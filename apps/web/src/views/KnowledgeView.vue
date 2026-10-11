<script setup lang="ts">
import {
  ArrowLeft,
  BookOpen,
  ExternalLink,
  FileLock2,
  Link2,
  Network,
  Search,
} from "@lucide/vue";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api, openOriginalSource } from "../api/client";
import PageHeader from "../components/PageHeader.vue";
import PaginationControls from "../components/PaginationControls.vue";
import StatusBadge from "../components/StatusBadge.vue";
import type { PageSummary, WikiPage } from "../types";

const route = useRoute();
const router = useRouter();
const query = ref("");
const type = ref("all");
const indexPages = ref<PageSummary[]>([]);
const indexPage = ref(1);
const indexTotal = ref(0);
const indexTotalPages = ref(0);
const indexLoading = ref(false);
const indexError = ref("");
const INDEX_PAGE_LIMIT = 8;
const selected = ref<WikiPage | null>(null);
const backlinks = ref<PageSummary[]>([]);
const related = ref<Array<PageSummary & { relationship?: string }>>([]);
const loading = ref(false);
const connectionsLoading = ref(false);
const error = ref("");
const connectionsError = ref("");
let openRequest = 0;
let filterTimer: ReturnType<typeof setTimeout> | undefined;

const originalSources = computed(() => {
  const unique = new Map<string, WikiPage["provenance"][number]>();
  for (const source of selected.value?.provenance ?? [])
    unique.set(source.document_version_id, source);
  return [...unique.values()];
});

async function loadIndex() {
  indexLoading.value = true;
  indexError.value = "";
  try {
    const result = await api.listWikiPageIndex(
      indexPage.value,
      INDEX_PAGE_LIMIT,
      query.value,
      type.value,
    );
    indexPages.value = result.items;
    indexTotal.value = result.total;
    indexTotalPages.value = result.total_pages;
  } catch (reason) {
    indexError.value =
      reason instanceof Error
        ? reason.message
        : "Unable to load the Wiki index.";
  } finally {
    indexLoading.value = false;
  }
}

function changeIndexPage(page: number) {
  indexPage.value = page;
  void loadIndex();
}

watch([query, type], () => {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(() => {
    indexPage.value = 1;
    void loadIndex();
  }, 250);
});
onMounted(loadIndex);
onBeforeUnmount(() => clearTimeout(filterTimer));

async function openPage(identifier: string) {
  const request = ++openRequest;
  loading.value = true;
  connectionsLoading.value = true;
  error.value = "";
  connectionsError.value = "";
  selected.value = null;
  backlinks.value = [];
  related.value = [];
  const connections = Promise.allSettled([
    api.getBacklinks(identifier),
    api.getRelated(identifier),
  ]);
  try {
    const page = await api.getWikiPage(identifier);
    if (request !== openRequest) return;
    selected.value = page;
  } catch (reason) {
    if (request !== openRequest) return;
    error.value =
      reason instanceof Error ? reason.message : "Unable to read this page.";
  } finally {
    if (request === openRequest) loading.value = false;
  }

  const [pageBacklinks, pageRelated] = await connections;
  if (request !== openRequest) return;
  if (pageBacklinks.status === "fulfilled") {
    backlinks.value = pageBacklinks.value;
  }
  if (pageRelated.status === "fulfilled") {
    related.value = pageRelated.value;
  }
  if (
    pageBacklinks.status === "rejected" ||
    pageRelated.status === "rejected"
  ) {
    connectionsError.value =
      "The page is open, but some connected pages could not be loaded.";
  }
  connectionsLoading.value = false;
}

function openSource(ref: WikiPage["provenance"][number]) {
  return openOriginalSource(
    `/api/v1/document-versions/${ref.document_version_id}/original`,
  );
}

watch(
  () => route.params.id,
  (id) => {
    if (typeof id === "string" && id) void openPage(id);
    else {
      openRequest += 1;
      selected.value = null;
      loading.value = false;
      connectionsLoading.value = false;
      error.value = "";
      connectionsError.value = "";
    }
  },
  { immediate: true },
);
</script>

<template>
  <section
    class="page-content [width:min(1380px,_100%)] [margin:0_auto] [padding:36px_clamp(22px,_3.5vw,_52px)_64px] mobile:[padding:27px_16px_45px]"
  >
    <PageHeader
      eyebrow="Organizational memory"
      title="Knowledge"
      description="Browse the auditable Wiki compiled from your approved sources."
    />
    <div
      class="grid [grid-template-columns:minmax(270px,_0.8fr)_minmax(0,_2fr)] [gap:14px] [min-height:650px] mobile:[grid-template-columns:1fr]"
    >
      <aside
        class="surface bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] self-start [padding-bottom:20px] overflow-hidden mobile:[&.detail-open]:hidden"
        :class="{ 'detail-open': selected }"
      >
        <div
          class="grid [gap:8px] [padding:14px] border-b border-line [&_.search-field_input]:w-full"
        >
          <label
            class="search-field focus-within:border-brand focus-within:shadow-[0_0_0_3px_rgba(51,209,51,0.09)] flex [gap:8px] items-center [min-height:36px] [padding:0_10px] [background:#f8f9f7] border border-line rounded-control [&_input]:[width:180px] [&_input]:p-0 [&_input]:[background:transparent] [&_input]:border-0 [&_input]:outline-none [&_input]:text-label [&_input:focus]:!shadow-none"
            ><Search :size="16" /><span
              class="sr-only absolute [width:1px] [height:1px] p-0 [margin:-1px] overflow-hidden [clip:rect(0,_0,_0,_0)] whitespace-nowrap border-0"
              >Search Wiki</span
            ><input
              v-model="query"
              placeholder="Search titles, aliases, topics…" /></label
          ><select
            class="h-9 rounded-[7px] border border-line bg-white py-0 pl-[10px] pr-[30px] text-label outline-none focus:border-brand focus:shadow-[0_0_0_3px_rgba(51,209,51,0.09)]"
            v-model="type"
            aria-label="Filter page type"
          >
            <option value="all">All page types</option>
            <option value="entity">Entities</option>
            <option value="concept">Concepts</option>
            <option value="topic">Topics</option>
            <option value="synthesis">Syntheses</option>
            <option value="dataset">Datasets</option>
          </select>
        </div>
        <div
          v-if="indexLoading"
          class="loading-block [padding:40px] text-muted text-center"
        >
          Loading Wiki index…
        </div>
        <div
          v-else-if="indexError"
          class="alert alert-danger flex items-center justify-between [gap:16px] [margin:0_0_20px] [padding:12px_15px] rounded-action text-label [&_button]:[color:inherit] [&_button]:[background:transparent] [&_button]:border-0 [&_button]:font-bold [&_button]:underline [color:#7b3525] [background:#fbece6] [border:1px_solid_#efc8bc]"
        >
          {{ indexError }}
        </div>
        <div
          v-else-if="!indexPages.length"
          class="empty-compact flex [gap:12px] items-center [padding:25px_14px] text-muted text-label"
        >
          <BookOpen :size="28" />
          <p>No Wiki pages match this view.</p>
        </div>
        <button
          v-for="page in indexPages"
          :key="page.id"
          type="button"
          class="grid w-full [padding:14px_16px] [background:transparent] border-0 [border-bottom:1px_solid_#edf0ee] text-left hover:[background:#f0f6f3] [&.active]:[background:#f0f6f3] [&.active]:[box-shadow:inset_3px_0_#33d133] [&_strong]:[margin-top:7px] [&_strong]:font-sans [&_strong]:text-body [&_strong]:font-medium [&_small]:[margin-top:4px] [&_small]:text-muted [&_small]:text-control"
          :class="{ active: selected?.id === page.id }"
          @click="router.push(`/knowledge/${page.id}`)"
        >
          <span
            class="kind-pill [width:max-content] [padding:3px_6px] [color:#4f6b62] [background:#edf2ef] [border-radius:4px] text-micro font-bold [letter-spacing:0.08em] uppercase"
            >{{ page.type }}</span
          ><strong>{{ page.title }}</strong
          ><small>{{ page.topics.join(" · ") || "No topics" }}</small>
        </button>
        <PaginationControls
          :page="indexPage"
          :page-limit="INDEX_PAGE_LIMIT"
          :total="indexTotal"
          :total-pages="indexTotalPages"
          :loading="indexLoading"
          @change="changeIndexPage"
        />
      </aside>
      <main
        class="surface wiki-reader bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] min-w-0 [padding:clamp(22px,_4vw,_48px)] mobile:[min-height:500px]"
      >
        <div
          v-if="loading"
          class="loading-block [padding:40px] text-muted text-center"
        >
          Opening Wiki page…
        </div>
        <div
          v-else-if="error"
          class="alert alert-danger flex items-center justify-between [gap:16px] [margin:0_0_20px] [padding:12px_15px] rounded-action text-label [&_button]:[color:inherit] [&_button]:[background:transparent] [&_button]:border-0 [&_button]:font-bold [&_button]:underline [color:#7b3525] [background:#fbece6] [border:1px_solid_#efc8bc]"
        >
          {{ error }}
        </div>
        <div
          v-else-if="!selected"
          class="grid justify-items-center [min-height:280px] place-content-center [padding:35px] [color:#7c8b86] text-center [&_h2]:[margin:12px_0_5px] [&_h2]:text-ink [&_h2]:font-sans [&_h2]:text-title-lg [&_h2]:font-medium [&_p]:[max-width:430px] [&_p]:[margin:0_0_18px] [&_p]:text-body [&_p]:[line-height:1.55]"
        >
          <span
            class="grid h-[54px] w-[54px] place-items-center rounded-[15px] bg-brand-pale text-brand"
            ><BookOpen :size="26"
          /></span>
          <h2>Select a Wiki page</h2>
          <p>
            Open a page to inspect its claims, connections, and original-source
            provenance.
          </p>
        </div>
        <article v-else>
          <div class="flex items-start [gap:12px] mobile:flex-col">
            <button
              class="inline-flex [gap:6px] items-center p-0 text-brand [background:none] border-0 text-body"
              type="button"
              @click="router.push('/knowledge')"
            >
              <ArrowLeft :size="16" /> All knowledge
            </button>
          </div>
          <header
            class="[padding:23px_0_28px] border-b border-line [&_h2]:[margin:12px_0_10px] [&_h2]:font-sans [&_h2]:[font-size:2rem] [&_h2]:font-medium [&_h2]:[letter-spacing:-0.035em] [&>p]:[max-width:750px] [&>p]:m-0 [&>p]:[color:#53655f] [&>p]:font-sans [&>p]:text-lead [&>p]:[line-height:1.6]"
          >
            <span
              class="kind-pill [width:max-content] [padding:3px_6px] [color:#4f6b62] [background:#edf2ef] [border-radius:4px] text-micro font-bold [letter-spacing:0.08em] uppercase"
              >{{ selected.type }}</span
            >
            <h2>{{ selected.title }}</h2>
            <span
              class="mb-2 inline-flex [width:max-content] [padding:3px_6px] [color:#6b5b23] [background:#fff7d6] [border-radius:4px] text-micro font-bold [letter-spacing:0.08em] uppercase"
              >AI-generated summary</span
            >
            <p>{{ selected.summary }}</p>
            <RouterLink
              class="inline-flex items-center [gap:6px] [color:#226d33] text-label font-extrabold no-underline [margin:30px_0_13px]"
              :to="{
                name: 'second-brain',
                query: { mode: 'local', root: selected.id, depth: '1' },
              }"
            >
              <Network :size="15" /> Open Local Graph
            </RouterLink>
            <div
              class="tag-row [&_a]:[padding:5px_8px] [&_a]:text-brand [&_a]:bg-brand-pale [&_a]:[border-radius:6px] [&_a]:text-control [&_a]:no-underline flex flex-wrap [gap:6px] [margin-top:15px] [&>span]:[padding:4px_7px] [&>span]:[color:#60716b] [&>span]:[background:#f2f4f2] [&>span]:[border-radius:5px] [&>span]:text-control"
            >
              <span v-for="alias in selected.aliases" :key="alias"
                >alias: {{ alias }}</span
              ><span v-for="topic in selected.topics" :key="topic"
                >#{{ topic }}</span
              >
            </div>
          </header>
          <section
            class="reader-section [padding:25px_0_4px] [&_h3]:[margin:0_0_14px] [&_h3]:text-control [&_h3]:[letter-spacing:0.08em] [&_h3]:uppercase"
          >
            <h3>AI-generated claims</h3>
            <div
              v-for="claim in selected.claims"
              :key="claim.id"
              class="[margin-bottom:10px] [padding:15px] [background:#fafbf9] [border:1px_solid_#e4e8e5] rounded-action [&>div]:flex [&>div]:[gap:8px] [&>div]:items-center [&>p]:[margin:11px_0] [&>p]:font-sans [&>p]:text-copy [&>p]:[line-height:1.55] [&_details]:text-control [&_summary]:text-brand [&_summary]:cursor-pointer [&_summary]:text-control [&_summary]:font-bold"
            >
              <div>
                <StatusBadge
                  class="compact-status-badge !text-caption"
                  :status="claim.status"
                /><span class="text-muted text-fine uppercase">{{
                  claim.classification.replace("_", " ")
                }}</span>
              </div>
              <p>{{ claim.text }}</p>
              <details>
                <summary>
                  {{ claim.provenance.length }} source reference{{
                    claim.provenance.length === 1 ? "" : "s"
                  }}
                </summary>
                <ul
                  class="[margin:16px_0_0] p-0 [list-style:none] [&_li]:grid [&_li]:[gap:4px] [&_li]:[padding:9px_0] [&_li]:border-t [&_li]:border-line [&_button]:inline-flex [&_button]:[gap:4px] [&_button]:items-center [&_button]:[width:max-content] [&_button]:max-w-full [&_button]:p-0 [&_button]:text-brand [&_button]:text-control [&_button]:font-bold [&_button]:[background:transparent] [&_button]:border-0 [&_code]:[width:max-content] [&_code]:max-w-full [&_code]:[padding:3px_5px] [&_code]:overflow-auto [&_code]:[background:#eef1ef] [&_code]:[border-radius:3px] [&_small]:text-muted"
                >
                  <li
                    v-for="source in claim.provenance"
                    :key="source.source_record_id"
                  >
                    <button type="button" @click="openSource(source)">
                      {{ source.original_filename }}
                      <ExternalLink :size="13" /></button
                    ><code>{{ JSON.stringify(source.locator) }}</code
                    ><small
                      >SHA-256 {{ source.sha256.slice(0, 12) }}… ·
                      {{ source.parser_name }}
                      {{ source.parser_version }}</small
                    >
                  </li>
                </ul>
              </details>
            </div>
          </section>
          <section
            v-if="selected.relationships.length"
            class="reader-section [padding:25px_0_4px] [&_h3]:[margin:0_0_14px] [&_h3]:text-control [&_h3]:[letter-spacing:0.08em] [&_h3]:uppercase"
          >
            <h3>Relationships</h3>
            <div
              class="grid [grid-template-columns:repeat(2,_1fr)] [gap:8px] [&_a]:flex [&_a]:[gap:10px] [&_a]:items-center [&_a]:[padding:12px] [&_a]:[background:#fafbf9] [&_a]:border [&_a]:border-line [&_a]:rounded-control [&_a]:no-underline [&_span]:grid [&_small]:text-muted [&_small]:text-fine [&_small]:uppercase [&_strong]:[margin-top:3px] [&_strong]:text-control mobile:[grid-template-columns:1fr]"
            >
              <RouterLink
                v-for="relationship in selected.relationships"
                :key="`${relationship.relation}-${relationship.target_id}`"
                :to="`/knowledge/${relationship.target_id}`"
                ><Link2 :size="16" /><span
                  ><small>{{ relationship.relation }}</small
                  ><strong>{{ relationship.target_title }}</strong></span
                ></RouterLink
              >
            </div>
          </section>
          <section
            v-if="
              connectionsLoading ||
              connectionsError ||
              backlinks.length ||
              related.length
            "
            class="reader-section [padding:25px_0_4px] [&_h3]:[margin:0_0_14px] [&_h3]:text-control [&_h3]:[letter-spacing:0.08em] [&_h3]:uppercase"
          >
            <h3>Connected pages</h3>
            <p
              v-if="connectionsLoading"
              class="connection-status m-0 text-muted text-label"
            >
              Loading connected pages…
            </p>
            <p
              v-else-if="connectionsError"
              class="connection-status m-0 text-muted text-label text-danger"
            >
              {{ connectionsError }}
            </p>
            <div
              class="tag-row [&_a]:[padding:5px_8px] [&_a]:text-brand [&_a]:bg-brand-pale [&_a]:[border-radius:6px] [&_a]:text-control [&_a]:no-underline flex flex-wrap [gap:6px] [margin-top:15px] [&>span]:[padding:4px_7px] [&>span]:[color:#60716b] [&>span]:[background:#f2f4f2] [&>span]:[border-radius:5px] [&>span]:text-control"
            >
              <RouterLink
                v-for="page in [...backlinks, ...related].filter(
                  (page, index, list) =>
                    list.findIndex((item) => item.id === page.id) === index,
                )"
                :key="page.id"
                :to="`/knowledge/${page.id}`"
                >{{ page.title }}</RouterLink
              >
            </div>
          </section>
          <section
            v-if="originalSources.length"
            class="reader-section [padding:25px_0_4px] [&_h3]:[margin:0_0_14px] [&_h3]:text-control [&_h3]:[letter-spacing:0.08em] [&_h3]:uppercase"
          >
            <h3>Immutable original files</h3>
            <div class="flex flex-wrap [gap:7px]">
              <button
                v-for="source in originalSources"
                :key="source.document_version_id"
                type="button"
                class="inline-flex items-center [gap:6px] [padding:7px_9px] [color:#365b4e] [background:#f5f8f6] border border-line rounded-control text-label font-bold hover:text-brand hover:border-brand"
                :title="`Open immutable original: ${source.original_filename}`"
                @click="openSource(source)"
              >
                <FileLock2 :size="15" /> Immutable original
                <span class="text-muted font-medium"
                  >· {{ source.original_filename }}</span
                >
              </button>
            </div>
          </section>
        </article>
      </main>
    </div>
  </section>
</template>
