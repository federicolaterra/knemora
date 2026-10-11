<script setup lang="ts">
import {
  ExternalLink,
  FileSearch,
  RefreshCw,
  Search,
  Trash2,
  X,
} from "@lucide/vue";
import { computed, onBeforeUnmount, ref, watch } from "vue";

import { api, openOriginalSource } from "../api/client";
import PaginationControls from "../components/PaginationControls.vue";
import PageHeader from "../components/PageHeader.vue";
import StatusBadge from "../components/StatusBadge.vue";
import UploadZone from "../components/UploadZone.vue";
import { useAuthStore } from "../stores/auth";
import { useSystemStore } from "../stores/system";
import { useWorkspaceStore } from "../stores/workspace";
import type { DocumentRecord, SourceDeletionOperation } from "../types";

const workspace = useWorkspaceStore();
const auth = useAuthStore();
const system = useSystemStore();
const query = ref("");
const filter = ref("all");
const busy = ref("");
const error = ref("");
const documents = ref<DocumentRecord[]>([]);
const page = ref(1);
const total = ref(0);
const totalPages = ref(1);
const loading = ref(true);
const deletions = ref<SourceDeletionOperation[]>([]);
const deletionDismissalKey = "knemora.documents.dismissed-deletions";
const dismissedDeletionIds = ref(loadDismissedDeletionIds());
let searchTimer: ReturnType<typeof setTimeout> | undefined;
let deletionTimer: ReturnType<typeof setTimeout> | undefined;

const visibleDeletions = computed(() =>
  deletions.value
    .filter(
      (operation) =>
        operation.status !== "COMPLETED" ||
        !dismissedDeletionIds.value.has(operation.id),
    )
    .slice(0, 5),
);

function loadDismissedDeletionIds(): Set<string> {
  try {
    const stored = JSON.parse(
      window.localStorage.getItem(deletionDismissalKey) ?? "[]",
    ) as unknown;
    return new Set(
      Array.isArray(stored)
        ? stored.filter((value): value is string => typeof value === "string")
        : [],
    );
  } catch {
    window.localStorage.removeItem(deletionDismissalKey);
    return new Set();
  }
}

function dismissDeletion(operationId: string) {
  dismissedDeletionIds.value = new Set([
    ...dismissedDeletionIds.value,
    operationId,
  ]);
  window.localStorage.setItem(
    deletionDismissalKey,
    JSON.stringify([...dismissedDeletionIds.value].slice(-100)),
  );
}

async function loadDeletions() {
  deletions.value = await api.listSourceDeletions();
  clearTimeout(deletionTimer);
  if (
    deletions.value.some((item) => ["PENDING", "RUNNING"].includes(item.status))
  ) {
    deletionTimer = setTimeout(() => void loadDeletions(), 1500);
  }
}

async function loadPage(targetPage = page.value) {
  loading.value = true;
  error.value = "";
  try {
    const result = await api.listDocumentPage(
      targetPage,
      10,
      query.value,
      filter.value,
    );
    documents.value = result.items;
    page.value = result.page;
    total.value = result.total;
    totalPages.value = result.total_pages;
    await loadDeletions();
  } catch (reason) {
    error.value =
      reason instanceof Error ? reason.message : "Unable to load documents.";
  } finally {
    loading.value = false;
  }
}

watch(
  [query, filter],
  () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => void loadPage(1), 250);
  },
  { immediate: true },
);
onBeforeUnmount(() => {
  clearTimeout(searchTimer);
  clearTimeout(deletionTimer);
});

async function refreshDocuments() {
  await workspace.refresh();
  await loadPage(1);
}

async function reprocess(document: (typeof workspace.documents)[number]) {
  busy.value = document.document_version_id;
  error.value = "";
  try {
    await api.reprocessIngestion(document.ingestion_job_id);
    await api.compileDocument(document.document_version_id);
    await workspace.refresh();
    await loadPage();
  } catch (reason) {
    error.value =
      reason instanceof Error ? reason.message : "Reprocessing failed.";
  } finally {
    busy.value = "";
  }
}

async function deleteSource(document: (typeof workspace.documents)[number]) {
  if (
    !window.confirm(
      `Delete ${document.original_filename} and every version? Stored source files will be removed and active Wiki, search, graph, and dataset knowledge will be updated. Historical backups and conversations are not changed.`,
    )
  )
    return;
  busy.value = document.document_version_id;
  try {
    await api.deleteDocument(document.document_id);
    await loadDeletions();
    await workspace.refresh();
    await loadPage(
      documents.value.length === 1 ? Math.max(1, page.value - 1) : page.value,
    );
  } catch (reason) {
    error.value =
      reason instanceof Error
        ? reason.message
        : "Deletion could not be started.";
  } finally {
    busy.value = "";
  }
}

async function retryDeletion(operation: SourceDeletionOperation) {
  error.value = "";
  try {
    await api.retrySourceDeletion(operation.id);
    await loadDeletions();
  } catch (reason) {
    error.value =
      reason instanceof Error ? reason.message : "Deletion retry failed.";
  }
}
</script>

<template>
  <section
    class="page-content [width:min(1380px,_100%)] [margin:0_auto] [padding:36px_clamp(22px,_3.5vw,_52px)_64px] mobile:[padding:27px_16px_45px]"
  >
    <PageHeader
      eyebrow="Source library"
      title="Documents"
      description="Upload immutable source material and follow it into your knowledge base."
    />
    <div
      v-if="system.demoActive"
      class="alert flex items-center justify-between [gap:16px] [margin:0_0_20px] [padding:12px_15px] rounded-action text-label [&_button]:[color:inherit] [&_button]:[background:transparent] [&_button]:border-0 [&_button]:font-bold [&_button]:underline"
      role="status"
    >
      Development demo sources are read-only. Start normal Knemora to upload,
      reprocess, or delete documents.
    </div>
    <div
      v-for="operation in visibleDeletions"
      :key="operation.id"
      class="alert flex items-center justify-between [gap:16px] [margin:0_0_12px] [padding:12px_15px] rounded-action text-label border border-line bg-white"
      role="status"
    >
      <span v-if="operation.status === 'COMPLETED'">
        Deleted {{ operation.display_filename }} and updated active knowledge.
      </span>
      <span v-else-if="operation.status === 'FAILED'">
        Deletion of {{ operation.display_filename }} failed at
        {{ operation.stage }}. The source remains excluded from active
        knowledge.
      </span>
      <span v-else>
        Deleting {{ operation.display_filename }} and updating knowledge…
      </span>
      <div class="flex items-center [gap:8px]">
        <button
          v-if="operation.status === 'FAILED' && auth.can('document.delete')"
          type="button"
          class="font-bold underline"
          @click="retryDeletion(operation)"
        >
          Retry
        </button>
        <button
          v-if="operation.status === 'COMPLETED'"
          type="button"
          class="inline-grid [width:28px] [height:28px] place-items-center [color:#64746e] [background:transparent] border-0 rounded-control hover:text-ink hover:bg-[#edf2ef]"
          :aria-label="`Dismiss deletion notice for ${operation.display_filename}`"
          title="Dismiss notice"
          @click="dismissDeletion(operation.id)"
        >
          <X :size="16" />
        </button>
      </div>
    </div>
    <UploadZone
      v-if="auth.can('document.upload') && !system.demoActive"
      @complete="refreshDocuments"
    />
    <div
      v-if="error"
      class="alert alert-danger flex items-center justify-between [gap:16px] [margin:0_0_20px] [padding:12px_15px] rounded-action text-label [&_button]:[color:inherit] [&_button]:[background:transparent] [&_button]:border-0 [&_button]:font-bold [&_button]:underline [color:#7b3525] [background:#fbece6] [border:1px_solid_#efc8bc]"
      role="alert"
    >
      {{ error }}
    </div>
    <section
      class="surface table-surface bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] [padding:22px]"
    >
      <div
        class="flex items-center justify-between [&_h2]:m-0 [&_h2]:font-sans [&_h2]:text-title [&_h2]:font-medium [gap:20px] [margin-bottom:14px] [&_p]:[margin:4px_0_0] [&_p]:text-muted [&_p]:text-label mobile:items-stretch mobile:flex-col"
      >
        <div>
          <h2>Source library</h2>
          <p>{{ total }} source versions · 10 per page</p>
        </div>
        <div
          class="flex [gap:9px] mobile:items-stretch mobile:flex-col mobile:[&_.search-field_input]:w-full"
        >
          <label
            class="search-field focus-within:border-brand focus-within:shadow-[0_0_0_3px_rgba(51,209,51,0.09)] flex [gap:8px] items-center [min-height:36px] [padding:0_10px] [background:#f8f9f7] border border-line rounded-control [&_input]:[width:180px] [&_input]:p-0 [&_input]:[background:transparent] [&_input]:border-0 [&_input]:outline-none [&_input]:text-label [&_input:focus]:!shadow-none"
            ><Search :size="16" /><span
              class="sr-only absolute [width:1px] [height:1px] p-0 [margin:-1px] overflow-hidden [clip:rect(0,_0,_0,_0)] whitespace-nowrap border-0"
              >Search documents</span
            ><input v-model="query" placeholder="Search files…" /></label
          ><select
            class="h-9 rounded-[7px] border border-line bg-white py-0 pl-[10px] pr-[30px] text-label outline-none focus:border-brand focus:shadow-[0_0_0_3px_rgba(51,209,51,0.09)]"
            v-model="filter"
            aria-label="Filter documents"
          >
            <option value="all">All sources</option>
            <option value="dataset">Datasets</option>
            <option value="attention">Needs attention</option>
          </select>
        </div>
      </div>
      <div
        v-if="loading && !documents.length"
        class="animate-pulse"
        role="status"
      >
        <span class="sr-only">Loading source library…</span>
        <div
          v-for="row in 4"
          :key="row"
          class="grid grid-cols-[minmax(180px,_2fr)_1fr_0.7fr_1fr_42px] items-center gap-5 border-b border-[#edf0ee] px-[10px] py-[16px] mobile:grid-cols-[1fr_90px]"
        >
          <span class="h-3 rounded bg-[#e8ece9]"></span>
          <span class="h-5 rounded-full bg-[#edf1ee]"></span>
          <span class="h-3 rounded bg-[#edf1ee] mobile:hidden"></span>
          <span class="h-3 rounded bg-[#edf1ee] mobile:hidden"></span>
          <span class="h-7 rounded-control bg-[#edf1ee] mobile:hidden"></span>
        </div>
      </div>
      <div
        v-else-if="!documents.length"
        class="empty-state grid justify-items-center [min-height:280px] place-content-center [padding:35px] [color:#7c8b86] text-center [&_h3]:[margin:12px_0_5px] [&_h3]:text-ink [&_h3]:font-sans [&_h3]:text-title-lg [&_h3]:font-medium [&_p]:[max-width:430px] [&_p]:[margin:0_0_18px] [&_p]:text-body [&_p]:[line-height:1.55]"
      >
        <FileSearch :size="34" />
        <h3>No matching documents</h3>
        <p>Try a different filter or upload a source above.</p>
      </div>
      <div
        v-else
        class="responsive-table [&_table]:w-full [&_table]:border-collapse [&_table]:text-left [&_table]:text-label [&_th]:border-y [&_th]:border-[#e4e8e5] [&_th]:bg-[#f6f8f6] [&_th]:px-[10px] [&_th]:py-[11px] [&_th]:text-[9px] [&_th]:uppercase [&_th]:tracking-[0.08em] [&_th]:text-[#74817d] [&_td]:border-b [&_td]:border-[#edf0ee] [&_td]:px-[10px] [&_td]:py-[13px] [&_td]:align-middle [&_td]:text-label [&_td_code]:text-label [&_td_strong]:block [&_td_strong]:text-label [&_td_small]:block [&_td_small]:mt-1 [&_td_small]:text-label [&_td_small]:text-muted overflow-x-auto"
      >
        <table>
          <thead>
            <tr>
              <th>Source</th>
              <th>Status</th>
              <th>Size</th>
              <th>Added</th>
              <th>
                <span
                  class="sr-only absolute [width:1px] [height:1px] p-0 [margin:-1px] overflow-hidden [clip:rect(0,_0,_0,_0)] whitespace-nowrap border-0"
                  >Actions</span
                >
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="document in documents"
              :key="document.document_version_id"
            >
              <td>
                <strong>{{ document.original_filename }}</strong
                ><small
                  >v{{ document.version_number }} ·
                  {{ document.content_type }}</small
                >
              </td>
              <td>
                <StatusBadge
                  class="compact-status-badge !text-caption"
                  :status="
                    document.compilation_status ?? document.ingestion_status
                  "
                /><small v-if="document.compilation_report"
                  >{{
                    [
                      ...document.compilation_report.pages_created,
                      ...document.compilation_report.pages_updated,
                    ].length
                  }}
                  Wiki pages</small
                ><small
                  v-if="document.ingestion_error || document.compilation_error"
                  class="text-danger !text-danger"
                  >{{
                    document.ingestion_error ?? document.compilation_error
                  }}</small
                >
              </td>
              <td>{{ (document.byte_size / 1024).toFixed(1) }} KB</td>
              <td>{{ new Date(document.created_at).toLocaleDateString() }}</td>
              <td
                class="whitespace-nowrap [&_button]:inline-grid [&_button]:place-items-center [&_button]:[width:31px] [&_button]:[height:31px] [&_button]:[color:#546861] [&_button]:[background:transparent] [&_button]:border-0 [&_button]:[border-radius:6px] [&_button]:focus-visible:outline [&_button]:focus-visible:outline-2 [&_button]:focus-visible:outline-brand"
              >
                <button
                  type="button"
                  class="hover:text-[#3f4c48] hover:bg-[#edf2ef]"
                  title="Open immutable original"
                  @click="openOriginalSource(document.original_url)"
                >
                  <ExternalLink :size="17" /></button
                ><button
                  v-if="auth.can('document.reprocess') && !system.demoActive"
                  type="button"
                  class="hover:text-[#3f4c48] hover:bg-[#edf2ef]"
                  title="Reprocess source"
                  :disabled="busy === document.document_version_id"
                  @click="reprocess(document)"
                >
                  <RefreshCw
                    :class="{
                      'animate-spin-fast':
                        busy === document.document_version_id,
                    }"
                    :size="17"
                  />
                </button>
                <button
                  v-if="auth.can('document.delete') && !system.demoActive"
                  type="button"
                  class="hover:text-danger hover:bg-[#fbece6] focus-visible:!outline-danger"
                  title="Delete source and update knowledge"
                  :disabled="busy === document.document_version_id"
                  @click="deleteSource(document)"
                >
                  <Trash2 :size="17" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <PaginationControls
        :page="page"
        :total="total"
        :total-pages="totalPages"
        :loading="loading"
        :page-limit="10"
        @change="loadPage"
      />
    </section>
  </section>
</template>
