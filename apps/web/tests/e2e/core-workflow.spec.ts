import { Buffer } from "node:buffer";

import { expect, test } from "@playwright/test";

const documentRecord = {
  document_id: "doc-1",
  document_version_id: "version-1",
  original_filename: "distribution.csv",
  version_number: 1,
  content_type: "text/csv",
  byte_size: 2048,
  checksum: "abc123",
  created_at: "2026-09-27T12:00:00Z",
  ingestion_job_id: "job-1",
  ingestion_status: "READY_FOR_COMPILATION",
  ingestion_error: null,
  ingestion_attempt_count: 1,
  last_completed_stage: "NORMALIZING",
  compilation_job_id: "compile-1",
  compilation_status: "COMPLETED",
  compilation_error: null,
  compilation_attempt_count: 2,
  compilation_report: {
    pages_created: [{ id: "wiki-typescript", title: "TypeScript" }],
    pages_updated: [],
    warnings: [],
    failures: [],
    conflicts: [],
    provenance_coverage: 1,
  },
  is_dataset: true,
  original_url: "/api/v1/document-versions/version-1/original",
};

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() =>
    window.localStorage.setItem("knemora.session", "test-token"),
  );
  await page.route("http://localhost:8000/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === "/api/v1/system")
      return route.fulfill({
        json: {
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
      });
    if (path === "/api/v1/auth/me")
      return route.fulfill({
        json: {
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
            "document.upload",
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
      });
    if (path === "/api/v1/documents")
      return route.fulfill({
        json: url.searchParams.has("page")
          ? {
              items: [documentRecord],
              page: 1,
              page_limit: 15,
              total: 1,
              total_pages: 1,
            }
          : [documentRecord],
      });
    if (path === "/api/v1/wiki/pages") return route.fulfill({ json: [] });
    if (path === "/api/v1/wiki/page-index")
      return route.fulfill({
        json: {
          items: [],
          page: 1,
          page_limit: 8,
          total: 0,
          total_pages: 0,
        },
      });
    if (path === "/api/v1/wiki/pages/wiki-concept-distribution")
      return route.fulfill({
        json: {
          id: "wiki-concept-distribution",
          type: "concept",
          title: "Distribution",
          aliases: ["Statistical distribution"],
          topics: ["statistics"],
          summary: "A portable Markdown page.",
          created_at: "2026-10-05T12:00:00Z",
          updated_at: "2026-10-05T12:00:00Z",
          compilation_version: "knemora-wiki/1",
          provenance: [],
          claims: [
            {
              id: "claim-1",
              key: "definition",
              text: "A distribution describes possible values.",
              classification: "source_fact",
              status: "supported",
              provenance: [],
              conflicts_with: [],
            },
          ],
          relationships: [],
        },
      });
    if (
      path === "/api/v1/wiki/pages/wiki-concept-distribution/backlinks" ||
      path === "/api/v1/wiki/pages/wiki-concept-distribution/related"
    )
      return route.fulfill({ json: [] });
    if (path === "/api/v1/wiki/graph") {
      const root = url.searchParams.get("root");
      return route.fulfill({
        json: {
          mode: root ? "local" : "global",
          root_id: root,
          depth: root ? Number(url.searchParams.get("depth") ?? "1") : null,
          nodes: [
            {
              id: "wiki-concept-distribution",
              title: "Distribution",
              path: "wiki/concepts/distribution.md",
              detail_reference:
                "/knowledge/file/wiki%2Fconcepts%2Fdistribution.md",
              aliases: ["Statistical distribution"],
              tags: ["statistics"],
              document_type: "concept",
              folder: "concepts",
              modified_at: "2026-10-05T12:00:00Z",
              degree: 4,
              isolated: true,
              provenance_document_version_ids: [],
            },
          ],
          edges: [],
          diagnostics: [],
          unresolved_count: 0,
          ambiguous_count: 0,
          total_nodes: 1,
          total_edges: 0,
          isolated_nodes: 1,
          returned_nodes: 1,
          returned_edges: 0,
          truncated: false,
          small_graph_threshold: 50,
          freshness: {
            revision: "e2e-fixture",
            wiki_revision: 4,
            indexed_at: "2026-10-05T12:00:00Z",
            file_count: 1,
          },
        },
      });
    }
    if (path === "/api/v1/wiki/files/wiki/concepts/distribution.md")
      return route.fulfill({
        json: {
          id: "wiki-concept-distribution",
          title: "Distribution",
          path: "wiki/concepts/distribution.md",
          aliases: ["Statistical distribution"],
          tags: ["statistics"],
          document_type: "concept",
          modified_at: "2026-10-05T12:00:00Z",
          content: "# Distribution\n\nA portable Markdown page.",
        },
      });
    if (path === "/api/v1/datasets")
      return route.fulfill({
        json: {
          items: [documentRecord],
          page: 1,
          page_limit: 5,
          total: 1,
          total_pages: 1,
        },
      });
    if (
      path === "/api/v1/datasets/version-1/analyze" &&
      route.request().method() === "POST"
    )
      return route.fulfill({
        json: {
          operation: "describe",
          columns: ["region", "revenue"],
          rows: [{ region: "North", revenue: 10 }],
          row_count: 1,
          truncated: false,
          chart: {
            type: "line",
            x_column: "region",
            x: ["North", "South"],
            series: [{ name: "revenue", values: [10, 20] }],
          },
          provenance: {
            document_id: "doc-1",
            document_version_id: "version-1",
            original_filename: "distribution.csv",
            sha256: "abc123",
            immutable_source_uri:
              "/api/v1/document-versions/version-1/original",
            sheet: null,
            source_columns: ["region", "revenue"],
            source_row_count: 1,
            filtered_row_count: 1,
          },
        },
      });
    if (path === "/api/v1/conversations")
      return route.fulfill({
        json: url.searchParams.has("page")
          ? {
              items: [
                {
                  id: "conversation-1",
                  user_id: "user-1",
                  title: "Research thread",
                  message_count: 2,
                },
              ],
              page: 1,
              page_limit: 8,
              total: 1,
              total_pages: 1,
            }
          : [
              {
                id: "conversation-1",
                user_id: "user-1",
                title: "Research thread",
                message_count: 2,
              },
            ],
      });
    if (path === "/api/v1/metrics")
      return route.fulfill({
        json: {
          runtime: {
            counters: { "http.GET./api/v1/documents.200": 4 },
            timings: {},
          },
          ingestion: { jobs: 2, failures: 0, average_duration_ms: 120 },
          compilation: { jobs: 2, failures: 1, average_duration_ms: 180 },
          knowledge: {
            pages: 1,
            lint_errors: 0,
            lint_warnings: 0,
            issues: {},
            average_provenance_coverage: 1,
            duplicate_uploads: 0,
          },
          evaluation_only: {},
          privacy: {
            message_content_recorded: false,
            hidden_reasoning_recorded: false,
          },
        },
      });
    if (path === "/api/v1/audit-events")
      return route.fulfill({
        json: {
          items: [
            {
              id: "audit-1",
              actor_user_id: "user-1",
              event_type: "document.uploaded",
              entity_type: "document",
              entity_id: "doc-1",
              payload: { filename: "distribution.csv" },
              created_at: "2026-09-27T12:00:00Z",
            },
          ],
          page: 1,
          page_limit: 15,
          total: url.searchParams.get("event_type") ? 1 : 16,
          total_pages: url.searchParams.get("event_type") ? 1 : 2,
        },
      });
    if (path === "/api/v1/updates")
      return route.fulfill({
        json: {
          state: "up_to_date",
          channel: "master",
          checked_at: "2026-10-09T12:00:00Z",
          cached: false,
          running: {
            sha: "abc123",
            short_sha: "abc123",
            app_version: "0.1.0-alpha",
            tag: null,
          },
          target: null,
          branch: "master",
          relation: "equal",
          dirty: false,
          installable: false,
          blocked_reason: null,
          error: null,
          changes: [],
          changes_truncated: false,
          dependency_changes: [],
          migration_changes: [],
          restart_required: false,
          privacy_notice: "Update checks contain no workspace content.",
          active_job: null,
        },
      });
    return route.fulfill({ json: {} });
  });
});

test("navigates the complete product workflow", async ({ page }, testInfo) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Welcome, Alex" }),
  ).toBeVisible();
  await expect(page.locator(".brand-logo")).toBeVisible();
  await expect(
    page
      .getByRole("link", { name: "Audit logs", exact: true })
      .locator("svg.lucide-shield-ellipsis"),
  ).toBeVisible();
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute(
    "href",
    "/favicon.svg",
  );
  await page.getByRole("button", { name: "Collapse navigation" }).click();
  await expect(page.locator(".brand-icon")).toBeVisible();
  await page.getByRole("button", { name: "Expand navigation" }).click();
  await expect(page.locator(".update-status-card strong")).toHaveCSS(
    "font-size",
    "12px",
  );
  await expect(page.locator(".update-status-card small")).toHaveCSS(
    "font-size",
    "11px",
  );
  await page
    .getByRole("link", { name: "Open profile for Alex Example" })
    .click();
  await expect(page.getByRole("heading", { name: "Profile" })).toBeVisible();
  await expect(page.getByLabel("Visualization name")).toHaveValue("Alex");
  await expect(
    page.getByRole("heading", { name: "Personal details" }),
  ).toHaveCSS("font-size", "19px");
  await expect(
    page.getByRole("heading", { name: "Personal details" }),
  ).toHaveCSS("font-weight", "500");
  await expect(page.getByRole("heading", { name: "Password" })).toHaveCSS(
    "font-size",
    "19px",
  );
  await expect(page.getByText("Used only inside this workspace.")).toHaveCSS(
    "font-size",
    "12px",
  );
  await expect(page.getByText("Use at least 12 characters.")).toHaveCSS(
    "font-size",
    "12px",
  );
  const updatePasswordButton = page.getByRole("button", {
    name: "Update password",
  });
  await expect(updatePasswordButton).toHaveCSS(
    "border-color",
    "rgb(169, 187, 180)",
  );
  await updatePasswordButton.hover();
  await expect(updatePasswordButton).toHaveCSS(
    "transform",
    "matrix(1, 0, 0, 1, 0, -1)",
  );
  await page.getByRole("button", { name: "Open update details" }).click();
  await expect(
    page.getByRole("dialog", { name: "Knemora update" }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("dialog", { name: "Knemora update" })
      .locator(".text-caption")
      .first(),
  ).toHaveCSS("font-size", "12px");
  await expect(
    page
      .getByRole("dialog", { name: "Knemora update" })
      .getByRole("button", { name: "Cancel" }),
  ).toHaveCSS("font-size", "12px");
  await expect(
    page
      .getByRole("dialog", { name: "Knemora update" })
      .getByRole("button", { name: "Check for updates" }),
  ).toHaveCSS("font-size", "12px");
  await page.getByRole("button", { name: "Close update dialog" }).click();
  await page.getByRole("link", { name: "Overview", exact: true }).click();
  await expect(page.getByText("Explore knowledge", { exact: true })).toHaveCSS(
    "font-size",
    "12px",
  );
  await expect(page.getByText("View all", { exact: true })).toHaveCSS(
    "font-size",
    "12px",
  );
  await expect(page.locator(".stat-card > strong").first()).toHaveCSS(
    "font-size",
    "31px",
  );
  await expect(page.locator(".orbit-dot")).toHaveCSS("width", "12px");
  await expect(page.locator(".orbit-dot")).toHaveCSS("height", "12px");
  await expect(page.locator(".orbit-dot")).toHaveCSS(
    "animation-name",
    "knowledge-orbit",
  );
  await expect(page.locator(".orbit-dot")).toHaveCSS(
    "animation-duration",
    "6s",
  );
  await expect(
    page
      .locator(".stat-card")
      .filter({ hasText: "Conversations" })
      .locator("h2"),
  ).toHaveCSS("font-size", "14px");
  await expect(
    page.locator(".stat-card").filter({ hasText: "Datasets" }).locator("h2"),
  ).toHaveCSS("font-size", "14px");
  await expect(page.locator(".stat-card p").first()).toHaveCSS(
    "font-size",
    "13px",
  );
  await expect(page.locator(".overview-action-card strong").first()).toHaveCSS(
    "font-size",
    "14px",
  );
  await expect(page.locator(".overview-action-card small").first()).toHaveCSS(
    "font-size",
    "13px",
  );
  await expect(
    page.locator(".recent-card .compact-status-badge").first(),
  ).toHaveCSS("font-size", "10px");
  await page.screenshot({
    path: testInfo.outputPath("overview.png"),
    animations: "disabled",
  });
  await page.getByRole("link", { name: "Documents", exact: true }).click();
  await expect(page.getByText("distribution.csv")).toBeVisible();
  await expect(
    page.getByText("PDF, TXT, Markdown, DOCX, CSV, or XLSX · up to 25 MB each"),
  ).toHaveCSS("font-size", "12px");
  await expect(page.locator("tbody td").first()).toHaveCSS("font-size", "12px");
  await expect(page.locator("tbody td").first().locator("strong")).toHaveCSS(
    "font-size",
    "12px",
  );
  await expect(page.locator("tbody td").first().locator("small")).toHaveCSS(
    "font-size",
    "12px",
  );
  await expect(
    page.locator(".responsive-table .compact-status-badge").first(),
  ).toHaveCSS("font-size", "10px");
  await page.locator('input[type="file"]').setInputFiles({
    name: "preview.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("queued preview"),
  });
  await expect(page.getByText("preview.txt", { exact: true })).toHaveCSS(
    "font-size",
    "12px",
  );
  await expect(page.getByText("queued", { exact: true })).toHaveCSS(
    "font-size",
    "12px",
  );
  await expect(page.getByText("1 source versions · 10 per page")).toHaveCSS(
    "font-size",
    "12px",
  );
  await page.screenshot({
    path: testInfo.outputPath("documents.png"),
    animations: "disabled",
  });
  const documentSearch = page.getByPlaceholder("Search files…");
  await documentSearch.focus();
  await expect(documentSearch).toHaveCSS(
    "box-shadow",
    "rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px",
  );
  await expect(documentSearch.locator("..")).toHaveCSS(
    "border-color",
    "rgb(51, 209, 51)",
  );
  await expect(documentSearch.locator("..")).toHaveCSS(
    "box-shadow",
    "rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(51, 209, 51, 0.09) 0px 0px 0px 3px",
  );
  await expect(page.getByLabel("Filter documents")).toHaveCSS(
    "font-size",
    "12px",
  );
  await page.getByRole("link", { name: "Ingestion", exact: true }).click();
  await expect(
    page.getByText("KNOWLEDGE", { exact: false }).first(),
  ).toBeVisible();
  await expect(page.getByLabel("Filter ingestion status")).toHaveCSS(
    "font-size",
    "12px",
  );
  await expect(page.getByLabel("Filter ingestion file type")).toHaveCSS(
    "font-size",
    "12px",
  );
  await expect(page.locator(".file-symbol").first()).toHaveCSS(
    "font-size",
    "10px",
  );
  await expect(page.locator(".source-file-copy h2").first()).toHaveCSS(
    "font-size",
    "12px",
  );
  await expect(page.locator(".source-file-copy p").first()).toHaveCSS(
    "font-size",
    "12px",
  );
  await expect(page.locator(".stage-rail li small").first()).toHaveCSS(
    "font-size",
    "10px",
  );
  await expect(page.locator(".status-badge").first()).toHaveCSS(
    "font-size",
    "10px",
  );
  await expect(page.getByRole("link", { name: "TypeScript" })).toHaveCSS(
    "font-size",
    "11px",
  );
  await expect(
    page.getByText("pages created", { exact: false }).first(),
  ).toHaveCSS("font-size", "12px");
  await expect(
    page.getByText("pages updated", { exact: false }).first(),
  ).toHaveCSS("font-size", "12px");
  await expect(
    page.getByText("provenance coverage", { exact: false }).first(),
  ).toHaveCSS("font-size", "12px");
  await expect(page.getByText("1 source versions · 10 per page")).toHaveCSS(
    "font-size",
    "12px",
  );
  await page.screenshot({
    path: testInfo.outputPath("ingestion.png"),
    animations: "disabled",
  });
  await page.getByRole("link", { name: "Knowledge", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Select a Wiki page" }),
  ).toBeVisible();
  await expect(page.getByLabel("Filter page type")).toHaveCSS(
    "font-size",
    "12px",
  );
  await expect(
    page.getByText(
      "Open a page to inspect its claims, connections, and original-source provenance.",
    ),
  ).toHaveCSS("font-size", "14px");
  await expect(page.locator(".empty-compact")).toHaveCSS(
    "padding-left",
    "14px",
  );
  await expect(page.locator(".empty-compact")).toHaveCSS(
    "padding-right",
    "14px",
  );
  await page.screenshot({
    path: testInfo.outputPath("knowledge.png"),
    animations: "disabled",
  });
  await page.goto("/knowledge/wiki-concept-distribution");
  await expect(page.getByRole("button", { name: "All knowledge" })).toHaveCSS(
    "font-size",
    "14px",
  );
  await expect(
    page.locator(".compact-status-badge").filter({ hasText: "supported" }),
  ).toHaveCSS("font-size", "10px");
  await page.getByRole("link", { name: "Second Brain", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Second Brain" }),
  ).toBeVisible();
  await expect(page.getByLabel("Page type")).toHaveCSS(
    "background-image",
    /svg/,
  );
  await expect(page.getByLabel("Page type")).toHaveCSS("font-size", "12px");
  await expect(page.getByLabel("Page type").locator("..")).toHaveCSS(
    "color",
    "rgb(23, 34, 31)",
  );
  await expect(page.getByLabel("Page type").locator("..")).toHaveCSS(
    "font-size",
    "12px",
  );
  await expect(page.getByLabel("Page type").locator("..")).toHaveCSS(
    "font-weight",
    "600",
  );
  await expect(
    page.getByText("Arrows retain the direction of each explicit link."),
  ).toHaveCSS("font-size", "12px");
  await expect(
    page
      .getByRole("heading", { name: "Legend" })
      .locator("..")
      .locator("span")
      .first(),
  ).toHaveCSS("font-size", "12px");
  const isolatedCheckbox = page.getByLabel("Show isolated pages");
  await expect(isolatedCheckbox).toHaveCSS(
    "background-color",
    "rgb(51, 209, 51)",
  );
  expect(
    await isolatedCheckbox.evaluate((element) =>
      getComputedStyle(element, "::before").getPropertyValue(
        "background-color",
      ),
    ),
  ).toBe("rgb(255, 255, 255)");
  await page.getByLabel("Page type").focus();
  await expect(page.getByLabel("Page type")).toHaveCSS("outline-style", "none");
  await expect(page.getByText("1 pages")).toBeVisible();
  const renderedLabelPixels = () =>
    page.locator("canvas.sigma-labels").evaluate((element) => {
      const canvas = element as HTMLCanvasElement;
      const context = canvas.getContext("2d");
      if (!context) return 0;
      const pixels = context.getImageData(
        0,
        0,
        canvas.width,
        canvas.height,
      ).data;
      let visible = 0;
      for (let index = 3; index < pixels.length; index += 4)
        if (pixels[index]) visible += 1;
      return visible;
    });
  await expect.poll(renderedLabelPixels).toBeGreaterThan(0);
  const countRows = await page.locator(".graph-counts").evaluate((element) => {
    const strong = element.querySelector("strong")?.getBoundingClientRect();
    const span = element.querySelector("span")?.getBoundingClientRect();
    return { strongTop: strong?.top ?? 0, spanTop: span?.top ?? 0 };
  });
  expect(countRows.spanTop).toBeGreaterThan(countRows.strongTop);
  await page.getByRole("button", { name: "Expand", exact: true }).click();
  await expect
    .poll(() =>
      page
        .locator(".brain-layout")
        .evaluate((element) => element.classList.contains("is-expanded")),
    )
    .toBe(true);
  await expect(page.locator("body")).toHaveClass(/graph-expanded-open/);
  await expect.poll(renderedLabelPixels).toBeGreaterThan(0);
  const expandedTabs = page.getByRole("tablist", {
    name: "Expanded graph view",
  });
  await expect(expandedTabs).toBeVisible();
  await expandedTabs.getByRole("tab", { name: "Local Graph" }).click();
  await expect(
    page.getByRole("heading", { name: "Choose a root page" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Find a page" }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Filters" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Legend" })).toBeVisible();
  await page.getByPlaceholder("Search titles…").fill("Distribution");
  await page
    .locator(".brain-find-control")
    .getByRole("button", { name: "Distribution", exact: true })
    .click();
  await expect(page).toHaveURL(/mode=local.*root=wiki-concept-distribution/);
  await expandedTabs.getByRole("tab", { name: "Global Graph" }).click();
  await expect(page).toHaveURL(/\/second-brain$/);
  await expect(
    page.getByRole("button", { name: "Minimize", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Fit", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Reset layout", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Refresh", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".brain-sidebar")).toHaveCSS("overflow-y", "auto");
  const expandedBounds = await page
    .locator(".brain-layout")
    .evaluate((element) => ({
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
      top: element.getBoundingClientRect().top,
      viewportHeight: window.innerHeight,
    }));
  expect(expandedBounds.top).toBe(0);
  expect(expandedBounds.clientHeight).toBe(expandedBounds.viewportHeight);
  expect(expandedBounds.scrollHeight).toBe(expandedBounds.clientHeight);
  await page.getByRole("button", { name: "Minimize", exact: true }).click();
  await expect
    .poll(() =>
      page
        .locator(".brain-layout")
        .evaluate((element) => element.classList.contains("is-expanded")),
    )
    .toBe(false);
  await expect.poll(renderedLabelPixels).toBeGreaterThan(0);
  await page.getByRole("tab", { name: "Local Graph" }).click();
  await page.getByPlaceholder("Find a page…").fill("Distribution");
  await page
    .locator(".compact-results")
    .getByRole("button", { name: /Distribution/ })
    .click();
  await expect(page.locator(".selected-root")).toContainText("Distribution");
  await page.getByRole("button", { name: "2 hops" }).click();
  await expect(page).toHaveURL(/depth=2/);
  await page.getByRole("tab", { name: "Global Graph" }).click();
  await page.getByLabel("Show isolated pages").uncheck();
  await expect(
    page.getByText("No pages match the current filters."),
  ).toBeVisible();
  await page.getByLabel("Show isolated pages").check();
  await page.getByPlaceholder("Search titles…").fill("Distribution");
  await page.getByTitle("Open Wiki Detail").click();
  await expect(
    page.locator(".page-header").getByRole("heading", { name: "Distribution" }),
  ).toBeVisible();
  await page
    .locator(".portable-reader-actions")
    .getByRole("link", { name: "Second Brain", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Second Brain" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "AI Chat", exact: true }).click();
  await expect(page.getByRole("heading", { name: "AI Chat" })).toBeVisible();
  await expect(page.getByText("2 messages", { exact: true })).toHaveCSS(
    "font-size",
    "11px",
  );
  await expect(
    page.getByRole("textbox", { name: "Message", exact: true }),
  ).toHaveCSS("font-size", "15px");
  await expect(
    page.getByText("What would you like to understand?"),
  ).toBeVisible();
  await expect(
    page.getByText(
      "I’ll search your connected knowledge and show where the answer comes from.",
    ),
  ).toHaveCSS("font-size", "14px");
  await page.screenshot({
    path: testInfo.outputPath("chat.png"),
    animations: "disabled",
  });
  await page.getByRole("button", { name: "Delete Research thread" }).click();
  await expect(
    page.getByRole("dialog", { name: "Delete conversation?" }),
  ).toBeVisible();
  await expect(
    page.getByText("Are you sure you want to confirm this action?"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: "Delete conversation?" }),
  ).toBeHidden();
  await page.getByRole("link", { name: "View all", exact: true }).click();
  await expect(page.getByText("1 conversations · 15 per page")).toHaveCSS(
    "font-size",
    "12px",
  );
  await page.getByRole("link", { name: "Analytics", exact: true }).click();
  await expect(
    page.getByText(
      "Metadata only. No prompts, source text, or hidden reasoning are recorded.",
    ),
  ).toHaveCSS("font-size", "12px");
  await expect(page.locator(".stat-card h2").first()).toHaveCSS(
    "font-size",
    "14px",
  );
  await expect(page.locator(".stat-card h2").first()).toHaveCSS(
    "font-weight",
    "700",
  );
  await expect(page.locator(".stat-card p").first()).toHaveCSS(
    "font-size",
    "13px",
  );
  await expect(
    page.locator(".analytics-card > div:first-child > p:last-child").first(),
  ).toHaveCSS("font-size", "14px");
  await page.screenshot({
    path: testInfo.outputPath("analytics.png"),
    animations: "disabled",
  });
  await page.getByRole("link", { name: "Audit logs", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Logs history" }),
  ).toBeVisible();
  await expect(page.getByText("16 logs · 15 per page")).toHaveCSS(
    "font-size",
    "12px",
  );
  await expect(page.locator("tbody td").first()).toHaveCSS("font-size", "12px");
  const activePage = page.locator(".pagination button.active");
  await expect(activePage).toHaveCSS("color", "rgb(255, 255, 255)");
  await expect(activePage).toHaveCSS("font-weight", "600");
  await page.getByLabel("Search event").fill("document.uploaded");
  await expect(page).toHaveURL(/event_type=document.uploaded/);
  await expect(page.getByText("1 logs · 15 per page")).toBeVisible();
  await page.getByRole("link", { name: "Datasets", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "distribution.csv", exact: true }),
  ).toBeVisible();
  await expect(
    page.locator("aside").getByText("distribution.csv", { exact: true }),
  ).toHaveCSS("font-size", "11px");
  await expect(
    page
      .getByRole("heading", { name: "Available datasets" })
      .locator("..")
      .locator("small")
      .first(),
  ).toHaveCSS("font-size", "11px");
  await expect(
    page.getByText(
      "Column names must match the source exactly. Computation uses allow-listed operations—no generated code or SQL.",
    ),
  ).toHaveCSS("font-size", "12px");
  await page.getByRole("button", { name: "Run analysis" }).click();
  await expect(page.getByText("Analysis provenance")).toBeVisible();
  await expect(page.locator(".chart-wrap")).toBeVisible();
  await page.locator(".chart-wrap").screenshot({
    path: testInfo.outputPath("simple-chart.png"),
    animations: "disabled",
  });
  await expect(page.locator("dt").first()).toHaveCSS("font-size", "10px");
  const immutableOriginalButton = page.getByRole("button", {
    name: "Open immutable original",
  });
  await expect(immutableOriginalButton).toHaveCSS("color", "rgb(51, 209, 51)");
  await expect(immutableOriginalButton).toHaveCSS("margin-top", "20px");
  await expect(immutableOriginalButton.locator("svg")).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("datasets.png"),
    animations: "disabled",
  });
});

test("renders the sign-in state", async ({ page }, testInfo) => {
  await page.route("http://localhost:8000/api/v1/auth/me", (route) =>
    route.fulfill({ status: 401, json: { detail: "Unauthorized" } }),
  );
  await page.goto("/");

  await expect(page.getByRole("img", { name: "Knemora" })).toBeVisible();
  await expect(page.getByLabel("Email")).toBeVisible();
  await expect(page.getByLabel("Password", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Email")).toHaveCSS("font-size", "14px");
  await expect(page.getByLabel("Password", { exact: true })).toHaveCSS(
    "font-size",
    "14px",
  );
  await expect(
    page.getByText("© 2026 Knemora - MIT-licensed application"),
  ).toBeVisible();
  await page.getByLabel("Email").focus();
  await expect(page.getByLabel("Email")).toHaveCSS(
    "border-color",
    "rgb(51, 209, 51)",
  );
  await expect(page.getByLabel("Email")).toHaveCSS(
    "box-shadow",
    "rgba(51, 209, 51, 0.09) 0px 0px 0px 3px",
  );
  await page.getByRole("button", { name: "Show password" }).click();
  await expect(page.getByLabel("Password", { exact: true })).toHaveAttribute(
    "type",
    "text",
  );
  await page.screenshot({ path: testInfo.outputPath("sign-in.png") });
});

test("preserves mobile and intermediate navigation", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Open navigation" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect
    .poll(async () =>
      Math.round((await page.locator(".sidebar").boundingBox())?.x ?? -999),
    )
    .toBe(0);
  await expect(
    page.getByRole("link", { name: "Overview", exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("mobile-navigation.png") });
  await page.getByRole("button", { name: "Close navigation" }).click();

  await page.setViewportSize({ width: 900, height: 700 });
  await page.goto("/second-brain");
  await expect(
    page.getByRole("button", { name: "Open navigation" }),
  ).toBeHidden();
  await expect(
    page.getByRole("heading", { name: "Second Brain" }),
  ).toBeVisible();
  await expect(page.locator(".brain-sidebar")).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("intermediate-graph.png"),
  });
});

test("keeps Wiki and Direct modes accessible and clear of the composer", async ({
  page,
}) => {
  const submittedBodies: Array<{ content: string; response_mode: string }> = [];
  let notifyStreamStarted: (() => void) | undefined;
  let releaseStream: (() => void) | undefined;
  const streamStarted = new Promise<void>((resolve) => {
    notifyStreamStarted = resolve;
  });
  const streamGate = new Promise<void>((resolve) => {
    releaseStream = resolve;
  });

  await page.route("http://localhost:8000/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/conversations" && request.method() === "POST")
      return route.fulfill({
        status: 201,
        json: {
          id: "conversation-mode",
          user_id: "user-1",
          title: "Untitled conversation",
          message_count: 0,
        },
      });
    if (
      path === "/api/v1/conversations/conversation-mode" &&
      request.method() === "GET"
    )
      return route.fulfill({
        json: {
          id: "conversation-mode",
          user_id: "user-1",
          title: "Mode test",
          message_count: 0,
        },
      });
    if (
      path === "/api/v1/conversations/conversation-mode/messages" &&
      request.method() === "GET"
    )
      return route.fulfill({ json: [] });
    if (
      path === "/api/v1/conversations/conversation-1" &&
      request.method() === "GET"
    )
      return route.fulfill({
        json: {
          id: "conversation-1",
          user_id: "user-1",
          title: "Research thread",
          message_count: 2,
        },
      });
    if (
      path === "/api/v1/conversations/conversation-1/messages" &&
      request.method() === "GET"
    )
      return route.fulfill({ json: [] });
    if (
      path === "/api/v1/conversations/conversation-mode/messages/stream" &&
      request.method() === "POST"
    ) {
      submittedBodies.push(
        request.postDataJSON() as { content: string; response_mode: string },
      );
      notifyStreamStarted?.();
      await streamGate;
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          'event: message.started\ndata: {"event_id":"mode"}\n\n' +
          'event: message.delta\ndata: {"event_id":"mode","delta":"Direct response."}\n\n' +
          'event: message.completed\ndata: {"event_id":"mode"}\n\n',
      });
    }
    return route.fallback();
  });

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/chat");
  const modeGroup = page.getByRole("group", { name: "Response mode" });
  const wiki = page.getByRole("radio", { name: "Wiki" });
  const direct = page.getByRole("radio", { name: "Direct" });
  const wikiOption = page.locator('label:has(input[value="wiki"]) span');
  const directOption = page.locator('label:has(input[value="direct"]) span');
  const responseDisclaimer = page.getByText(
    "AI responses may include mistakes.",
  );
  const wikiHelp = page.getByText("Wiki: answers grounded in your knowledge");
  const directHelp = page.getByText(
    "Direct: local AI without knowledge search",
  );
  const composer = page.locator("form.composer");
  const message = page.getByRole("textbox", { name: "Message" });
  await expect(wiki).toBeChecked();
  await expect(wikiHelp).toBeVisible();
  await expect(wikiHelp).toHaveCSS("font-size", "11px");
  await expect(wikiOption).toHaveCSS("background-color", "rgb(51, 209, 51)");
  await expect(wikiOption).toHaveCSS("font-size", "11px");
  await expect(directOption).toHaveCSS("font-size", "11px");
  await expect(responseDisclaimer).toHaveCSS("font-size", "11px");
  const composerBox = await composer.boundingBox();
  const disclaimerBox = await responseDisclaimer.boundingBox();
  expect(composerBox).not.toBeNull();
  expect(disclaimerBox).not.toBeNull();
  expect(disclaimerBox!.y).toBeGreaterThanOrEqual(
    composerBox!.y + composerBox!.height,
  );

  await wiki.focus();
  await wiki.press("ArrowRight");
  await expect(direct).toBeChecked();
  await expect(directHelp).toBeVisible();
  await expect(directHelp).toHaveCSS("font-size", "11px");
  await expect(directOption).toHaveCSS("background-color", "rgb(51, 209, 51)");

  await message.fill(
    Array.from(
      { length: 8 },
      (_, index) => `Long prompt line ${index + 1}`,
    ).join("\n"),
  );
  const expandedTextareaBox = await message.boundingBox();
  const modeBox = await modeGroup.boundingBox();
  expect(expandedTextareaBox).not.toBeNull();
  expect(modeBox).not.toBeNull();
  expect(modeBox!.y).toBeGreaterThanOrEqual(
    expandedTextareaBox!.y + expandedTextareaBox!.height,
  );

  await page.getByRole("button", { name: "Send message" }).click();
  await streamStarted;
  await expect(wiki).toBeDisabled();
  await expect(direct).toBeDisabled();
  await expect(page.getByText("Generating answer…")).toBeVisible();
  await expect(page.getByText("Searching company knowledge…")).toHaveCount(0);
  expect(submittedBodies).toHaveLength(1);
  expect(submittedBodies[0].response_mode).toBe("direct");

  await page.setViewportSize({ width: 375, height: 812 });
  const mobileTextareaBox = await message.boundingBox();
  const mobileModeBox = await modeGroup.boundingBox();
  expect(mobileTextareaBox).not.toBeNull();
  expect(mobileModeBox).not.toBeNull();
  expect(mobileModeBox!.y).toBeGreaterThanOrEqual(
    mobileTextareaBox!.y + mobileTextareaBox!.height,
  );

  releaseStream?.();
  await expect(page.getByText("Direct response.")).toBeVisible();
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.getByRole("button", { name: "New conversation" }).click();
  await expect(wiki).toBeChecked();

  await directOption.click();
  await page.getByRole("link", { name: /Research thread/ }).click();
  await expect(wiki).toBeChecked();

  await directOption.click();
  await page.reload();
  await expect(wiki).toBeChecked();
});
