<script setup lang="ts">
import { Activity, BookOpenCheck, Clock3, RefreshCw, Route } from "@lucide/vue";
import type { ChartConfiguration } from "chart.js";
import { computed, onMounted, ref } from "vue";

import { api } from "../api/client";
import AnalyticsChart from "../components/AnalyticsChart.vue";
import PageHeader from "../components/PageHeader.vue";
import type { MetricsResponse } from "../types";

const metrics = ref<MetricsResponse | null>(null);
const loading = ref(false);
const error = ref("");

const palette = {
  green: "#33d133",
  greenPale: "#dff6df",
  coral: "#dd7c53",
};

const requestEntries = computed(() =>
  Object.entries(metrics.value?.runtime.counters ?? {})
    .filter(([key]) => key.startsWith("http."))
    .sort((left, right) => right[1] - left[1])
    .slice(0, 8),
);
const requestTotal = computed(() =>
  Object.entries(metrics.value?.runtime.counters ?? {})
    .filter(([key]) => key.startsWith("http."))
    .reduce((sum, [, value]) => sum + value, 0),
);
function routeLabel(key: string) {
  return key
    .replace(/^http\./, "")
    .replace(/\.(\d{3})$/, "")
    .replace(".", " ")
    .replace("/api/v1", "")
    .replace("/{id}", "/:id");
}
const averagePipelineDuration = computed(() => {
  const values = [
    metrics.value?.ingestion.average_duration_ms,
    metrics.value?.compilation.average_duration_ms,
  ].filter((value): value is number => typeof value === "number");
  return values.length
    ? Math.round(values.reduce((sum, value) => sum + value, 0) / values.length)
    : 0;
});
const summary = computed(() => [
  {
    label: "Local requests",
    value: requestTotal.value,
    note: `${requestEntries.value.length} active routes`,
    icon: Route,
  },
  {
    label: "Knowledge pages",
    value: metrics.value?.knowledge.pages ?? 0,
    note: `${metrics.value?.knowledge.lint_errors ?? 0} lint errors`,
    icon: BookOpenCheck,
  },
  {
    label: "Pipeline jobs",
    value:
      (metrics.value?.ingestion.jobs ?? 0) +
      (metrics.value?.compilation.jobs ?? 0),
    note: `${(metrics.value?.ingestion.failures ?? 0) + (metrics.value?.compilation.failures ?? 0)} failures`,
    icon: Activity,
  },
  {
    label: "Average duration",
    value: `${averagePipelineDuration.value.toLocaleString()} ms`,
    note: "Ingestion and compilation",
    icon: Clock3,
  },
]);

const pipelineConfig = computed<ChartConfiguration>(() => ({
  type: "doughnut",
  data: {
    labels: ["Successful", "Failed"],
    datasets: [
      {
        data: [
          Math.max(
            0,
            (metrics.value?.ingestion.jobs ?? 0) +
              (metrics.value?.compilation.jobs ?? 0) -
              (metrics.value?.ingestion.failures ?? 0) -
              (metrics.value?.compilation.failures ?? 0),
          ),
          (metrics.value?.ingestion.failures ?? 0) +
            (metrics.value?.compilation.failures ?? 0),
        ],
        backgroundColor: [palette.green, palette.coral],
        borderWidth: 0,
        hoverOffset: 3,
      },
    ],
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    cutout: "72%",
    plugins: { legend: { position: "bottom" } },
  },
}));

const durationConfig = computed<ChartConfiguration>(() => ({
  type: "bar",
  data: {
    labels: ["Ingestion", "Compilation"],
    datasets: [
      {
        label: "Average duration (ms)",
        data: [
          metrics.value?.ingestion.average_duration_ms ?? 0,
          metrics.value?.compilation.average_duration_ms ?? 0,
        ],
        backgroundColor: [palette.green, palette.green],
        borderRadius: 8,
      },
    ],
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: { y: { beginAtZero: true, grid: { color: "#edf1ed" } } },
  },
}));

const knowledgeConfig = computed<ChartConfiguration>(() => ({
  type: "bar",
  data: {
    labels: ["Lint errors", "Lint warnings", "Duplicate uploads"],
    datasets: [
      {
        label: "Count",
        data: [
          metrics.value?.knowledge.lint_errors ?? 0,
          metrics.value?.knowledge.lint_warnings ?? 0,
          metrics.value?.knowledge.duplicate_uploads ?? 0,
        ],
        backgroundColor: [palette.coral, "#e9b949", palette.greenPale],
        borderColor: [palette.coral, "#c98f13", palette.green],
        borderWidth: 1,
        borderRadius: 8,
      },
    ],
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
  },
}));

const trafficConfig = computed<ChartConfiguration>(() => ({
  type: "bar",
  data: {
    labels: requestEntries.value.map(([key]) => routeLabel(key)),
    datasets: [
      {
        label: "Requests",
        data: requestEntries.value.map(([, value]) => value),
        backgroundColor: palette.green,
        borderRadius: 6,
      },
    ],
  },
  options: {
    indexAxis: "y",
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: { x: { beginAtZero: true, ticks: { precision: 0 } } },
  },
}));

async function refresh() {
  loading.value = true;
  error.value = "";
  try {
    metrics.value = await api.readMetrics();
  } catch (reason) {
    error.value =
      reason instanceof Error ? reason.message : "Unable to load metrics.";
  } finally {
    loading.value = false;
  }
}

onMounted(refresh);
</script>

<template>
  <section
    class="page-content [width:min(1380px,_100%)] [margin:0_auto] [padding:36px_clamp(22px,_3.5vw,_52px)_64px] mobile:[padding:27px_16px_45px]"
  >
    <PageHeader
      eyebrow="Local observability"
      title="Analytics"
      description="Content-free performance, reliability, and knowledge-quality signals."
    >
      <template #actions>
        <button
          class="button button-secondary inline-flex [gap:8px] items-center justify-center [min-height:38px] [padding:0_15px] [border:1px_solid_transparent] rounded-action text-label font-bold no-underline [transition:0.16s_ease] [color:#33433e] bg-surface [border-color:#d5ddd8] hover:[border-color:#a9bbb4]"
          type="button"
          :disabled="loading"
          @click="refresh"
        >
          <RefreshCw :size="16" :class="{ 'animate-spin-fast': loading }" />
          Refresh
        </button>
      </template>
    </PageHeader>

    <div
      class="flex [gap:10px] items-center [margin:-8px_0_20px] [padding:12px_14px] [color:#3e5b4a] [background:linear-gradient(90deg,_#eefbee,_#fff)] [border:1px_solid_#d5ebd5] rounded-field text-label [&_svg]:text-brand"
    >
      <Activity :size="18" />
      <span
        ><strong>Metadata only.</strong> No prompts, source text, or hidden
        reasoning are recorded.</span
      >
    </div>
    <div
      v-if="error"
      class="alert alert-danger flex items-center justify-between [gap:16px] [margin:0_0_20px] [padding:12px_15px] rounded-action text-label [&_button]:[color:inherit] [&_button]:[background:transparent] [&_button]:border-0 [&_button]:font-bold [&_button]:underline [color:#7b3525] [background:#fbece6] [border:1px_solid_#efc8bc]"
    >
      {{ error }}
    </div>
    <div
      v-else-if="!metrics"
      class="loading-block [padding:40px] text-muted text-center"
    >
      Loading analytics…
    </div>
    <template v-else>
      <div
        class="grid [grid-template-columns:repeat(4,_1fr)] [gap:14px] tablet:[grid-template-columns:repeat(2,_1fr)] phone:[grid-template-columns:1fr_1fr] phone:[gap:9px]"
      >
        <article
          v-for="stat in summary"
          :key="stat.label"
          class="stat-card summary-card-copy relative [min-height:145px] [padding:20px] bg-surface border border-line rounded-composer [&>strong]:block [&>strong]:[margin-top:20px] [&>strong]:[font-size:31px] [&>strong]:font-medium [&_h2]:[margin:5px_0_3px] [&_h2]:text-label [&_h2]:font-bold [&_p]:m-0 [&_p]:text-muted [&_p]:text-label phone:[min-height:125px] phone:[padding:15px] phone:[&>strong]:[margin-top:30px]"
        >
          <span
            class="stat-icon absolute [top:17px] [right:17px] grid place-items-center [width:33px] [height:33px] text-brand bg-brand-pale rounded-action"
            ><component :is="stat.icon" :size="20"
          /></span>
          <strong>{{ stat.value }}</strong>
          <h2>{{ stat.label }}</h2>
          <p>{{ stat.note }}</p>
        </article>
      </div>

      <div
        class="grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:16px] [margin-top:16px] tablet:[grid-template-columns:1fr]"
      >
        <article
          class="surface analytics-card bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] min-w-0 [padding:22px] [&_h2]:m-0 [&_h2]:font-sans [&_h2]:text-title-lg [&_h2]:font-medium [&>div:first-child>p:last-child]:[margin:7px_0_0] [&>div:first-child>p:last-child]:text-muted [&>div:first-child>p:last-child]:text-body"
        >
          <div>
            <p
              class="section-kicker [margin:0_0_8px] text-brand text-caption font-medium [letter-spacing:0.13em] uppercase"
            >
              Reliability
            </p>
            <h2>Pipeline outcomes</h2>
            <p>Completed work compared with failures across both stages.</p>
          </div>
          <AnalyticsChart
            :configuration="pipelineConfig"
            label="Pipeline outcomes chart"
          />
        </article>
        <article
          class="surface analytics-card bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] min-w-0 [padding:22px] [&_h2]:m-0 [&_h2]:font-sans [&_h2]:text-title-lg [&_h2]:font-medium [&>div:first-child>p:last-child]:[margin:7px_0_0] [&>div:first-child>p:last-child]:text-muted [&>div:first-child>p:last-child]:text-body"
        >
          <div>
            <p
              class="section-kicker [margin:0_0_8px] text-brand text-caption font-medium [letter-spacing:0.13em] uppercase"
            >
              Performance
            </p>
            <h2>Average processing time</h2>
            <p>Mean completed-job duration in milliseconds.</p>
          </div>
          <AnalyticsChart
            :configuration="durationConfig"
            label="Average processing time chart"
          />
        </article>
        <article
          class="surface analytics-card bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] min-w-0 [padding:22px] [&_h2]:m-0 [&_h2]:font-sans [&_h2]:text-title-lg [&_h2]:font-medium [&>div:first-child>p:last-child]:[margin:7px_0_0] [&>div:first-child>p:last-child]:text-muted [&>div:first-child>p:last-child]:text-body"
        >
          <div>
            <p
              class="section-kicker [margin:0_0_8px] text-brand text-caption font-medium [letter-spacing:0.13em] uppercase"
            >
              Knowledge quality
            </p>
            <h2>Quality signals</h2>
            <p>Actionable Wiki lint and duplicate-source indicators.</p>
          </div>
          <AnalyticsChart
            :configuration="knowledgeConfig"
            label="Knowledge quality signals chart"
          />
        </article>
        <article
          class="surface analytics-card bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] min-w-0 [padding:22px] [&_h2]:m-0 [&_h2]:font-sans [&_h2]:text-title-lg [&_h2]:font-medium [&>div:first-child>p:last-child]:[margin:7px_0_0] [&>div:first-child>p:last-child]:text-muted [&>div:first-child>p:last-child]:text-body"
        >
          <div>
            <p
              class="section-kicker [margin:0_0_8px] text-brand text-caption font-medium [letter-spacing:0.13em] uppercase"
            >
              Local traffic
            </p>
            <h2>Most-used routes</h2>
            <p>Content-free request counts for the busiest local endpoints.</p>
          </div>
          <AnalyticsChart
            :configuration="trafficConfig"
            label="Most-used local routes chart"
          />
        </article>
      </div>
    </template>
  </section>
</template>
