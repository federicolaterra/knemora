import type {
  AuditEventRecord,
  AuthSession,
  Conversation,
  CurrentUser,
  DatasetResult,
  DocumentRecord,
  Message,
  MetricsResponse,
  PageSummary,
  PaginatedResponse,
  ProblemDetail,
  RoleRecord,
  SourceDeletionOperation,
  SystemMetadata,
  UpdateJob,
  UpdateSnapshot,
  WikiPage,
  WikiGraphResponse,
  WikiMarkdownPage,
} from "../types";

export const API_BASE =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly requestId?: string,
  ) {
    super(message);
  }
}

const TOKEN_KEY = "knemora.session";
const LEGACY_TOKEN_KEY = "pharmatrace.session";

export function getAccessToken(): string | null {
  const current = window.localStorage.getItem(TOKEN_KEY);
  if (current) return current;
  const legacy = window.localStorage.getItem(LEGACY_TOKEN_KEY);
  if (legacy) {
    window.localStorage.setItem(TOKEN_KEY, legacy);
    window.localStorage.removeItem(LEGACY_TOKEN_KEY);
  }
  return legacy;
}

export function setAccessToken(token: string | null): void {
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else {
    window.localStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(LEGACY_TOKEN_KEY);
  }
}

function authenticatedInit(init?: RequestInit): RequestInit {
  const headers = new Headers(init?.headers);
  const token = getAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return { ...init, headers };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, authenticatedInit(init));
  if (!response.ok) {
    let problem: ProblemDetail = {};
    try {
      problem = (await response.json()) as ProblemDetail;
    } catch {
      // The status text is still useful when a proxy returns a non-JSON response.
    }
    if (response.status === 401 && getAccessToken()) {
      setAccessToken(null);
      window.dispatchEvent(new Event("knemora:unauthorized"));
    }
    throw new ApiError(
      problem.detail ?? problem.title ?? response.statusText,
      response.status,
      problem.request_id,
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  readSystem: () => request<SystemMetadata>("/api/v1/system"),
  login: (email: string, password: string) =>
    request<AuthSession>("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<CurrentUser>("/api/v1/auth/me"),
  updateProfile: (profile: {
    email: string;
    first_name: string | null;
    last_name: string | null;
    company: string | null;
    visualization_name: string | null;
  }) =>
    request<CurrentUser>("/api/v1/auth/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profile),
    }),
  updatePassword: (
    currentPassword: string,
    newPassword: string,
    confirmPassword: string,
  ) =>
    request<void>("/api/v1/auth/password", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
        confirm_password: confirmPassword,
      }),
    }),
  logout: () => request<void>("/api/v1/auth/logout", { method: "POST" }),
  listUsers: () => request<CurrentUser[]>("/api/v1/users"),
  listRoles: () => request<RoleRecord[]>("/api/v1/roles"),
  listAuditEvents: (page = 1, pageLimit = 15, eventType = "") => {
    const parameters = new URLSearchParams({
      page: String(page),
      page_limit: String(pageLimit),
    });
    if (eventType.trim()) parameters.set("event_type", eventType.trim());
    return request<PaginatedResponse<AuditEventRecord>>(
      `/api/v1/audit-events?${parameters}`,
    );
  },
  readSettings: () => request<Record<string, unknown>>("/api/v1/settings"),
  readMetrics: () => request<MetricsResponse>("/api/v1/metrics"),
  readUpdate: () => request<UpdateSnapshot>("/api/v1/updates"),
  checkUpdate: () =>
    request<UpdateSnapshot>("/api/v1/updates/check", { method: "POST" }),
  startUpdate: (targetSha: string) =>
    request<UpdateJob>("/api/v1/updates/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_sha: targetSha }),
    }),
  readUpdateJob: (jobId: string) =>
    request<UpdateJob>(`/api/v1/updates/jobs/${encodeURIComponent(jobId)}`),
  listDocuments: () => request<DocumentRecord[]>("/api/v1/documents"),
  listDocumentPage: (
    page = 1,
    pageLimit = 10,
    query = "",
    filter = "all",
    status = "all",
    fileType = "all",
  ) => {
    const parameters = new URLSearchParams({
      page: String(page),
      page_limit: String(pageLimit),
      q: query,
      filter,
      status,
      file_type: fileType,
    });
    return request<PaginatedResponse<DocumentRecord>>(
      `/api/v1/documents?${parameters}`,
    );
  },
  deleteDocument: (documentId: string) =>
    request<SourceDeletionOperation>(`/api/v1/documents/${documentId}`, {
      method: "DELETE",
    }),
  listSourceDeletions: () =>
    request<SourceDeletionOperation[]>("/api/v1/source-deletion-operations"),
  retrySourceDeletion: (operationId: string) =>
    request<SourceDeletionOperation>(
      `/api/v1/source-deletion-operations/${operationId}/retry`,
      { method: "POST" },
    ),
  uploadDocument: async (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<{
      document_version_id: string;
      ingestion_job_id: string;
      status: string;
    }>("/api/v1/documents", { method: "POST", body });
  },
  retryIngestion: (jobId: string) =>
    request(`/api/v1/ingestion-jobs/${jobId}/retry`, { method: "POST" }),
  reprocessIngestion: (jobId: string) =>
    request(`/api/v1/ingestion-jobs/${jobId}/reprocess`, { method: "POST" }),
  compileDocument: (versionId: string) =>
    request(`/api/v1/document-versions/${versionId}/compile`, {
      method: "POST",
    }),
  listWikiPages: () => request<PageSummary[]>("/api/v1/wiki/pages"),
  listWikiPageIndex: (page = 1, pageLimit = 8, query = "", kind = "all") => {
    const parameters = new URLSearchParams({
      page: String(page),
      page_limit: String(pageLimit),
      q: query,
    });
    if (kind !== "all") parameters.set("kind", kind);
    return request<PaginatedResponse<PageSummary>>(
      `/api/v1/wiki/page-index?${parameters}`,
    );
  },
  searchWiki: (query: string) =>
    request<PageSummary[]>(
      `/api/v1/wiki/search?q=${encodeURIComponent(query)}&limit=50`,
    ),
  getWikiPage: (identifier: string) =>
    request<WikiPage>(`/api/v1/wiki/pages/${encodeURIComponent(identifier)}`),
  getBacklinks: (identifier: string) =>
    request<PageSummary[]>(
      `/api/v1/wiki/pages/${encodeURIComponent(identifier)}/backlinks`,
    ),
  getRelated: (identifier: string) =>
    request<Array<PageSummary & { depth?: number; relationship?: string }>>(
      `/api/v1/wiki/pages/${encodeURIComponent(identifier)}/related?max_depth=2&limit=30`,
    ),
  getWikiGraph: (
    options: {
      root?: string;
      depth?: number;
      refresh?: boolean;
    } = {},
  ) => {
    const parameters = new URLSearchParams();
    if (options.root) parameters.set("root", options.root);
    if (options.depth) parameters.set("depth", String(options.depth));
    if (options.refresh) parameters.set("refresh", "true");
    const query = parameters.size ? `?${parameters}` : "";
    return request<WikiGraphResponse>(`/api/v1/wiki/graph${query}`);
  },
  getWikiMarkdownPage: (path: string) =>
    request<WikiMarkdownPage>(
      `/api/v1/wiki/files/${path
        .split("/")
        .map((part) => encodeURIComponent(part))
        .join("/")}`,
    ),
  listConversations: () => request<Conversation[]>("/api/v1/conversations"),
  listConversationPage: (page = 1, pageLimit = 15, query = "") => {
    const parameters = new URLSearchParams({
      page: String(page),
      page_limit: String(pageLimit),
      q: query,
    });
    return request<PaginatedResponse<Conversation>>(
      `/api/v1/conversations?${parameters}`,
    );
  },
  getConversation: (id: string) =>
    request<Conversation>(`/api/v1/conversations/${id}`),
  renameConversation: (id: string, title: string) =>
    request<Conversation>(`/api/v1/conversations/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),
  createConversation: (title?: string) =>
    request<Conversation>("/api/v1/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: title || null }),
    }),
  deleteConversation: (id: string) =>
    request<void>(`/api/v1/conversations/${id}`, { method: "DELETE" }),
  listMessages: (id: string) =>
    request<Message[]>(`/api/v1/conversations/${id}/messages`),
  listDatasetPage: (page = 1, pageLimit = 5, query = "") => {
    const parameters = new URLSearchParams({
      page: String(page),
      page_limit: String(pageLimit),
      q: query,
    });
    return request<PaginatedResponse<DocumentRecord>>(
      `/api/v1/datasets?${parameters}`,
    );
  },
  getDataset: (versionId: string) =>
    request<DocumentRecord>(`/api/v1/datasets/${versionId}`),
  analyzeDataset: (versionId: string, body: Record<string, unknown>) =>
    request<DatasetResult>(`/api/v1/datasets/${versionId}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};

export async function streamMessage(
  conversationId: string,
  content: string,
  signal: AbortSignal,
  onDelta: (delta: string) => void,
): Promise<void> {
  const response = await fetch(
    `${API_BASE}/api/v1/conversations/${conversationId}/messages/stream`,
    {
      method: "POST",
      headers: authenticatedInit({
        headers: { "Content-Type": "application/json" },
      }).headers,
      body: JSON.stringify({ content }),
      signal,
    },
  );
  if (!response.ok || !response.body) {
    const problem = (await response.json().catch(() => ({}))) as ProblemDetail;
    throw new ApiError(
      problem.detail ?? "Unable to stream a response.",
      response.status,
    );
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const event = block.match(/^event:\s*(.+)$/m)?.[1];
      const raw = block.match(/^data:\s*(.+)$/m)?.[1];
      if (!raw) continue;
      const data = JSON.parse(raw) as { delta?: string; error?: string };
      if (event === "message.delta" && data.delta) onDelta(data.delta);
      if (event === "error")
        throw new Error(data.error ?? "The response stream failed.");
    }
    if (done) break;
  }
}

export async function openOriginalSource(path: string): Promise<void> {
  const response = await fetch(`${API_BASE}${path}`, authenticatedInit());
  if (!response.ok)
    throw new ApiError("Unable to open the original source.", response.status);
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.target = "_blank";
  anchor.rel = "noopener noreferrer";
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
