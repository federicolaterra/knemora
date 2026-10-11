<script setup lang="ts">
import { ArrowLeft, Network } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { api } from "../api/client";
import MarkdownContent from "../components/MarkdownContent.vue";
import PageHeader from "../components/PageHeader.vue";
import type { WikiMarkdownPage } from "../types";

const route = useRoute();
const page = ref<WikiMarkdownPage | null>(null);
const loading = ref(false);
const error = ref("");
const path = computed(() => {
  const value = route.params.pathMatch;
  return Array.isArray(value) ? value.join("/") : String(value ?? "");
});

watch(
  path,
  async (value) => {
    loading.value = true;
    error.value = "";
    page.value = null;
    try {
      page.value = await api.getWikiMarkdownPage(value);
    } catch (reason) {
      error.value =
        reason instanceof Error
          ? reason.message
          : "Unable to open this Markdown page.";
    } finally {
      loading.value = false;
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
      eyebrow="Portable Markdown"
      :title="page?.title ?? 'Wiki page'"
      description="A native, read-only view of a Markdown page stored inside the configured Wiki root."
    />
    <main
      class="surface bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] [max-width:960px] [min-height:520px] [padding:28px]"
    >
      <div
        v-if="loading"
        class="loading-block [padding:40px] text-muted text-center"
      >
        Opening Markdown page…
      </div>
      <div
        v-else-if="error"
        class="alert alert-danger flex items-center justify-between [gap:16px] [margin:0_0_20px] [padding:12px_15px] rounded-action text-label [&_button]:[color:inherit] [&_button]:[background:transparent] [&_button]:border-0 [&_button]:font-bold [&_button]:underline [color:#7b3525] [background:#fbece6] [border:1px_solid_#efc8bc]"
      >
        {{ error }}
      </div>
      <article v-else-if="page">
        <nav
          class="portable-reader-actions [&_a]:inline-flex [&_a]:items-center [&_a]:[gap:6px] [&_a]:[color:#226d33] [&_a]:text-label [&_a]:font-extrabold [&_a]:no-underline flex items-center [gap:15px] [margin-bottom:20px]"
          aria-label="Wiki page actions"
        >
          <RouterLink to="/second-brain"
            ><ArrowLeft :size="16" /> Second Brain</RouterLink
          >
          <RouterLink
            :to="{
              name: 'second-brain',
              query: { mode: 'local', root: page.id, depth: '1' },
            }"
          >
            <Network :size="16" /> Local Graph
          </RouterLink>
        </nav>
        <div
          class="flex items-center [gap:15px] [margin-bottom:20px] flex-wrap [padding:10px] text-muted [background:#f4f7f4] rounded-action text-control"
        >
          <span>{{ page.document_type }}</span
          ><code>{{ page.path }}</code>
          <span>Updated {{ new Date(page.modified_at).toLocaleString() }}</span>
        </div>
        <MarkdownContent :content="page.content" />
      </article>
    </main>
  </section>
</template>
