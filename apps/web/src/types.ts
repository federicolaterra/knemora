export interface ProblemDetail {
  title?: string;
  detail?: string;
  status?: number;
  request_id?: string;
}

export type ResponseMode = "wiki" | "direct";

export interface SystemMetadata {
  product: {
    name: string;
    edition: string;
    description: string;
    website: string | null;
    support_url: string | null;
  };
  versions: {
    app_version: string;
    schema_version: number;
    knowledge_schema_version: number;
  };
  capabilities: string[];
  telemetry_enabled: boolean;
  demo: {
    active: boolean;
    preset: string | null;
    topic: string | null;
    synthetic: boolean;
  };
  authentication: {
    default_email: string;
  };
}

export interface UpdateRevision {
  sha: string;
  short_sha: string;
  app_version: string | null;
  tag: string | null;
}

export interface UpdateChange {
  sha: string;
  short_sha: string;
  subject: string;
  url: string;
  pull_request_number: number | null;
  pull_request_title: string | null;
  pull_request_url: string | null;
}

export interface UpdateJob {
  id: string;
  status: "queued" | "running" | "complete" | "failed";
  stage: string;
  message: string;
  target_sha: string;
  running_sha: string | null;
  backup: string | null;
  previous_checkout: string | null;
  error: string | null;
}

export interface UpdateSnapshot {
  state:
    | "checking"
    | "up_to_date"
    | "update_available"
    | "development"
    | "blocked"
    | "unavailable"
    | "disabled";
  channel: "master";
  checked_at: string | null;
  cached: boolean;
  running: UpdateRevision | null;
  target: UpdateRevision | null;
  branch: string | null;
  relation: string;
  dirty: boolean;
  installable: boolean;
  blocked_reason: string | null;
  error: string | null;
  changes: UpdateChange[];
  changes_truncated: boolean;
  dependency_changes: string[];
  migration_changes: string[];
  restart_required: boolean;
  privacy_notice: string;
  active_job?: UpdateJob | null;
}

export interface CurrentUser {
  id: string;
  email: string;
  display_name: string;
  first_name: string | null;
  last_name: string | null;
  company: string | null;
  visualization_name: string | null;
  is_active: boolean;
  roles: string[];
  permissions: string[];
  last_login_at: string | null;
}

export interface AuthSession {
  access_token: string;
  token_type: "bearer";
  expires_at: string;
  user: CurrentUser;
}

export interface RoleRecord {
  id: string;
  name: string;
  description: string | null;
  permissions: string[];
}

export interface AuditEventRecord {
  id: string;
  actor_user_id: string | null;
  event_type: string;
  entity_type: string;
  entity_id: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  page: number;
  page_limit: number;
  total: number;
  total_pages: number;
}

export interface Conversation {
  id: string;
  user_id: string;
  title: string | null;
  message_count?: number;
  updated_at?: string;
  created_at?: string | null;
  last_activity_at?: string | null;
}

export interface Message {
  id?: string;
  sequence?: number;
  role: "user" | "assistant" | "system";
  content: string;
  model?: string | null;
  created_at?: string | null;
}

export interface PageSummary {
  id: string;
  type: "entity" | "concept" | "topic" | "synthesis" | "dataset";
  title: string;
  aliases: string[];
  topics: string[];
  path: string;
}

export interface ProvenanceRef {
  source_record_id: string;
  document_id: string;
  document_version_id: string;
  original_filename: string;
  sha256: string;
  locator: Record<string, unknown>;
  parser_name: string;
  parser_version: string;
  compilation_version: string;
  compiled_at: string;
}

export interface WikiClaim {
  id: string;
  key: string;
  text: string;
  classification: "source_fact" | "synthesis";
  status: "supported" | "disputed";
  provenance: ProvenanceRef[];
  conflicts_with: string[];
}

export interface WikiPage {
  id: string;
  type: PageSummary["type"];
  title: string;
  aliases: string[];
  topics: string[];
  summary: string;
  created_at: string;
  updated_at: string;
  compilation_version: string;
  provenance: ProvenanceRef[];
  claims: WikiClaim[];
  relationships: Array<{
    relation: string;
    target_id: string;
    target_title: string;
    provenance: ProvenanceRef[];
  }>;
}

export interface WikiGraphNode {
  id: string;
  page_id: string | null;
  title: string;
  aliases: string[];
  tags: string[];
  document_type: string;
  folder: string;
  path: string;
  detail_reference: string;
  modified_at: string;
  generated: boolean;
  degree: number;
  isolated: boolean;
}

export interface WikiGraphEdge {
  id: string;
  source: string;
  target: string;
  relations: string[];
  provenance: Array<"relationship" | "wikilink" | "markdown_link">;
}

export interface WikiGraphResponse {
  mode: "global" | "local";
  root_id: string | null;
  depth: number | null;
  nodes: WikiGraphNode[];
  edges: WikiGraphEdge[];
  diagnostics: Array<{
    source_id: string;
    source_path: string;
    target: string;
    reason: "ambiguous" | "unresolved";
  }>;
  unresolved_count: number;
  ambiguous_count: number;
  total_nodes: number;
  total_edges: number;
  isolated_nodes: number;
  returned_nodes: number;
  returned_edges: number;
  truncated: boolean;
  small_graph_threshold: number;
  freshness: {
    revision: string;
    wiki_revision: number;
    indexed_at: string;
    file_count: number;
  };
}

export interface WikiMarkdownPage {
  id: string;
  path: string;
  title: string;
  aliases: string[];
  tags: string[];
  document_type: string;
  modified_at: string;
  content: string;
}

export interface DocumentRecord {
  document_id: string;
  document_version_id: string;
  original_filename: string;
  version_number: number;
  content_type: string;
  byte_size: number;
  checksum: string;
  created_at: string;
  ingestion_job_id: string;
  ingestion_status: string;
  ingestion_error: string | null;
  ingestion_attempt_count: number;
  last_completed_stage: string | null;
  compilation_job_id: string | null;
  compilation_status: string | null;
  compilation_error: string | null;
  compilation_attempt_count: number | null;
  compilation_report: CompilationReport | null;
  is_dataset: boolean;
  original_url: string;
}

export interface SourceDeletionOperation {
  id: string;
  document_id: string;
  display_filename: string;
  status: "PENDING" | "RUNNING" | "FAILED" | "COMPLETED";
  stage: string;
  attempt_count: number;
  error: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
}

export interface CompilationReport {
  pages_created: PageSummary[];
  pages_updated: PageSummary[];
  warnings: string[];
  failures: string[];
  conflicts: unknown[];
  provenance_coverage: number;
}

export interface DatasetResult {
  operation: string;
  columns: string[];
  rows: Array<Record<string, unknown>>;
  row_count: number;
  truncated: boolean;
  chart: null | {
    type: "bar" | "line";
    x_column: string;
    x: unknown[];
    series: Array<{ name: string; values: unknown[] }>;
  };
  provenance: {
    document_id: string;
    document_version_id: string;
    original_filename: string;
    sha256: string;
    immutable_source_uri: string;
    sheet: string | null;
    source_columns: string[];
    source_row_count: number;
    filtered_row_count: number;
  };
}

export interface MetricsResponse {
  runtime: {
    counters: Record<string, number>;
    timings: Record<string, { count: number; average: number; max: number }>;
  };
  ingestion: {
    jobs: number;
    failures: number;
    average_duration_ms: number | null;
  };
  compilation: {
    jobs: number;
    failures: number;
    average_duration_ms: number | null;
  };
  knowledge: {
    pages: number;
    lint_errors: number;
    lint_warnings: number;
    issues: Record<string, number>;
    average_provenance_coverage: number | null;
    duplicate_uploads: number;
  };
  evaluation_only: Record<string, string>;
  privacy: {
    message_content_recorded: boolean;
    hidden_reasoning_recorded: boolean;
  };
}
