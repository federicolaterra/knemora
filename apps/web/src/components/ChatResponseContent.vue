<script setup lang="ts">
import { computed } from "vue";

import type { DatasetResult } from "../types";
import MarkdownContent from "./MarkdownContent.vue";
import SimpleChart from "./SimpleChart.vue";

type Part =
  | { kind: "markdown"; content: string }
  | { kind: "chart"; chart: NonNullable<DatasetResult["chart"]> };

const props = defineProps<{ content: string }>();

function chartFrom(value: unknown): NonNullable<DatasetResult["chart"]> | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Record<string, unknown>;
  if (
    !["bar", "line"].includes(String(candidate.type)) ||
    typeof candidate.x_column !== "string" ||
    !Array.isArray(candidate.x) ||
    !Array.isArray(candidate.series)
  ) {
    return null;
  }
  const series = candidate.series.filter(
    (item): item is { name: string; values: unknown[] } =>
      Boolean(
        item &&
        typeof item === "object" &&
        typeof (item as Record<string, unknown>).name === "string" &&
        Array.isArray((item as Record<string, unknown>).values),
      ),
  );
  if (!series.length) return null;
  return {
    type: candidate.type as "bar" | "line",
    x_column: candidate.x_column,
    x: candidate.x,
    series,
  };
}

const parts = computed<Part[]>(() => {
  const output: Part[] = [];
  const pattern = /```chart\s*([\s\S]*?)```/gi;
  let cursor = 0;
  for (const match of props.content.matchAll(pattern)) {
    const index = match.index ?? cursor;
    if (index > cursor)
      output.push({
        kind: "markdown",
        content: props.content.slice(cursor, index),
      });
    try {
      const chart = chartFrom(JSON.parse(match[1] ?? ""));
      if (chart) output.push({ kind: "chart", chart });
      else output.push({ kind: "markdown", content: match[0] });
    } catch {
      output.push({ kind: "markdown", content: match[0] });
    }
    cursor = index + match[0].length;
  }
  if (cursor < props.content.length)
    output.push({ kind: "markdown", content: props.content.slice(cursor) });
  return output.length
    ? output
    : [{ kind: "markdown", content: props.content }];
});
</script>

<template>
  <template v-for="(part, index) in parts" :key="index">
    <MarkdownContent v-if="part.kind === 'markdown'" :content="part.content" />
    <SimpleChart v-else :chart="part.chart" />
  </template>
</template>
