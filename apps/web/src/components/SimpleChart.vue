<script setup lang="ts">
import { computed } from "vue";

import type { DatasetResult } from "../types";

const props = defineProps<{ chart: NonNullable<DatasetResult["chart"]> }>();
const width = 720;
const height = 260;
const padding = 36;
const numeric = computed(() =>
  props.chart.series.flatMap((series) =>
    series.values.map((value) => Number(value) || 0),
  ),
);
const max = computed(() => Math.max(...numeric.value, 1));
const points = computed(() =>
  props.chart.series.map((series) => ({
    ...series,
    points: series.values.map((value, index) => {
      const denominator = Math.max(series.values.length - 1, 1);
      return {
        x: padding + (index / denominator) * (width - padding * 2),
        y:
          height -
          padding -
          ((Number(value) || 0) / max.value) * (height - padding * 2),
        value,
      };
    }),
  })),
);
const colors = ["#33d133", "#dd7c53", "#526daa", "#c39a32"];
</script>

<template>
  <div class="chart-wrap overflow-x-auto">
    <svg
      class="block w-full min-w-[480px] overflow-visible"
      :viewBox="`0 0 ${width} ${height}`"
      role="img"
      :aria-label="`${chart.type} chart of ${chart.x_column}`"
    >
      <line
        :x1="padding"
        :y1="height - padding"
        :x2="width - padding"
        :y2="height - padding"
        class="chart-axis stroke-[#cfd8d3] [stroke-width:1]"
      />
      <template v-for="(series, sIndex) in points" :key="series.name">
        <polyline
          v-if="chart.type === 'line'"
          :points="
            series.points.map((point) => `${point.x},${point.y}`).join(' ')
          "
          :stroke="colors[sIndex % colors.length]"
          class="chart-line fill-none [stroke-linecap:round] [stroke-linejoin:round] [stroke-width:3]"
        />
        <template v-for="(point, index) in series.points" :key="index">
          <circle
            v-if="chart.type === 'line'"
            :cx="point.x"
            :cy="point.y"
            r="4"
            :fill="colors[sIndex % colors.length]"
          >
            <title>{{ chart.x[index] }}: {{ point.value }}</title>
          </circle>
          <rect
            v-else
            :x="point.x - 12 + sIndex * 8"
            :y="point.y"
            width="16"
            :height="height - padding - point.y"
            rx="3"
            :fill="colors[sIndex % colors.length]"
          >
            <title>{{ chart.x[index] }}: {{ point.value }}</title>
          </rect>
        </template>
      </template>
      <text
        v-for="(label, index) in chart.x"
        :key="String(label)"
        :x="
          padding +
          (index / Math.max(chart.x.length - 1, 1)) * (width - padding * 2)
        "
        :y="height - 10"
        class="chart-label fill-muted [font:8px_Outfit,_sans-serif] [text-anchor:middle]"
      >
        {{ String(label).slice(0, 14) }}
      </text>
    </svg>
    <div class="chart-legend flex justify-center gap-3">
      <span
        v-for="(series, index) in chart.series"
        :key="series.name"
        class="flex items-center gap-[5px] text-fine text-muted"
        ><i
          class="size-[7px] rounded-full"
          :style="{ background: colors[index % colors.length] }"
        ></i
        >{{ series.name }}</span
      >
    </div>
  </div>
</template>
