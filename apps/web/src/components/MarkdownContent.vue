<script setup lang="ts">
import DOMPurify from "dompurify";
import { marked } from "marked";
import { computed } from "vue";

const props = defineProps<{ content: string }>();

const html = computed(() => {
  const wikilinked = props.content.replace(
    /\[\[([^\]]+)\]\]/g,
    (_, title: string) => {
      const target = encodeURIComponent(title.trim());
      return `[${title}](/knowledge/${target})`;
    },
  );
  const rendered = marked.parse(wikilinked, {
    breaks: true,
    gfm: true,
  }) as string;
  return DOMPurify.sanitize(rendered, {
    USE_PROFILES: { html: true },
    ADD_ATTR: ["target", "rel"],
  });
});
</script>

<template>
  <!-- Content is sanitized because model and document text are untrusted. -->
  <div
    class="markdown-body font-sans text-copy leading-[1.65] text-[#2d3b36]"
    v-html="html"
  ></div>
</template>
