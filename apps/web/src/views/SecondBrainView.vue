<script setup lang="ts">
import {
  Expand,
  ExternalLink,
  Focus,
  Maximize2,
  Minimize2,
  Network,
  RefreshCw,
  RotateCcw,
  Search,
} from "@lucide/vue";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError, api } from "../api/client";
import PageHeader from "../components/PageHeader.vue";
import SecondBrainGraph from "../components/SecondBrainGraph.vue";
import type { WikiGraphNode, WikiGraphResponse } from "../types";

interface GraphControls {
  fit: () => Promise<void>;
  focusNode: (id: string) => Promise<void>;
  reset: () => Promise<void>;
}

const route = useRoute();
const router = useRouter();
const graphView = ref<GraphControls | null>(null);
const graph = ref<WikiGraphResponse | null>(null);
const allNodes = ref<WikiGraphNode[]>([]);
const loading = ref(true);
const refreshing = ref(false);
const error = ref("");
const graphUnavailable = ref("");
const recoveryNotice = ref("");
const mode = ref<"global" | "local">(
  route.query.mode === "local" ? "local" : "global",
);
const depth = ref(
  [1, 2, 3].includes(Number(route.query.depth)) ? Number(route.query.depth) : 1,
);
const rootId = ref(
  typeof route.query.root === "string" ? route.query.root : "",
);
const rootSearch = ref("");
const search = ref("");
const focusedId = ref<string | null>(null);
const tagFilter = ref("all");
const folderFilter = ref("all");
const typeFilter = ref("all");
const showIsolated = ref(true);
const expanded = ref(false);
const storageKey = "knemora.second-brain.controls";
const legendClasses: Record<string, string> = {
  entity: "[&_i]:bg-brand",
  concept: "[&_i]:bg-[#60a5fa]",
  topic: "[&_i]:bg-[#a78bfa]",
  synthesis: "[&_i]:bg-[#f59e0b]",
  dataset: "[&_i]:bg-[#22d3ee]",
};

const rootMatches = computed(() => {
  const query = rootSearch.value.trim().toLocaleLowerCase();
  const matches = query
    ? allNodes.value.filter((node) =>
        [node.title, ...node.aliases].some((name) =>
          name.toLocaleLowerCase().includes(query),
        ),
      )
    : allNodes.value;
  return matches.slice(0, 12);
});
const searchMatches = computed(() => {
  const query = search.value.trim().toLocaleLowerCase();
  if (!query) return [];
  return allNodes.value
    .filter((node) => node.title.toLocaleLowerCase().includes(query))
    .slice(0, 20);
});
const tags = computed(() =>
  [...new Set((graph.value?.nodes ?? []).flatMap((node) => node.tags))].sort(),
);
const folders = computed(() =>
  [...new Set((graph.value?.nodes ?? []).map((node) => node.folder))].sort(),
);
const documentTypes = computed(() =>
  [
    ...new Set((graph.value?.nodes ?? []).map((node) => node.document_type)),
  ].sort(),
);
const visibleNodes = computed(() =>
  (graph.value?.nodes ?? []).filter(
    (node) =>
      (tagFilter.value === "all" || node.tags.includes(tagFilter.value)) &&
      (folderFilter.value === "all" || node.folder === folderFilter.value) &&
      (typeFilter.value === "all" || node.document_type === typeFilter.value) &&
      (showIsolated.value || !node.isolated),
  ),
);
const visibleIds = computed(
  () => new Set(visibleNodes.value.map((node) => node.id)),
);
const visibleEdges = computed(() =>
  (graph.value?.edges ?? []).filter(
    (edge) =>
      visibleIds.value.has(edge.source) && visibleIds.value.has(edge.target),
  ),
);
const selectedRoot = computed(() =>
  allNodes.value.find(
    (node) => node.id === graph.value?.root_id || node.id === rootId.value,
  ),
);

async function loadGraph(forceRefresh = false) {
  if (mode.value === "local" && !rootId.value) {
    graph.value = null;
    loading.value = false;
    return;
  }
  error.value = "";
  graphUnavailable.value = "";
  recoveryNotice.value = "";
  if (forceRefresh) refreshing.value = true;
  else loading.value = true;
  const requestedLocalRoot =
    mode.value === "local" && rootId.value ? rootId.value : null;
  const globalRequest =
    requestedLocalRoot || !allNodes.value.length
      ? api.getWikiGraph({ refresh: forceRefresh })
      : Promise.resolve(null);
  try {
    const options = {
      root: requestedLocalRoot ?? undefined,
      depth: depth.value,
      refresh: forceRefresh,
    };
    const [result, global] = await Promise.all([
      api.getWikiGraph(options),
      globalRequest,
    ]);
    graph.value = result;
    if (global) allNodes.value = global.nodes;
    else if (result.mode === "global") allNodes.value = result.nodes;
    if (result.root_id) rootId.value = result.root_id;
    syncRoute();
  } catch (reason) {
    let graphError = reason;
    if (
      requestedLocalRoot &&
      reason instanceof ApiError &&
      reason.status === 404
    ) {
      clearMissingLocalRoot(requestedLocalRoot);
      syncRoute();
      try {
        const global = await globalRequest;
        if (global) {
          graph.value = global;
          allNodes.value = global.nodes;
          recoveryNotice.value =
            "The selected local root no longer exists. Showing the global graph.";
          return;
        }
      } catch (fallbackReason) {
        graphError = fallbackReason;
      }
    }
    error.value =
      graphError instanceof Error
        ? graphError.message
        : "Unable to load the knowledge graph.";
  } finally {
    loading.value = false;
    refreshing.value = false;
  }
}

function clearMissingLocalRoot(missingRoot: string) {
  mode.value = "global";
  rootId.value = "";
  rootSearch.value = "";
  focusedId.value = null;
  try {
    const saved = JSON.parse(
      sessionStorage.getItem(storageKey) ?? "{}",
    ) as Record<string, unknown>;
    if (saved.rootId === missingRoot) {
      saved.mode = "global";
      saved.rootId = "";
      sessionStorage.setItem(storageKey, JSON.stringify(saved));
    }
  } catch {
    sessionStorage.removeItem(storageKey);
  }
}

function syncRoute() {
  const query =
    mode.value === "local" && rootId.value
      ? { mode: "local", root: rootId.value, depth: String(depth.value) }
      : {};
  void router.replace({ name: "second-brain", query });
}

function selectRoot(node: WikiGraphNode) {
  rootId.value = node.id;
  rootSearch.value = node.title;
  mode.value = "local";
  void loadGraph();
}

function showGlobal() {
  mode.value = "global";
  void loadGraph();
}

function showLocal() {
  mode.value = "local";
  void loadGraph();
}

function changeDepth(value: number) {
  depth.value = value;
  if (mode.value === "local" && rootId.value) void loadGraph();
}

function focusNode(node: WikiGraphNode) {
  if (mode.value === "local" && !rootId.value) {
    selectRoot(node);
    return;
  }
  const visible = graph.value?.nodes.some((item) => item.id === node.id);
  if (!visible) {
    rootId.value = node.id;
    mode.value = "local";
    void loadGraph().then(() => {
      focusedId.value = node.id;
      void graphView.value?.focusNode(node.id);
    });
    return;
  }
  focusedId.value = node.id;
  void graphView.value?.focusNode(node.id);
}

function openNode(node: WikiGraphNode) {
  sessionStorage.setItem(
    storageKey,
    JSON.stringify({
      mode: mode.value,
      depth: depth.value,
      rootId: rootId.value,
      tag: tagFilter.value,
      folder: folderFilter.value,
      type: typeFilter.value,
      showIsolated: showIsolated.value,
    }),
  );
  void router.push(node.detail_reference);
}

function restoreControls() {
  if (Object.keys(route.query).length) return;
  try {
    const saved = JSON.parse(
      sessionStorage.getItem(storageKey) ?? "{}",
    ) as Record<string, unknown>;
    if (saved.mode === "local") mode.value = "local";
    if ([1, 2, 3].includes(Number(saved.depth)))
      depth.value = Number(saved.depth);
    if (typeof saved.rootId === "string") rootId.value = saved.rootId;
    if (typeof saved.tag === "string") tagFilter.value = saved.tag;
    if (typeof saved.folder === "string") folderFilter.value = saved.folder;
    if (typeof saved.type === "string") typeFilter.value = saved.type;
    if (typeof saved.showIsolated === "boolean")
      showIsolated.value = saved.showIsolated;
  } catch {
    sessionStorage.removeItem(storageKey);
  }
}

function toggleExpanded() {
  expanded.value = !expanded.value;
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === "Escape" && expanded.value) expanded.value = false;
}

watch([tagFilter, folderFilter, typeFilter, showIsolated], () => {
  focusedId.value = null;
});

watch(expanded, (value) => {
  document.body.classList.toggle("graph-expanded-open", value);
});

onMounted(() => {
  restoreControls();
  window.addEventListener("keydown", handleKeydown);
  void loadGraph();
});

onBeforeUnmount(() => {
  window.removeEventListener("keydown", handleKeydown);
  document.body.classList.remove("graph-expanded-open");
});
</script>

<template>
  <section
    class="page-content [width:min(1380px,_100%)] [margin:0_auto] [padding:36px_clamp(22px,_3.5vw,_52px)_64px] mobile:[padding:27px_16px_45px]"
  >
    <PageHeader
      eyebrow="Native knowledge workspace"
      title="Second Brain"
      description="Explore the real links in your portable Markdown Wiki. Knemora renders this graph locally; no external application is required."
    />

    <div
      class="brain-mode-tabs inline-flex [gap:4px] [padding:4px] [margin-bottom:16px] [background:#e7ece8] rounded-field [&_button]:inline-flex [&_button]:items-center [&_button]:justify-center [&_button]:[gap:6px] [&_button]:[padding:8px_11px] [&_button]:[color:#596963] [&_button]:[background:transparent] [&_button]:border-0 [&_button]:rounded-control [&_button]:text-label [&_button]:font-bold [&_button.active]:[color:#183329] [&_button.active]:bg-white [&_button.active]:[box-shadow:0_1px_4px_rgb(17_38_31_/_9%)]"
      role="tablist"
      aria-label="Graph view"
    >
      <button
        type="button"
        role="tab"
        :aria-selected="mode === 'global'"
        :class="{ active: mode === 'global' }"
        @click="showGlobal"
      >
        Global Graph
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="mode === 'local'"
        :class="{ active: mode === 'local' }"
        @click="showLocal"
      >
        Local Graph
      </button>
    </div>

    <div
      class="brain-layout grid [grid-template-columns:286px_minmax(0,_1fr)] [gap:14px] [min-height:680px] [&.is-expanded]:fixed [&.is-expanded]:[inset:0] [&.is-expanded]:[z-index:110] [&.is-expanded]:[grid-template-columns:clamp(240px,_22vw,_340px)_minmax(0,_1fr)] [&.is-expanded]:[gap:0] [&.is-expanded]:[width:100vw] [&.is-expanded]:[height:100dvh] [&.is-expanded]:[min-height:0] [&.is-expanded]:[background:#13201c] [&.is-expanded_.brain-sidebar]:h-full [&.is-expanded_.brain-sidebar]:[max-height:none] [&.is-expanded_.brain-sidebar]:overflow-y-auto [&.is-expanded_.brain-sidebar]:[border-width:0_1px_0_0] [&.is-expanded_.brain-sidebar]:[border-radius:0] [&.is-expanded_.brain-root-control]:hidden [&.is-expanded_.brain-stage]:h-full [&.is-expanded_.brain-stage]:[min-height:0] [&.is-expanded_.brain-stage]:border-0 [&.is-expanded_.brain-stage]:[border-radius:0] [&.is-expanded_.second-brain-canvas]:[min-height:0] tablet:[grid-template-columns:240px_minmax(0,_1fr)] mobile:[grid-template-columns:1fr] mobile:[&.is-expanded]:[grid-template-columns:minmax(170px,_38vw)_minmax(0,_1fr)] mobile:[&.is-expanded_.brain-sidebar]:block mobile:[&.is-expanded_.brain-sidebar]:[padding:6px_12px_12px] mobile:[&.is-expanded_.brain-toolbar]:[padding:8px] mobile:[&.is-expanded_.brain-actions]:[gap:5px] mobile:[&.is-expanded_.brain-actions_button]:[padding:7px]"
      :class="{ 'is-expanded': expanded }"
    >
      <aside
        class="surface brain-sidebar bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] [padding:6px_18px_18px] overflow-y-auto [&_.search-field_input]:w-full mobile:grid mobile:[grid-template-columns:repeat(2,_minmax(0,_1fr))] mobile:[gap:0_18px] mobile:[max-height:480px] phone:[grid-template-columns:1fr]"
      >
        <div
          v-if="expanded"
          class="brain-mode-tabs inline-flex [gap:4px] [padding:4px] [margin-bottom:16px] [background:#e7ece8] rounded-field [&_button]:inline-flex [&_button]:items-center [&_button]:justify-center [&_button]:[gap:6px] [&_button]:[padding:8px_11px] [&_button]:[color:#596963] [&_button]:[background:transparent] [&_button]:border-0 [&_button]:rounded-control [&_button]:text-label [&_button]:font-bold [&_button.active]:[color:#183329] [&_button.active]:bg-white [&_button.active]:[box-shadow:0_1px_4px_rgb(17_38_31_/_9%)] flex w-full [margin:12px_0_0] [&_button]:flex-1"
          role="tablist"
          aria-label="Expanded graph view"
        >
          <button
            type="button"
            role="tab"
            :aria-selected="mode === 'global'"
            :class="{ active: mode === 'global' }"
            @click="showGlobal"
          >
            Global Graph
          </button>
          <button
            type="button"
            role="tab"
            :aria-selected="mode === 'local'"
            :class="{ active: mode === 'local' }"
            @click="showLocal"
          >
            Local Graph
          </button>
        </div>
        <section
          v-if="mode === 'local'"
          class="brain-control-section brain-root-control grid [gap:9px] [padding:16px_0] border-b border-line [&:last-child]:[border-bottom:0] [&_h2]:m-0 [&_h2]:text-label [&_h2]:font-extrabold [&_h2]:[letter-spacing:0.04em] [&_h2]:uppercase [&>label:not(.search-field,_.check-row)]:grid [&>label:not(.search-field,_.check-row)]:[gap:5px] [&>label:not(.search-field,_.check-row)]:text-ink [&>label:not(.search-field,_.check-row)]:text-label [&>label:not(.search-field,_.check-row)]:font-semibold [&_select]:w-full [&_select]:[padding:8px_9px] [&_select]:[background:#fbfcfb] [&_select]:border [&_select]:border-line [&_select]:rounded-control [&_select]:text-label"
        >
          <h2>Root page</h2>
          <label
            class="search-field focus-within:border-brand focus-within:shadow-[0_0_0_3px_rgba(51,209,51,0.09)] flex [gap:8px] items-center [min-height:36px] [padding:0_10px] [background:#f8f9f7] border border-line rounded-control [&_input]:[width:180px] [&_input]:p-0 [&_input]:[background:transparent] [&_input]:border-0 [&_input]:outline-none [&_input]:text-label [&_input:focus]:!shadow-none"
          >
            <Search :size="16" />
            <span
              class="sr-only absolute [width:1px] [height:1px] p-0 [margin:-1px] overflow-hidden [clip:rect(0,_0,_0,_0)] whitespace-nowrap border-0"
              >Search for a local graph root</span
            >
            <input v-model="rootSearch" placeholder="Find a page…" />
          </label>
          <div
            v-if="rootSearch || !rootId"
            class="brain-results compact-results grid [max-height:230px] overflow-y-auto [background:#f8faf8] border border-line rounded-action [&>button]:flex [&>button]:items-center [&>button]:justify-between [&>button]:min-w-0 [&>button]:border-b [&>button]:border-line [&>div]:flex [&>div]:items-center [&>div]:justify-between [&>div]:min-w-0 [&>div]:border-b [&>div]:border-line [&>:last-child]:[border-bottom:0] [&_button]:flex [&_button]:items-center [&_button]:[gap:7px] [&_button]:min-w-0 [&_button]:[padding:9px] [&_button]:text-left [&_button]:[background:transparent] [&_button]:border-0 [&_button:first-child]:flex-1 [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_strong]:text-body [&_strong]:font-medium [&_small]:overflow-hidden [&_small]:text-ellipsis [&_small]:whitespace-nowrap [&_small]:text-muted [&_small]:text-caption [&_p]:[padding:10px] [&_p]:m-0 [&_p]:text-muted [&_p]:text-label [&_button]:grid"
          >
            <button
              v-for="node in rootMatches"
              :key="node.id"
              type="button"
              @click="selectRoot(node)"
            >
              <strong>{{ node.title }}</strong
              ><small>{{ node.folder }}</small>
            </button>
          </div>
          <div
            v-if="selectedRoot"
            class="selected-root grid [gap:2px] [padding:9px_10px] bg-brand-pale [border:1px_solid_#c9edc9] rounded-action [&_span]:text-muted [&_span]:text-caption"
          >
            <span>Selected root</span><strong>{{ selectedRoot.title }}</strong>
          </div>
          <fieldset
            class="[&_button]:inline-flex [&_button]:items-center [&_button]:justify-center [&_button]:[gap:6px] [&_button]:[padding:8px_11px] [&_button]:[color:#596963] [&_button]:[background:transparent] [&_button]:border-0 [&_button]:rounded-control [&_button]:text-label [&_button]:font-bold [&_button.active]:[color:#183329] [&_button.active]:bg-white [&_button.active]:[box-shadow:0_1px_4px_rgb(17_38_31_/_9%)] [&_legend]:m-0 [&_legend]:text-label [&_legend]:font-extrabold [&_legend]:[letter-spacing:0.04em] [&_legend]:uppercase grid [grid-template-columns:repeat(3,_1fr)] [gap:4px] p-0 [margin:4px_0_0] border-0 [&_legend]:[grid-column:1_/_-1] [&_legend]:[margin-bottom:4px] [&_button]:[padding:7px_4px] [&_button]:[background:#edf1ee] [&_button]:text-caption"
          >
            <legend>Neighborhood depth</legend>
            <button
              v-for="value in [1, 2, 3]"
              :key="value"
              type="button"
              :class="{ active: depth === value }"
              @click="changeDepth(value)"
            >
              {{ value }} hop{{ value === 1 ? "" : "s" }}
            </button>
          </fieldset>
        </section>

        <section
          class="brain-control-section brain-find-control grid [gap:9px] [padding:16px_0] border-b border-line [&:last-child]:[border-bottom:0] [&_h2]:m-0 [&_h2]:text-label [&_h2]:font-extrabold [&_h2]:[letter-spacing:0.04em] [&_h2]:uppercase [&>label:not(.search-field,_.check-row)]:grid [&>label:not(.search-field,_.check-row)]:[gap:5px] [&>label:not(.search-field,_.check-row)]:text-ink [&>label:not(.search-field,_.check-row)]:text-label [&>label:not(.search-field,_.check-row)]:font-semibold [&_select]:w-full [&_select]:[padding:8px_9px] [&_select]:[background:#fbfcfb] [&_select]:border [&_select]:border-line [&_select]:rounded-control [&_select]:text-label"
        >
          <h2>Find a page</h2>
          <label
            class="search-field focus-within:border-brand focus-within:shadow-[0_0_0_3px_rgba(51,209,51,0.09)] flex [gap:8px] items-center [min-height:36px] [padding:0_10px] [background:#f8f9f7] border border-line rounded-control [&_input]:[width:180px] [&_input]:p-0 [&_input]:[background:transparent] [&_input]:border-0 [&_input]:outline-none [&_input]:text-label [&_input:focus]:!shadow-none"
          >
            <Search :size="16" />
            <span
              class="sr-only absolute [width:1px] [height:1px] p-0 [margin:-1px] overflow-hidden [clip:rect(0,_0,_0,_0)] whitespace-nowrap border-0"
              >Search page titles</span
            >
            <input v-model="search" placeholder="Search titles…" />
          </label>
          <div
            v-if="search"
            class="brain-results grid [max-height:230px] overflow-y-auto [background:#f8faf8] border border-line rounded-action [&>button]:flex [&>button]:items-center [&>button]:justify-between [&>button]:min-w-0 [&>button]:border-b [&>button]:border-line [&>div]:flex [&>div]:items-center [&>div]:justify-between [&>div]:min-w-0 [&>div]:border-b [&>div]:border-line [&>:last-child]:[border-bottom:0] [&_button]:flex [&_button]:items-center [&_button]:[gap:7px] [&_button]:min-w-0 [&_button]:[padding:9px] [&_button]:text-left [&_button]:[background:transparent] [&_button]:border-0 [&_button:first-child]:flex-1 [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_small]:overflow-hidden [&_small]:text-ellipsis [&_small]:whitespace-nowrap [&_small]:text-muted [&_small]:text-caption [&_p]:[padding:10px] [&_p]:m-0 [&_p]:text-muted [&_p]:text-label [&_span]:text-body [&_span]:font-medium"
          >
            <div v-for="node in searchMatches" :key="node.id">
              <button type="button" @click="focusNode(node)">
                <Focus :size="14" /><span>{{ node.title }}</span>
              </button>
              <button
                type="button"
                title="Open Wiki Detail"
                @click="openNode(node)"
              >
                <ExternalLink :size="14" />
              </button>
            </div>
            <p v-if="!searchMatches.length">No page titles match.</p>
          </div>
        </section>

        <section
          class="brain-control-section grid [gap:9px] [padding:16px_0] border-b border-line [&:last-child]:[border-bottom:0] [&_h2]:m-0 [&_h2]:text-label [&_h2]:font-extrabold [&_h2]:[letter-spacing:0.04em] [&_h2]:uppercase [&>label:not(.search-field,_.check-row)]:grid [&>label:not(.search-field,_.check-row)]:[gap:5px] [&>label:not(.search-field,_.check-row)]:text-ink [&>label:not(.search-field,_.check-row)]:text-label [&>label:not(.search-field,_.check-row)]:font-semibold [&_select]:w-full [&_select]:[padding:8px_9px] [&_select]:[background:#fbfcfb] [&_select]:border [&_select]:border-line [&_select]:rounded-control [&_select]:text-label"
        >
          <h2>Filters</h2>
          <label>
            Page type
            <select
              class="h-9 rounded-[7px] border border-line bg-white py-0 pl-[10px] pr-[30px] text-label outline-none focus:border-brand focus:shadow-[0_0_0_3px_rgba(51,209,51,0.09)]"
              v-model="typeFilter"
            >
              <option value="all">All page types</option>
              <option
                v-for="value in documentTypes"
                :key="value"
                :value="value"
              >
                {{ value }}
              </option>
            </select>
          </label>
          <label>
            Tag
            <select
              class="h-9 rounded-[7px] border border-line bg-white py-0 pl-[10px] pr-[30px] text-label outline-none focus:border-brand focus:shadow-[0_0_0_3px_rgba(51,209,51,0.09)]"
              v-model="tagFilter"
            >
              <option value="all">All tags</option>
              <option v-for="value in tags" :key="value" :value="value">
                #{{ value }}
              </option>
            </select>
          </label>
          <label>
            Folder
            <select
              class="h-9 rounded-[7px] border border-line bg-white py-0 pl-[10px] pr-[30px] text-label outline-none focus:border-brand focus:shadow-[0_0_0_3px_rgba(51,209,51,0.09)]"
              v-model="folderFilter"
            >
              <option value="all">All folders</option>
              <option v-for="value in folders" :key="value" :value="value">
                {{ value }}
              </option>
            </select>
          </label>
          <label class="check-row flex items-center [gap:8px] text-label">
            <input v-model="showIsolated" type="checkbox" /> Show isolated pages
          </label>
        </section>

        <section
          class="brain-control-section grid [gap:9px] [padding:16px_0] border-b border-line [&:last-child]:[border-bottom:0] [&_h2]:m-0 [&_h2]:text-label [&_h2]:font-extrabold [&_h2]:[letter-spacing:0.04em] [&_h2]:uppercase [&>label:not(.search-field,_.check-row)]:grid [&>label:not(.search-field,_.check-row)]:[gap:5px] [&>label:not(.search-field,_.check-row)]:text-ink [&>label:not(.search-field,_.check-row)]:text-label [&>label:not(.search-field,_.check-row)]:font-semibold [&_select]:w-full [&_select]:[padding:8px_9px] [&_select]:[background:#fbfcfb] [&_select]:border [&_select]:border-line [&_select]:rounded-control [&_select]:text-label [grid-template-columns:repeat(2,_minmax(0,_1fr))] [&_h2]:[grid-column:1_/_-1] [&_small]:[grid-column:1_/_-1] [&_span]:flex [&_span]:items-center [&_span]:[gap:6px] [&_span]:text-muted [&_span]:text-label [&_i]:[width:8px] [&_i]:[height:8px] [&_i]:[background:#94a3b8] [&_i]:rounded-full"
        >
          <h2>Legend</h2>
          <span
            v-for="value in documentTypes"
            :key="value"
            :class="legendClasses[value]"
          >
            <i></i>{{ value }}
          </span>
          <small class="text-label"
            >Arrows retain the direction of each explicit link.</small
          >
        </section>
      </aside>

      <main
        class="surface brain-stage bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] relative flex min-w-0 [min-height:680px] overflow-hidden flex-col [background:#13201c] [border-color:#263a33] mobile:[min-height:560px]"
      >
        <div
          class="brain-toolbar relative [z-index:3] flex items-center justify-between [gap:12px] [min-height:55px] [padding:10px_13px] [color:#e7f0ed] [background:#172823] [border-bottom:1px_solid_#2b3d37] mobile:items-stretch mobile:flex-col"
        >
          <div
            class="graph-counts grid [grid-template-columns:repeat(3,_max-content)] [gap:2px_11px] items-center [&_strong]:[grid-column:1_/_-1] [&_span]:[color:#9aaba5] [&_span]:text-detail phone:items-start phone:flex-col phone:[gap:3px]"
          >
            <strong>{{ visibleNodes.length }} pages</strong>
            <span>{{ visibleEdges.length }} links</span>
            <span v-if="graph?.unresolved_count">
              {{ graph.unresolved_count }} unresolved
            </span>
            <span v-if="graph?.ambiguous_count">
              {{ graph.ambiguous_count }} ambiguous
            </span>
          </div>
          <div
            class="brain-actions [&_button]:inline-flex [&_button]:items-center [&_button]:justify-center [&_button]:[gap:6px] [&_button]:[padding:8px_11px] [&_button]:[color:#596963] [&_button]:[background:transparent] [&_button]:border-0 [&_button]:rounded-control [&_button]:text-label [&_button]:font-bold flex items-center [gap:11px] [&_button]:[color:#c7d4cf] [&_button]:[background:#22352f] [&_button]:[border:1px_solid_#314b42] [&_button:hover]:[color:white] [&_button:hover]:border-brand [&_button:focus-visible]:[color:white] [&_button:focus-visible]:border-brand mobile:flex-wrap"
          >
            <button
              type="button"
              :aria-pressed="expanded"
              @click="toggleExpanded"
            >
              <Minimize2 v-if="expanded" :size="15" />
              <Expand v-else :size="15" />
              {{ expanded ? "Minimize" : "Expand" }}
            </button>
            <button type="button" @click="graphView?.fit()">
              <Maximize2 :size="15" /> Fit
            </button>
            <button type="button" @click="graphView?.reset()">
              <RotateCcw :size="15" /> Reset layout
            </button>
            <button
              type="button"
              :disabled="refreshing"
              @click="loadGraph(true)"
            >
              <RefreshCw
                :size="15"
                :class="{ 'animate-spin-fast': refreshing }"
              />
              Refresh
            </button>
          </div>
        </div>

        <p
          v-if="recoveryNotice && !loading"
          class="graph-notice relative [z-index:2] [padding:8px_12px] m-0 [color:#c7d4cf] [background:#27362f] [border-bottom:1px_solid_#35463f] text-control"
        >
          {{ recoveryNotice }}
        </p>

        <div
          v-if="loading"
          class="brain-state grid place-items-center content-center flex-1 [padding:34px] [color:#c7d4cf] text-center [&_svg]:text-brand [&_h2]:[margin:12px_0_4px] [&_h2]:[color:white] [&_p]:[max-width:510px] [&_p]:[margin:0_0_14px] [&_p]:[color:#91a39d] [&_a]:[padding:8px_12px] [&_a]:[color:#102019] [&_a]:bg-brand [&_a]:border-0 [&_a]:rounded-control [&_a]:font-extrabold [&_a]:no-underline [&_button]:[padding:8px_12px] [&_button]:[color:#102019] [&_button]:bg-brand [&_button]:border-0 [&_button]:rounded-control [&_button]:font-extrabold [&_button]:no-underline"
        >
          <Network :size="42" />
          <h2>Building the graph…</h2>
          <p>Reading the revision-aware local Wiki index.</p>
        </div>
        <div
          v-else-if="error"
          class="brain-state grid place-items-center content-center flex-1 [padding:34px] [color:#c7d4cf] text-center [&_svg]:text-brand [&_h2]:[margin:12px_0_4px] [&_h2]:[color:white] [&_p]:[max-width:510px] [&_p]:[margin:0_0_14px] [&_p]:[color:#91a39d] [&_a]:[padding:8px_12px] [&_a]:[color:#102019] [&_a]:bg-brand [&_a]:border-0 [&_a]:rounded-control [&_a]:font-extrabold [&_a]:no-underline [&_button]:[padding:8px_12px] [&_button]:[color:#102019] [&_button]:bg-brand [&_button]:border-0 [&_button]:rounded-control [&_button]:font-extrabold [&_button]:no-underline"
        >
          <Network :size="42" />
          <h2>Graph unavailable</h2>
          <p>{{ error }}</p>
          <button type="button" @click="loadGraph(true)">Try again</button>
        </div>
        <div
          v-else-if="mode === 'local' && !rootId"
          class="brain-state grid place-items-center content-center flex-1 [padding:34px] [color:#c7d4cf] text-center [&_svg]:text-brand [&_h2]:[margin:12px_0_4px] [&_h2]:[color:white] [&_p]:[max-width:510px] [&_p]:[margin:0_0_14px] [&_p]:[color:#91a39d] [&_a]:[padding:8px_12px] [&_a]:[color:#102019] [&_a]:bg-brand [&_a]:border-0 [&_a]:rounded-control [&_a]:font-extrabold [&_a]:no-underline [&_button]:[padding:8px_12px] [&_button]:[color:#102019] [&_button]:bg-brand [&_button]:border-0 [&_button]:rounded-control [&_button]:font-extrabold [&_button]:no-underline"
        >
          <Focus :size="42" />
          <h2>Choose a root page</h2>
          <p>
            Search on the left, then select a page and a neighborhood depth.
          </p>
        </div>
        <div
          v-else-if="!graph?.total_nodes"
          class="brain-state grid place-items-center content-center flex-1 [padding:34px] [color:#c7d4cf] text-center [&_svg]:text-brand [&_h2]:[margin:12px_0_4px] [&_h2]:[color:white] [&_p]:[max-width:510px] [&_p]:[margin:0_0_14px] [&_p]:[color:#91a39d] [&_a]:[padding:8px_12px] [&_a]:[color:#102019] [&_a]:bg-brand [&_a]:border-0 [&_a]:rounded-control [&_a]:font-extrabold [&_a]:no-underline [&_button]:[padding:8px_12px] [&_button]:[color:#102019] [&_button]:bg-brand [&_button]:border-0 [&_button]:rounded-control [&_button]:font-extrabold [&_button]:no-underline"
        >
          <Network :size="42" />
          <h2>Your Second Brain is empty</h2>
          <p>Ingest a document to compile the first portable Wiki pages.</p>
          <RouterLink to="/ingestion">Open ingestion</RouterLink>
        </div>
        <template v-else>
          <p
            v-if="graph.truncated"
            class="graph-notice relative [z-index:2] [padding:8px_12px] m-0 [color:#c7d4cf] [background:#27362f] [border-bottom:1px_solid_#35463f] text-control"
          >
            Showing {{ graph.returned_nodes }} of {{ graph.total_nodes }} pages
            and {{ graph.returned_edges }} of {{ graph.total_edges }} links
            because the configured resource bound was reached.
          </p>
          <p
            v-if="graph.total_edges === 0"
            class="graph-notice relative [z-index:2] [padding:8px_12px] m-0 [color:#c7d4cf] [background:#27362f] [border-bottom:1px_solid_#35463f] text-control"
          >
            These pages do not link to one another yet. Isolated pages remain
            visible.
          </p>
          <p
            v-if="!visibleNodes.length"
            class="graph-notice relative [z-index:2] [padding:8px_12px] m-0 [color:#c7d4cf] [background:#27362f] [border-bottom:1px_solid_#35463f] text-control"
          >
            No pages match the current filters.
          </p>
          <SecondBrainGraph
            v-if="visibleNodes.length && !graphUnavailable"
            ref="graphView"
            :nodes="visibleNodes"
            :edges="visibleEdges"
            :focused-id="focusedId"
            :small-graph-threshold="graph.small_graph_threshold ?? 50"
            @open="openNode"
            @unavailable="graphUnavailable = $event"
          />
          <div
            v-else-if="graphUnavailable"
            class="grid [grid-template-columns:repeat(auto-fill,_minmax(190px,_1fr))] [gap:8px] [padding:12px] overflow-y-auto [&_.compact-state]:[grid-column:1_/_-1] [&>button]:grid [&>button]:[gap:3px] [&>button]:[padding:11px] [&>button]:[color:#dce7e3] [&>button]:text-left [&>button]:[background:#1b2c26] [&>button]:[border:1px_solid_#30453d] [&>button]:rounded-action [&_strong]:text-body [&_strong]:font-medium [&_small]:[color:#80928b]"
          >
            <div
              class="brain-state compact-state grid place-items-center content-center flex-1 [padding:34px] [color:#c7d4cf] text-center [&_svg]:text-brand [&_h2]:[margin:12px_0_4px] [&_h2]:[color:white] [&_p]:[max-width:510px] [&_p]:[margin:0_0_14px] [&_p]:[color:#91a39d] [&_a]:[padding:8px_12px] [&_a]:[color:#102019] [&_a]:bg-brand [&_a]:border-0 [&_a]:rounded-control [&_a]:font-extrabold [&_a]:no-underline [&_button]:[padding:8px_12px] [&_button]:[color:#102019] [&_button]:bg-brand [&_button]:border-0 [&_button]:rounded-control [&_button]:font-extrabold [&_button]:no-underline"
            >
              <Network :size="34" />
              <h2>Interactive graph unavailable</h2>
              <p>{{ graphUnavailable }} Use the accessible page list below.</p>
            </div>
            <button
              v-for="node in visibleNodes"
              :key="node.id"
              type="button"
              @click="openNode(node)"
            >
              <strong>{{ node.title }}</strong
              ><small>{{ node.folder }}</small>
            </button>
          </div>
        </template>

        <footer
          v-if="graph"
          class="relative [z-index:3] [padding:7px_12px] [color:#7f938c] [background:#172823] [border-top:1px_solid_#2b3d37] text-caption"
        >
          Indexed {{ new Date(graph.freshness.indexed_at).toLocaleString() }} ·
          Wiki revision {{ graph.freshness.wiki_revision }} ·
          {{ graph.freshness.file_count }} Markdown files
        </footer>
      </main>
    </div>
  </section>
</template>
