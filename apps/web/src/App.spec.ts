import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App.vue";
import { router } from "./router";

const emptyResponses: Record<string, unknown> = {
  "/api/v1/system": {
    product: {
      name: "Knemora",
      edition: "community",
      description:
        "Open-source, local-first knowledge and agent platform with a native Second Brain graph, a portable Markdown wiki, and local AI inference.",
      website: null,
      support_url: null,
    },
    versions: {
      app_version: "0.8.0",
      schema_version: 9,
      knowledge_schema_version: 1,
    },
    capabilities: [
      "audit",
      "authentication",
      "dataset_analysis",
      "document_ingestion",
      "local_inference",
      "native_second_brain",
      "rbac",
      "wiki_graph",
      "wiki_search",
    ],
    telemetry_enabled: false,
    authentication: { default_email: "admin@knemora.local" },
    demo: {
      active: false,
      preset: null,
      topic: null,
      synthetic: false,
    },
  },
  "/api/v1/auth/me": {
    id: "user-1",
    email: "admin@example.test",
    display_name: "Alex Example",
    first_name: "Alex",
    last_name: "Example",
    company: null,
    visualization_name: "Alex",
    is_active: true,
    roles: ["administrator"],
    permissions: [
      "chat.use",
      "document.read",
      "ingestion.read",
      "knowledge.read",
      "dataset.analyze",
      "user.manage",
      "role.manage",
      "audit.read",
      "settings.manage",
    ],
    last_login_at: null,
  },
  "/api/v1/documents": {
    items: [],
    page: 1,
    page_limit: 5,
    total: 0,
    total_pages: 0,
  },
  "/api/v1/datasets": {
    items: [],
    page: 1,
    page_limit: 5,
    total: 0,
    total_pages: 0,
  },
  "/api/v1/wiki/pages": [],
  "/api/v1/wiki/page-index": {
    items: [],
    page: 1,
    page_limit: 8,
    total: 0,
    total_pages: 0,
  },
  "/api/v1/wiki/graph": {
    mode: "global",
    root_id: null,
    depth: null,
    nodes: [],
    edges: [],
    diagnostics: [],
    unresolved_count: 0,
    ambiguous_count: 0,
    total_nodes: 0,
    total_edges: 0,
    isolated_nodes: 0,
    returned_nodes: 0,
    returned_edges: 0,
    truncated: false,
    small_graph_threshold: 50,
    freshness: {
      revision: "empty",
      wiki_revision: 0,
      indexed_at: "2026-10-05T12:00:00Z",
      file_count: 0,
    },
  },
  "/api/v1/conversations": {
    items: [],
    page: 1,
    page_limit: 8,
    total: 0,
    total_pages: 0,
  },
};

let stored: Record<string, string>;

beforeEach(() => {
  stored = {};
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      getItem: (key: string) => stored[key] ?? null,
      setItem: (key: string, value: string) => {
        stored[key] = value;
      },
      removeItem: (key: string) => {
        delete stored[key];
      },
    },
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify(emptyResponses["/api/v1/system"]), {
          status: 200,
        }),
      ),
    ),
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("requires a local authenticated session", async () => {
    await router.push("/");
    await router.isReady();
    const wrapper = mount(App, {
      global: { plugins: [createPinia(), router] },
    });
    await flushPromises();

    expect(wrapper.text()).not.toContain("Sign in to Knemora");
    expect(wrapper.text()).toContain("Your session stays on this workstation");
    expect(wrapper.find("input[type='password']").exists()).toBe(true);
  });

  it("opens Overview after a successful sign-in", async () => {
    const user = emptyResponses["/api/v1/auth/me"];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL | Request) => {
        const path = new URL(String(input)).pathname;
        const body =
          path === "/api/v1/auth/login"
            ? {
                access_token: "signed-in-token",
                token_type: "bearer",
                expires_at: "2026-10-05T12:00:00Z",
                user,
              }
            : (emptyResponses[path] ?? []);
        return Promise.resolve(
          new Response(JSON.stringify(body), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }),
    );
    await router.push("/knowledge");
    await router.isReady();
    const wrapper = mount(App, {
      global: { plugins: [createPinia(), router] },
    });
    await flushPromises();

    await wrapper
      .get("input[type='password']")
      .setValue("local password value");
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(router.currentRoute.value.name).toBe("overview");
    expect(wrapper.text()).toContain("Welcome, Alex");
  });

  it("renders the product shell and core workflow navigation", async () => {
    window.localStorage.setItem("knemora.session", "test-token");
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL | Request) => {
        const path = new URL(String(input)).pathname;
        return Promise.resolve(
          new Response(JSON.stringify(emptyResponses[path]), { status: 200 }),
        );
      }),
    );
    await router.push("/");
    await router.isReady();
    const wrapper = mount(App, {
      global: { plugins: [createPinia(), router] },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("Knemora");
    expect(wrapper.text()).toContain("Welcome, Alex");
    expect(wrapper.get(".brand-logo").attributes("src")).toBe(
      "/knemora-logo.svg",
    );
    const navigation = wrapper
      .findAll("nav[aria-label='Main navigation'] a")
      .map((item) => item.text());
    expect(navigation.slice(0, 8)).toEqual([
      "Overview",
      "AI Chat",
      "Second Brain",
      "Knowledge",
      "Documents",
      "Ingestion",
      "Datasets",
      "Analytics",
    ]);
    expect(wrapper.text()).toContain("Knemora updates");
    expect(wrapper.text()).not.toContain("Local · private by default");
    expect(navigation).not.toEqual(
      expect.arrayContaining(["Users", "Roles", "Settings"]),
    );
    const secondBrainLink = wrapper
      .findAll("nav[aria-label='Main navigation'] a")
      .find((item) => item.text().includes("Second Brain"));
    expect(secondBrainLink?.find(".lucide-brain-circuit").exists()).toBe(true);
    expect(router.getRoutes().map((route) => route.path)).not.toEqual(
      expect.arrayContaining(["/users", "/roles", "/settings"]),
    );
  });

  it("shows update details and reconnects to a durable job after restart", async () => {
    vi.useFakeTimers();
    window.localStorage.setItem("knemora.session", "test-token");
    let jobReads = 0;
    const update = {
      state: "update_available",
      channel: "master",
      checked_at: "2026-10-07T12:00:00Z",
      last_attempt_at: "2026-10-07T12:00:00Z",
      cached: false,
      running: {
        sha: "a".repeat(40),
        short_sha: "aaaaaaaaaaaa",
        app_version: "0.1.0-alpha",
        tag: null,
      },
      target: {
        sha: "b".repeat(40),
        short_sha: "bbbbbbbbbbbb",
        app_version: "0.1.0-alpha",
        tag: null,
      },
      branch: "master",
      relation: "behind",
      dirty: false,
      installable: true,
      blocked_reason: null,
      error: null,
      changes: [
        {
          sha: "b".repeat(40),
          short_sha: "bbbbbbbbbbbb",
          subject: "feat: safe updates",
          url: "https://github.com/federicolaterra/knemora/commit/example",
          pull_request_number: null,
          pull_request_title: null,
          pull_request_url: null,
        },
      ],
      changes_truncated: false,
      dependency_changes: [],
      migration_changes: [],
      restart_required: true,
      privacy_notice: "No private knowledge is sent.",
      active_job: null,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL | Request, init?: RequestInit) => {
        const path = new URL(String(input)).pathname;
        if (path === "/api/v1/updates/jobs/job-1") {
          jobReads += 1;
          if (jobReads === 1)
            return Promise.reject(new TypeError("API restarting"));
          return Promise.resolve(
            new Response(
              JSON.stringify({
                id: "job-1",
                status: "complete",
                stage: "complete",
                message: "Update installed and verified.",
                target_sha: "b".repeat(40),
                running_sha: "a".repeat(40),
                backup: "/backup.zip",
                previous_checkout: "/previous",
                error: null,
              }),
              { status: 200 },
            ),
          );
        }
        if (path === "/api/v1/updates/jobs" && init?.method === "POST") {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                id: "job-1",
                status: "queued",
                stage: "queued",
                message: "Update queued.",
                target_sha: "b".repeat(40),
                running_sha: "a".repeat(40),
                backup: null,
                previous_checkout: null,
                error: null,
              }),
              { status: 202 },
            ),
          );
        }
        const body =
          path === "/api/v1/updates" ? update : (emptyResponses[path] ?? []);
        return Promise.resolve(
          new Response(JSON.stringify(body), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }),
    );
    await router.push("/");
    await router.isReady();
    const wrapper = mount(App, {
      global: { plugins: [createPinia(), router] },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("Update available");
    await wrapper
      .get("button[title='Open update details'], .runtime-card button")
      .trigger("click");
    expect(wrapper.text()).toContain("feat: safe updates");
    const install = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Install update"));
    expect(install).toBeTruthy();
    void install!.trigger("click");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(1_500);
    await flushPromises();
    await vi.advanceTimersByTimeAsync(1_500);
    await flushPromises();

    expect(jobReads).toBe(2);
    expect(wrapper.text()).toContain("Update installed and verified.");
    expect(wrapper.text()).toContain("Reload application");
  });

  it("exposes the Development Wiki without mutation workflows in demo mode", async () => {
    window.localStorage.setItem("knemora.session", "test-token");
    const demoSystem = {
      ...(emptyResponses["/api/v1/system"] as Record<string, unknown>),
      capabilities: [
        "audit",
        "local_inference",
        "native_second_brain",
        "wiki_graph",
        "wiki_search",
      ],
      demo: {
        active: true,
        preset: "development",
        topic: "Development",
        synthetic: true,
      },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL | Request) => {
        const path = new URL(String(input)).pathname;
        const response =
          path === "/api/v1/system" ? demoSystem : emptyResponses[path];
        return Promise.resolve(
          new Response(JSON.stringify(response ?? []), { status: 200 }),
        );
      }),
    );
    await router.push("/");
    await router.isReady();
    const wrapper = mount(App, {
      global: { plugins: [createPinia(), router] },
    });
    await flushPromises();

    const navigation = wrapper
      .findAll("nav[aria-label='Main navigation'] a")
      .map((item) => item.text());
    expect(navigation).toEqual(
      expect.arrayContaining(["AI Chat", "Knowledge", "Second Brain"]),
    );
    expect(navigation).not.toEqual(
      expect.arrayContaining([
        "Documents",
        "Ingestion",
        "Datasets",
        "Users",
        "Roles",
        "Settings",
      ]),
    );
    expect(wrapper.text()).not.toContain("Add sources");
    expect(wrapper.text()).not.toContain("Analyze dataset");
  });

  it("opens the native Second Brain empty state", async () => {
    window.localStorage.setItem("knemora.session", "test-token");
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL | Request) => {
        const path = new URL(String(input)).pathname;
        return Promise.resolve(
          new Response(JSON.stringify(emptyResponses[path] ?? []), {
            status: 200,
          }),
        );
      }),
    );
    await router.push("/second-brain");
    await router.isReady();
    const wrapper = mount(App, {
      global: { plugins: [createPinia(), router] },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("Second Brain");
    expect(wrapper.text()).toContain("Your Second Brain is empty");
    expect(wrapper.text()).toContain("Open ingestion");
  });

  it("labels generated knowledge and opens its immutable original", async () => {
    window.localStorage.setItem("knemora.session", "test-token");
    const pageId = "b314c345-df21-5647-9d48-561124e0cc9d";
    const provenance = {
      source_record_id: "source-record-1",
      document_id: "document-1",
      document_version_id: "document-version-1",
      original_filename: "Federico_La_Terra_Skills.txt",
      sha256: "a".repeat(64),
      locator: { line_start: 1, line_end: 53 },
      parser_name: "knemora-text",
      parser_version: "1.0.0",
      compilation_version: "knemora-wiki/1",
      compiled_at: "2026-10-07T12:00:00Z",
    };
    const wikiPage = {
      id: pageId,
      type: "concept",
      title: "JavaScript",
      aliases: [],
      topics: ["programming"],
      summary:
        "Avery Morgan works in the JavaScript ecosystem through their frontend and backend stack.",
      created_at: "2026-10-07T12:00:00Z",
      updated_at: "2026-10-07T12:00:00Z",
      compilation_version: "knemora-wiki/1",
      provenance: [provenance],
      claims: [
        {
          id: "claim-1",
          key: "used_by",
          text: "Avery Morgan uses JavaScript in their work context.",
          classification: "source_fact",
          status: "supported",
          provenance: [provenance],
          conflicts_with: [],
        },
      ],
      relationships: [],
    };
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const url = new URL(String(input));
      if (
        url.pathname === "/api/v1/document-versions/document-version-1/original"
      )
        return Promise.resolve(new Response(new Blob(["immutable source"])));
      const body =
        url.pathname === `/api/v1/wiki/pages/${pageId}`
          ? wikiPage
          : url.pathname.endsWith("/backlinks") ||
              url.pathname.endsWith("/related")
            ? []
            : (emptyResponses[url.pathname] ?? []);
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:immutable-original");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
      () => undefined,
    );
    await router.push(`/knowledge/${pageId}`);
    await router.isReady();
    const wrapper = mount(App, {
      global: { plugins: [createPinia(), router] },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("AI-generated summary");
    expect(wrapper.text()).toContain("AI-generated claims");
    const original = wrapper.get(
      'button[title="Open immutable original: Federico_La_Terra_Skills.txt"]',
    );
    expect(original.text()).toContain("Immutable original");
    await original.trigger("click");
    await flushPromises();

    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes(
          "/api/v1/document-versions/document-version-1/original",
        ),
      ),
    ).toBe(true);
  });

  it("persists dismissal of completed deletion notices", async () => {
    vi.useFakeTimers();
    window.localStorage.setItem("knemora.session", "test-token");
    const deletions = [
      {
        id: "deletion-skills",
        document_id: "document-skills",
        display_filename: "Federico_La_Terra_Skills.txt",
        status: "COMPLETED",
        stage: "COMPLETED",
        attempt_count: 1,
        error: null,
        created_at: "2026-10-07T12:00:00Z",
        updated_at: "2026-10-07T12:01:00Z",
        finished_at: "2026-10-07T12:01:00Z",
      },
      {
        id: "deletion-travel",
        document_id: "document-travel",
        display_filename: "05_Munich_Private_Travel_Notes.txt",
        status: "COMPLETED",
        stage: "COMPLETED",
        attempt_count: 1,
        error: null,
        created_at: "2026-10-07T11:00:00Z",
        updated_at: "2026-10-07T11:01:00Z",
        finished_at: "2026-10-07T11:01:00Z",
      },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL | Request) => {
        const url = new URL(String(input));
        let body = emptyResponses[url.pathname] ?? [];
        if (url.pathname === "/api/v1/source-deletion-operations")
          body = deletions;
        if (
          url.pathname === "/api/v1/documents" &&
          url.searchParams.has("page")
        )
          body = {
            items: [],
            page: 1,
            page_limit: 15,
            total: 0,
            total_pages: 0,
          };
        return Promise.resolve(
          new Response(JSON.stringify(body), { status: 200 }),
        );
      }),
    );
    await router.push("/documents");
    await router.isReady();
    const wrapper = mount(App, {
      global: { plugins: [createPinia(), router] },
    });
    await vi.advanceTimersByTimeAsync(251);
    await flushPromises();

    expect(wrapper.text()).toContain(
      "Deleted Federico_La_Terra_Skills.txt and updated active knowledge.",
    );
    expect(wrapper.text()).toContain(
      "Deleted 05_Munich_Private_Travel_Notes.txt and updated active knowledge.",
    );
    await wrapper
      .get(
        'button[aria-label="Dismiss deletion notice for Federico_La_Terra_Skills.txt"]',
      )
      .trigger("click");

    expect(wrapper.text()).not.toContain(
      "Deleted Federico_La_Terra_Skills.txt and updated active knowledge.",
    );
    expect(wrapper.text()).toContain(
      "Deleted 05_Munich_Private_Travel_Notes.txt and updated active knowledge.",
    );
    expect(
      JSON.parse(
        window.localStorage.getItem("knemora.documents.dismissed-deletions") ??
          "[]",
      ),
    ).toEqual(["deletion-skills"]);

    wrapper.unmount();
    const reloaded = mount(App, {
      global: { plugins: [createPinia(), router] },
    });
    await vi.advanceTimersByTimeAsync(251);
    await flushPromises();

    expect(reloaded.text()).not.toContain(
      "Deleted Federico_La_Terra_Skills.txt and updated active knowledge.",
    );
    expect(reloaded.text()).toContain(
      "Deleted 05_Munich_Private_Travel_Notes.txt and updated active knowledge.",
    );
  });

  it("falls back to the global graph when a saved local root was deleted", async () => {
    window.localStorage.setItem("knemora.session", "test-token");
    window.sessionStorage.removeItem("knemora.second-brain.controls");
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const url = new URL(String(input));
      if (
        url.pathname === "/api/v1/wiki/graph" &&
        url.searchParams.get("root") === "deleted-page"
      ) {
        return Promise.resolve(
          new Response(JSON.stringify({ detail: "deleted-page" }), {
            status: 404,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify(emptyResponses[url.pathname] ?? []), {
          status: 200,
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    await router.push("/second-brain?mode=local&root=deleted-page&depth=1");
    await router.isReady();
    const wrapper = mount(App, {
      global: { plugins: [createPinia(), router] },
    });
    await flushPromises();
    await flushPromises();

    expect(wrapper.text()).toContain(
      "The selected local root no longer exists. Showing the global graph.",
    );
    expect(wrapper.text()).not.toContain("Graph unavailable");
    expect(router.currentRoute.value.query).toEqual({});
    expect(
      fetchMock.mock.calls.some(([input]) => {
        const url = new URL(String(input));
        return (
          url.pathname === "/api/v1/wiki/graph" &&
          url.searchParams.get("root") === "deleted-page"
        );
      }),
    ).toBe(true);
    expect(
      fetchMock.mock.calls.some(([input]) => {
        const url = new URL(String(input));
        return (
          url.pathname === "/api/v1/wiki/graph" && !url.searchParams.has("root")
        );
      }),
    ).toBe(true);
  });

  it("returns to login when a stored session has expired", async () => {
    window.localStorage.setItem("pharmatrace.session", "expired-token");
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({ detail: "Authentication is required." }),
            {
              status: 401,
              headers: { "Content-Type": "application/json" },
            },
          ),
        ),
      ),
    );
    await router.push("/");
    await router.isReady();
    const wrapper = mount(App, {
      global: { plugins: [createPinia(), router] },
    });
    await flushPromises();

    expect(wrapper.text()).not.toContain("Sign in to Knemora");
    expect(wrapper.text()).toContain("Your session stays on this workstation");
    expect(window.localStorage.getItem("pharmatrace.session")).toBeNull();
    expect(window.localStorage.getItem("knemora.session")).toBeNull();
  });
});
