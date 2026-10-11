<script setup lang="ts">
import { AlertTriangle, Check, Clock3, RotateCw, Search, X } from "@lucide/vue";
import { onBeforeUnmount, ref, watch } from "vue";

import { api } from "../api/client";
import PageHeader from "../components/PageHeader.vue";
import PaginationControls from "../components/PaginationControls.vue";
import StatusBadge from "../components/StatusBadge.vue";
import { useSystemStore } from "../stores/system";
import type { DocumentRecord } from "../types";

const system = useSystemStore();
const documents = ref<DocumentRecord[]>([]);
const query = ref("");
const status = ref("all");
const fileType = ref("all");
const page = ref(1);
const total = ref(0);
const totalPages = ref(0);
const loading = ref(true);
const error = ref("");
let searchTimer: ReturnType<typeof setTimeout> | undefined;
let requestSequence = 0;
const stages = [
  "VALIDATING",
  "STORING",
  "PARSING",
  "NORMALIZING",
  "ANALYZING",
  "COMPILING_WIKI",
  "LINKING",
  "INDEXING",
  "VALIDATING_WIKI",
  "COMPLETED",
];

function stageIndex(document: DocumentRecord) {
  if (document.compilation_status === "COMPLETED") return stages.length - 1;
  if (document.compilation_status) {
    const compilation: Record<string, number> = {
      QUEUED: 4,
      ANALYZING: 4,
      VALIDATING: 5,
      APPLYING: 6,
      INDEXING: 7,
      LINTING: 8,
    };
    return compilation[document.compilation_status] ?? 4;
  }
  const ingestion: Record<string, number> = {
    UPLOADED: 0,
    VALIDATING: 0,
    STORING: 1,
    PARSING: 2,
    NORMALIZING: 3,
    READY_FOR_COMPILATION: 3,
  };
  return ingestion[document.ingestion_status] ?? 0;
}

async function loadPage(targetPage = page.value) {
  const request = ++requestSequence;
  loading.value = true;
  error.value = "";
  try {
    const result = await api.listDocumentPage(
      targetPage,
      10,
      query.value.trim(),
      "all",
      status.value,
      fileType.value,
    );
    if (request !== requestSequence) return;
    if (result.total && targetPage > result.total_pages) {
      await loadPage(result.total_pages);
      return;
    }
    documents.value = result.items;
    page.value = result.page;
    total.value = result.total;
    totalPages.value = result.total_pages;
  } catch (reason) {
    if (request !== requestSequence) return;
    error.value =
      reason instanceof Error
        ? reason.message
        : "Unable to load ingestion activity.";
  } finally {
    if (request === requestSequence) loading.value = false;
  }
}

watch(
  [query, status, fileType],
  () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => void loadPage(1), 300);
  },
  { immediate: true },
);
onBeforeUnmount(() => clearTimeout(searchTimer));

function clearFilters() {
  query.value = "";
  status.value = "all";
  fileType.value = "all";
}

async function retry(document: DocumentRecord) {
  try {
    if (document.ingestion_status === "FAILED")
      await api.retryIngestion(document.ingestion_job_id);
    await api.compileDocument(document.document_version_id);
    await loadPage();
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "Retry failed.";
  }
}
</script>

<template>
  <section
    class="page-content [width:min(1380px,_100%)] [margin:0_auto] [padding:36px_clamp(22px,_3.5vw,_52px)_64px] mobile:[padding:27px_16px_45px]"
  >
    <PageHeader
      eyebrow="Processing"
      title="Ingestion"
      description="A transparent view of every source as it becomes durable, linked knowledge."
    >
      <template #actions
        ><button
          class="button button-secondary inline-flex [gap:8px] items-center justify-center [min-height:38px] [padding:0_15px] [border:1px_solid_transparent] rounded-action text-label font-bold no-underline [transition:0.16s_ease] [color:#33433e] bg-surface [border-color:#d5ddd8] hover:[border-color:#a9bbb4]"
          type="button"
          :disabled="loading"
          @click="loadPage()"
        >
          <RotateCw :size="16" /> Refresh
        </button></template
      >
    </PageHeader>
    <div
      v-if="system.demoActive"
      class="alert flex items-center justify-between [gap:16px] [margin:0_0_20px] [padding:12px_15px] rounded-action text-label [&_button]:[color:inherit] [&_button]:[background:transparent] [&_button]:border-0 [&_button]:font-bold [&_button]:underline"
      role="status"
    >
      Development demo ingestion is read-only.
    </div>
    <section
      class="surface mb-4 flex items-center justify-between gap-5 rounded-panel border border-line bg-surface p-[22px] [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] mobile:items-stretch mobile:flex-col"
    >
      <div>
        <h2 class="m-0 font-sans text-title font-medium">Ingestion history</h2>
        <p class="mb-0 mt-1 text-label text-muted">
          {{ total }} source versions · 10 per page
        </p>
      </div>
      <div
        class="flex flex-wrap items-center justify-end gap-[9px] mobile:items-stretch mobile:flex-col mobile:[&_.search-field_input]:w-full"
      >
        <label
          class="search-field flex min-h-9 items-center gap-2 rounded-control border border-line bg-[#f8f9f7] px-[10px] focus-within:border-brand focus-within:shadow-[0_0_0_3px_rgba(51,209,51,0.09)] [&_input]:w-[180px] [&_input]:text-label [&_input:focus]:!shadow-none"
        >
          <Search :size="16" /><span class="sr-only">Search files</span
          ><input
            v-model="query"
            class="border-0 bg-transparent p-0 text-control outline-none"
            placeholder="Search files…"
          />
        </label>
        <select
          v-model="status"
          aria-label="Filter ingestion status"
          class="h-9 rounded-control border border-line bg-white px-3 text-label"
        >
          <option value="all">All statuses</option>
          <option value="processing">Processing</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
        </select>
        <select
          v-model="fileType"
          aria-label="Filter ingestion file type"
          class="h-9 rounded-control border border-line bg-white px-3 text-label"
        >
          <option value="all">All file types</option>
          <option value="pdf">PDF</option>
          <option value="txt">TXT</option>
          <option value="md">Markdown</option>
          <option value="docx">DOCX</option>
          <option value="csv">CSV</option>
          <option value="xlsx">XLSX</option>
        </select>
        <button
          v-if="query.trim() || status !== 'all' || fileType !== 'all'"
          type="button"
          class="inline-flex h-9 items-center gap-2 rounded-control border border-line px-3 text-control font-bold hover:border-danger hover:bg-[#fbece6] hover:text-danger"
          @click="clearFilters"
        >
          <X :size="15" /> Clear filters
        </button>
      </div>
    </section>
    <div
      v-if="error"
      class="alert alert-danger mb-4 rounded-action border border-[#efc8bc] bg-[#fbece6] p-3 text-label text-danger"
      role="alert"
    >
      {{ error }}
    </div>
    <div
      v-if="loading && !documents.length"
      class="grid animate-pulse gap-[14px]"
      role="status"
    >
      <span class="sr-only">Loading ingestion history…</span>
      <article
        v-for="card in 3"
        :key="card"
        class="surface rounded-panel border border-line bg-surface p-[22px] [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)]"
      >
        <div class="flex items-center gap-3">
          <span class="h-[35px] w-[35px] rounded-control bg-[#e8ece9]"></span>
          <div class="grid flex-1 gap-2">
            <span class="h-3 w-2/5 rounded bg-[#e8ece9]"></span>
            <span class="h-2 w-1/4 rounded bg-[#edf1ee]"></span>
          </div>
          <span class="h-5 w-20 rounded-full bg-[#edf1ee]"></span>
        </div>
        <div class="mt-6 grid grid-cols-10 gap-2">
          <span
            v-for="stage in 10"
            :key="stage"
            class="h-2 rounded bg-[#edf1ee]"
          ></span>
        </div>
      </article>
    </div>
    <div
      v-else-if="!documents.length"
      class="surface empty-state bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] grid justify-items-center [min-height:280px] place-content-center [padding:35px] [color:#7c8b86] text-center [&_h3]:[margin:12px_0_5px] [&_h3]:text-ink [&_h3]:font-sans [&_h3]:text-title-lg [&_h3]:font-medium [&_p]:[max-width:430px] [&_p]:[margin:0_0_18px] [&_p]:text-body [&_p]:[line-height:1.55]"
    >
      <span
        class="grid h-[54px] w-[54px] place-items-center rounded-[15px] bg-brand-pale text-brand"
        ><Clock3 :size="26"
      /></span>
      <h3>No ingestion activity yet</h3>
      <p>Upload your first source from Documents.</p>
      <RouterLink
        v-if="!system.demoActive"
        class="button button-primary inline-flex [gap:8px] items-center justify-center [min-height:38px] [padding:0_15px] [border:1px_solid_transparent] rounded-action text-label font-bold no-underline [transition:0.16s_ease] text-white bg-brand [box-shadow:0_2px_7px_rgb(51_209_51_/_18%)] hover:text-white hover:bg-brand hover:[opacity:0.82] hover:[transform:translateY(-1px)]"
        to="/documents"
        >Add a source</RouterLink
      >
    </div>
    <div v-else class="grid [gap:14px]">
      <article
        v-for="document in documents"
        :key="document.document_version_id"
        class="surface bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] [padding:22px]"
      >
        <div
          class="flex items-center justify-between [&>div]:flex [&>div]:items-center [&>div]:justify-between [gap:11px] [&>div]:[gap:11px] [&_h2]:m-0 [&_h2]:text-label [&_h2]:font-semibold [&_p]:[margin:4px_0_0] [&_p]:text-muted [&_p]:text-label phone:items-start phone:flex-col"
        >
          <div>
            <span
              class="file-symbol inline-grid place-items-center [width:35px] [height:35px] flex-none [color:#49635a] [background:#eef2ef] rounded-control text-caption font-semibold"
              >{{
                document.original_filename.split(".").pop()?.toUpperCase()
              }}</span
            >
            <div class="source-file-copy">
              <h2>{{ document.original_filename }}</h2>
              <p>
                Attempt
                {{
                  document.compilation_attempt_count ??
                  document.ingestion_attempt_count
                }}
                ·
                {{ new Date(document.created_at).toLocaleString() }}
              </p>
            </div>
          </div>
          <StatusBadge
            class="compact-status-badge !text-caption"
            :status="document.compilation_status ?? document.ingestion_status"
          />
        </div>
        <ol
          class="stage-rail my-0 mb-5 mt-[27px] grid list-none grid-cols-10 p-0 [&_.complete>span]:border-brand [&_.complete>span]:bg-brand [&_.complete>span]:text-white [&_.complete]:text-brand [&_.current>span]:border-[#d8a843] [&_.current>span]:bg-[#fff4d5] [&_.current>span]:text-[#7a5c1e] [&_.current>span]:shadow-[0_0_0_4px_#fbf3df] [&_.current]:font-bold [&_.current]:text-[#5f4c25] [&_.failed>span]:!border-[#d46a52] [&_.failed>span]:!bg-[#fbece6] [&_.failed>span]:!text-danger [&_.failed]:!text-danger [&_li>span]:z-[1] [&_li>span]:grid [&_li>span]:size-[21px] [&_li>span]:place-items-center [&_li>span]:rounded-full [&_li>span]:border-2 [&_li>span]:border-[#d9dfdb] [&_li>span]:bg-[#eef1ef] [&_li>span]:text-fine [&_li]:relative [&_li]:grid [&_li]:justify-items-center [&_li]:gap-1.5 [&_li]:text-center [&_li]:text-[#9aa49f] [&_small]:text-caption [&_small]:tracking-[0.03em] tablet:grid-cols-5 tablet:gap-y-[18px] phone:grid-cols-2"
          aria-label="Ingestion progress"
        >
          <li
            v-for="(stage, index) in stages"
            :key="stage"
            :class="{
              complete: index < stageIndex(document),
              current: index === stageIndex(document),
              failed:
                (document.ingestion_error || document.compilation_error) &&
                index === stageIndex(document),
            }"
          >
            <span
              ><Check
                v-if="index < stageIndex(document)"
                :size="12"
              /><AlertTriangle
                v-else-if="
                  (document.ingestion_error || document.compilation_error) &&
                  index === stageIndex(document)
                "
                :size="12"
              />{{ index >= stageIndex(document) ? index + 1 : "" }}</span
            ><small>{{ stage.replaceAll("_", " ") }}</small>
          </li>
        </ol>
        <div
          v-if="document.ingestion_error || document.compilation_error"
          class="flex [gap:12px] items-center [padding:12px] [color:#7b3525] [background:#fbece6] rounded-control [&>div]:flex-1 [&_strong]:block [&_strong]:m-0 [&_strong]:text-caption [&_p]:block [&_p]:m-0 [&_p]:text-caption [&_p]:[margin-top:3px]"
        >
          <AlertTriangle :size="17" />
          <div>
            <strong>Processing needs attention</strong>
            <p>{{ document.ingestion_error ?? document.compilation_error }}</p>
          </div>
          <button
            v-if="!system.demoActive"
            class="button button-secondary inline-flex [gap:8px] items-center justify-center [min-height:38px] [padding:0_15px] [border:1px_solid_transparent] rounded-action text-label font-bold no-underline [transition:0.16s_ease] [color:#33433e] bg-surface [border-color:#d5ddd8] hover:[border-color:#a9bbb4]"
            type="button"
            @click="retry(document)"
          >
            Retry
          </button>
        </div>
        <div
          v-if="document.compilation_report"
          class="flex flex-wrap [gap:20px] items-center [padding-top:13px] [border-top:1px_solid_#edf0ee] [&_p]:m-0 [&_p]:text-muted [&_p]:text-label [&_strong]:text-ink phone:items-start phone:flex-col"
        >
          <p>
            <strong>{{
              document.compilation_report.pages_created.length
            }}</strong>
            pages created
          </p>
          <p>
            <strong>{{
              document.compilation_report.pages_updated.length
            }}</strong>
            pages updated
          </p>
          <p>
            <strong
              >{{
                Math.round(
                  document.compilation_report.provenance_coverage * 100,
                )
              }}%</strong
            >
            provenance coverage
          </p>
          <div
            v-if="
              document.compilation_report.pages_created.length ||
              document.compilation_report.pages_updated.length
            "
            class="flex flex-1 flex-wrap [gap:6px] justify-end [&_a]:[padding:5px_8px] [&_a]:text-brand [&_a]:bg-brand-pale [&_a]:[border-radius:6px] [&_a]:text-control [&_a]:no-underline phone:justify-start"
          >
            <RouterLink
              v-for="page in [
                ...document.compilation_report.pages_created,
                ...document.compilation_report.pages_updated,
              ]"
              :key="page.id"
              :to="`/knowledge/${page.id}`"
              >{{ page.title }}</RouterLink
            >
          </div>
        </div>
      </article>
      <PaginationControls
        :page="page"
        :page-limit="10"
        :total="total"
        :total-pages="totalPages"
        :loading="loading"
        @change="loadPage"
      />
    </div>
  </section>
</template>
