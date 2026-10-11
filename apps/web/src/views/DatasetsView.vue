<script setup lang="ts">
import { BarChart3, Database, ExternalLink, Play, Table2 } from "@lucide/vue";
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api, openOriginalSource } from "../api/client";
import PageHeader from "../components/PageHeader.vue";
import PaginationControls from "../components/PaginationControls.vue";
import SimpleChart from "../components/SimpleChart.vue";
import { useSystemStore } from "../stores/system";
import type { DatasetResult, DocumentRecord } from "../types";

const system = useSystemStore();
const route = useRoute();
const router = useRouter();
const selectedId = ref(
  typeof route.params.id === "string" ? route.params.id : "",
);
const operation = ref("describe");
const groupBy = ref("");
const valueColumn = ref("");
const metric = ref("average");
const chartType = ref<"bar" | "line">("bar");
const result = ref<DatasetResult | null>(null);
const loading = ref(false);
const error = ref("");
const datasets = ref<DocumentRecord[]>([]);
const selectedDetail = ref<DocumentRecord | null>(null);
const datasetPage = ref(1);
const datasetTotal = ref(0);
const datasetTotalPages = ref(0);
const listLoading = ref(false);
const resultPage = ref(1);
const resultTotalPages = computed(() =>
  Math.max(1, Math.ceil((result.value?.row_count ?? 0) / 15)),
);
const selected = computed(() =>
  selectedDetail.value?.document_version_id === selectedId.value
    ? selectedDetail.value
    : datasets.value.find(
        (item) => item.document_version_id === selectedId.value,
      ),
);

async function loadDatasets(targetPage = datasetPage.value) {
  listLoading.value = true;
  error.value = "";
  try {
    const response = await api.listDatasetPage(targetPage, 5);
    if (response.total && targetPage > response.total_pages) {
      await loadDatasets(response.total_pages);
      return;
    }
    datasets.value = response.items;
    datasetPage.value = response.page;
    datasetTotal.value = response.total;
    datasetTotalPages.value = response.total_pages;
    if (!selectedId.value && response.items.length) {
      selectDataset(response.items[0]);
    }
  } catch (reason) {
    error.value =
      reason instanceof Error ? reason.message : "Unable to load datasets.";
  } finally {
    listLoading.value = false;
  }
}

function selectDataset(dataset: DocumentRecord) {
  selectedId.value = dataset.document_version_id;
  selectedDetail.value = dataset;
  result.value = null;
  void router.replace(`/datasets/${dataset.document_version_id}`);
}

onMounted(async () => {
  await loadDatasets();
  if (selectedId.value && !selected.value) {
    try {
      selectedDetail.value = await api.getDataset(selectedId.value);
    } catch (reason) {
      error.value =
        reason instanceof Error ? reason.message : "Unable to open dataset.";
    }
  }
});

async function analyze(targetPage = 1) {
  if (!selectedId.value) return;
  loading.value = true;
  error.value = "";
  result.value = null;
  try {
    const grouped = groupBy.value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    result.value = await api.analyzeDataset(selectedId.value, {
      operation: operation.value,
      group_by: grouped,
      value_column: valueColumn.value || null,
      metrics: operation.value === "describe" ? [] : [metric.value],
      chart_type: operation.value === "describe" ? null : chartType.value,
      limit: 15,
      offset: (targetPage - 1) * 15,
    });
    resultPage.value = targetPage;
    await router.replace(`/datasets/${selectedId.value}`);
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "Analysis failed.";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <section
    class="page-content [width:min(1380px,_100%)] [margin:0_auto] [padding:36px_clamp(22px,_3.5vw,_52px)_64px] mobile:[padding:27px_16px_45px]"
  >
    <PageHeader
      eyebrow="Deterministic computation"
      title="Datasets"
      description="Analyze structured sources with bounded calculations and column-level provenance."
    />
    <div
      v-if="system.demoActive"
      class="alert flex items-center justify-between [gap:16px] [margin:0_0_20px] [padding:12px_15px] rounded-action text-label [&_button]:[color:inherit] [&_button]:[background:transparent] [&_button]:border-0 [&_button]:font-bold [&_button]:underline"
      role="status"
    >
      Dataset upload and analysis are disabled in the Development demo.
    </div>
    <div
      v-if="!listLoading && !datasetTotal"
      class="surface empty-state bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] grid justify-items-center [min-height:280px] place-content-center [padding:35px] [color:#7c8b86] text-center [&_h3]:[margin:12px_0_5px] [&_h3]:text-ink [&_h3]:font-sans [&_h3]:text-title-lg [&_h3]:font-medium [&_p]:[max-width:430px] [&_p]:[margin:0_0_18px] [&_p]:text-label [&_p]:[line-height:1.55]"
    >
      <Database :size="36" />
      <h3>No datasets yet</h3>
      <p>Upload a CSV or XLSX source to begin.</p>
      <RouterLink
        v-if="!system.demoActive"
        class="button button-primary inline-flex [gap:8px] items-center justify-center [min-height:38px] [padding:0_15px] [border:1px_solid_transparent] rounded-action text-label font-bold no-underline [transition:0.16s_ease] text-white bg-brand [box-shadow:0_2px_7px_rgb(51_209_51_/_18%)] hover:text-white hover:bg-brand hover:[opacity:0.82] hover:[transform:translateY(-1px)]"
        to="/documents"
        >Upload dataset</RouterLink
      >
    </div>
    <div
      v-else
      class="grid [grid-template-columns:230px_minmax(0,_1fr)] [gap:14px] mobile:[grid-template-columns:1fr]"
    >
      <aside
        class="surface bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] [&_h2]:m-0 [&_h2]:font-sans [&_h2]:text-title [&_h2]:font-medium self-start [padding:16px] [&_h2]:[margin-bottom:13px] [&_h2]:text-lead [&_button]:flex [&_button]:[gap:9px] [&_button]:items-center [&_button]:w-full [&_button]:[padding:10px] [&_button]:[color:#53655f] [&_button]:[background:transparent] [&_button]:border-0 [&_button]:rounded-control [&_button]:text-left [&_button:hover]:text-brand [&_button:hover]:bg-brand-pale [&_button.active]:text-brand [&_button.active]:bg-brand-pale [&_button>span]:grid [&_button>span]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-control [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_small]:[margin-top:3px] [&_small]:text-muted [&_small]:text-control mobile:flex mobile:[gap:8px] mobile:overflow-x-auto mobile:[&_h2]:hidden mobile:[&_button]:[min-width:190px]"
      >
        <h2>Available datasets</h2>
        <button
          v-for="dataset in datasets"
          :key="dataset.document_version_id"
          type="button"
          :class="{ active: selectedId === dataset.document_version_id }"
          @click="selectDataset(dataset)"
        >
          <Database :size="17" /><span
            ><strong>{{ dataset.original_filename }}</strong
            ><small>{{ (dataset.byte_size / 1024).toFixed(1) }} KB</small></span
          >
        </button>
        <PaginationControls
          :page="datasetPage"
          :page-limit="5"
          :total="datasetTotal"
          :total-pages="datasetTotalPages"
          :loading="listLoading"
          @change="loadDatasets"
        />
      </aside>
      <main class="grid [gap:14px] min-w-0">
        <section
          class="surface bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] [padding:22px] [&_h2]:m-0 [&_h2]:font-sans [&_h2]:text-title [&_h2]:font-medium"
        >
          <div
            class="section-heading flex items-center justify-between items-start [gap:16px] [&_h2]:m-0 [&_h2]:font-sans [&_h2]:text-title [&_h2]:font-medium [&_a]:flex [&_a]:[gap:5px] [&_a]:items-center [&_a]:text-brand [&_a]:text-control [&_a]:font-bold [&_a]:no-underline"
          >
            <div>
              <p
                class="section-kicker [margin:0_0_8px] text-brand text-caption font-medium [letter-spacing:0.13em] uppercase"
              >
                Analysis prompt
              </p>
              <h2>{{ selected?.original_filename || "Choose a dataset" }}</h2>
            </div>
          </div>
          <div
            class="form-grid [&_input]:h-9 [&_input]:rounded-[7px] [&_input]:border [&_input]:border-line [&_input]:bg-white [&_input]:py-0 [&_input]:pl-[10px] [&_input]:pr-[30px] [&_input]:text-label [&_input]:outline-none [&_input:focus]:border-brand [&_input:focus]:shadow-[0_0_0_3px_rgba(51,209,51,0.09)] grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:11px] [margin:18px_0] [&_label]:grid [&_label]:[gap:6px] [&_label]:[color:#55665f] [&_label]:text-label [&_label]:font-semibold [&_select]:w-full [&_input]:w-full mobile:[grid-template-columns:1fr]"
          >
            <label
              >Operation<select
                class="h-9 rounded-[7px] border border-line bg-white py-0 pl-[10px] pr-[30px] text-label outline-none focus:border-brand focus:shadow-[0_0_0_3px_rgba(51,209,51,0.09)]"
                v-model="operation"
              >
                <option value="describe">Descriptive statistics</option>
                <option value="aggregate">Aggregate</option>
                <option value="trend">Trend</option>
                <option value="comparison">Comparison</option>
                <option value="top">Top values</option>
                <option value="bottom">Bottom values</option>
              </select></label
            ><label
              >Group by columns<input
                v-model="groupBy"
                placeholder="e.g. region, month"
                :disabled="operation === 'describe'" /></label
            ><label
              >Value column<input
                v-model="valueColumn"
                placeholder="e.g. revenue"
                :disabled="operation === 'describe'" /></label
            ><label
              >Metric<select
                class="h-9 rounded-[7px] border border-line bg-white py-0 pl-[10px] pr-[30px] text-label outline-none focus:border-brand focus:shadow-[0_0_0_3px_rgba(51,209,51,0.09)]"
                v-model="metric"
                :disabled="operation === 'describe'"
              >
                <option value="sum">Sum</option>
                <option value="average">Average</option>
                <option value="median">Median</option>
                <option value="count">Count</option>
              </select></label
            ><label
              >Chart<select
                class="h-9 rounded-[7px] border border-line bg-white py-0 pl-[10px] pr-[30px] text-label outline-none focus:border-brand focus:shadow-[0_0_0_3px_rgba(51,209,51,0.09)]"
                v-model="chartType"
                :disabled="operation === 'describe'"
              >
                <option value="bar">Bar chart</option>
                <option value="line">Line chart</option>
              </select></label
            >
          </div>
          <button
            class="button button-primary inline-flex [gap:8px] items-center justify-center [min-height:38px] [padding:0_15px] [border:1px_solid_transparent] rounded-action text-label font-bold no-underline [transition:0.16s_ease] text-white bg-brand [box-shadow:0_2px_7px_rgb(51_209_51_/_18%)] hover:text-white hover:bg-brand hover:[opacity:0.82] hover:[transform:translateY(-1px)]"
            type="button"
            :disabled="system.demoActive || !selectedId || loading"
            @click="analyze()"
          >
            <Play :size="15" /> {{ loading ? "Analyzing…" : "Run analysis" }}
          </button>
          <p
            class="form-hint [margin:10px_0_0] text-muted text-label [line-height:1.45]"
          >
            Column names must match the source exactly. Computation uses
            allow-listed operations—no generated code or SQL.
          </p>
        </section>
        <div
          v-if="error"
          class="alert alert-danger flex items-center justify-between [gap:16px] [margin:0_0_20px] [padding:12px_15px] rounded-action text-label [&_button]:[color:inherit] [&_button]:[background:transparent] [&_button]:border-0 [&_button]:font-bold [&_button]:underline [color:#7b3525] [background:#fbece6] [border:1px_solid_#efc8bc]"
        >
          {{ error }}
        </div>
        <template v-if="result"
          ><section
            v-if="result.chart"
            class="surface result-card bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] [padding:22px] [&_h2]:m-0 [&_h2]:font-sans [&_h2]:text-title [&_h2]:font-medium [&_.section-heading]:[margin-bottom:16px]"
          >
            <div
              class="section-heading flex items-center justify-between items-start [gap:16px] [&_h2]:m-0 [&_h2]:font-sans [&_h2]:text-title [&_h2]:font-medium [&_a]:flex [&_a]:[gap:5px] [&_a]:items-center [&_a]:text-brand [&_a]:text-control [&_a]:font-bold [&_a]:no-underline"
            >
              <div>
                <p
                  class="section-kicker [margin:0_0_8px] text-brand text-caption font-medium [letter-spacing:0.13em] uppercase"
                >
                  Visualization
                </p>
                <h2>Chart result</h2>
              </div>
              <BarChart3 :size="20" />
            </div>
            <SimpleChart :chart="result.chart" />
          </section>
          <section
            class="surface result-card bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] [padding:22px] [&_h2]:m-0 [&_h2]:font-sans [&_h2]:text-title [&_h2]:font-medium [&_.section-heading]:[margin-bottom:16px]"
          >
            <div
              class="section-heading flex items-center justify-between items-start [gap:16px] [&_h2]:m-0 [&_h2]:font-sans [&_h2]:text-title [&_h2]:font-medium [&_a]:flex [&_a]:[gap:5px] [&_a]:items-center [&_a]:text-brand [&_a]:text-control [&_a]:font-bold [&_a]:no-underline"
            >
              <div>
                <p
                  class="section-kicker [margin:0_0_8px] text-brand text-caption font-medium [letter-spacing:0.13em] uppercase"
                >
                  Result table
                </p>
                <h2>{{ result.row_count }} rows</h2>
              </div>
              <Table2 :size="20" />
            </div>
            <div
              class="responsive-table [&_table]:w-full [&_table]:border-collapse [&_table]:text-left [&_table]:text-label [&_th]:border-y [&_th]:border-[#e4e8e5] [&_th]:bg-[#f6f8f6] [&_th]:px-[10px] [&_th]:py-[11px] [&_th]:text-[9px] [&_th]:uppercase [&_th]:tracking-[0.08em] [&_th]:text-[#74817d] [&_td]:border-b [&_td]:border-[#edf0ee] [&_td]:px-[10px] [&_td]:py-[13px] [&_td]:align-middle [&_td]:text-label [&_td_code]:text-label [&_td_strong]:block [&_td_strong]:text-label [&_td_small]:block [&_td_small]:mt-1 [&_td_small]:text-label [&_td_small]:text-muted overflow-x-auto"
            >
              <table>
                <thead>
                  <tr>
                    <th v-for="column in result.columns" :key="column">
                      {{ column }}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, index) in result.rows" :key="index">
                    <td v-for="column in result.columns" :key="column">
                      {{ row[column] }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <PaginationControls
              :page="resultPage"
              :total="result.row_count"
              :total-pages="resultTotalPages"
              :loading="loading"
              @change="analyze"
            />
            <p
              v-if="result.truncated"
              class="form-hint [margin:10px_0_0] text-muted text-meta [line-height:1.45]"
            >
              Showing 15 rows per page from the server-side result set.
            </p>
          </section>
          <section
            class="surface bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] [padding:22px] [&_h2]:m-0 [&_h2]:font-sans [&_h2]:text-title [&_h2]:font-medium [&_dl]:grid [&_dl]:[grid-template-columns:repeat(2,_1fr)] [&_dl]:[gap:10px] [&_dl>div]:min-w-0 [&_dl>div]:[padding:10px] [&_dl>div]:[background:#f7f8f6] [&_dl>div]:[border-radius:6px] [&_dt]:text-muted [&_dt]:text-caption [&_dt]:uppercase [&_dd]:[margin:5px_0_0] [&_dd]:overflow-auto [&_dd]:text-caption [&_a]:text-brand [&_a]:text-caption [&_a]:font-bold phone:[&_dl]:[grid-template-columns:1fr]"
          >
            <p
              class="section-kicker [margin:0_0_8px] text-brand text-caption font-medium [letter-spacing:0.13em] uppercase"
            >
              Analysis provenance
            </p>
            <h2>{{ result.provenance.original_filename }}</h2>
            <dl>
              <div>
                <dt>Source rows</dt>
                <dd>{{ result.provenance.source_row_count }}</dd>
              </div>
              <div>
                <dt>Filtered rows</dt>
                <dd>{{ result.provenance.filtered_row_count }}</dd>
              </div>
              <div>
                <dt>Columns used</dt>
                <dd>{{ result.provenance.source_columns.join(", ") }}</dd>
              </div>
              <div>
                <dt>Sheet</dt>
                <dd>{{ result.provenance.sheet || "CSV" }}</dd>
              </div>
              <div>
                <dt>Checksum</dt>
                <dd>
                  <code>{{ result.provenance.sha256 }}</code>
                </dd>
              </div>
            </dl>
            <button
              v-if="selected"
              class="mt-5 inline-flex items-center gap-2 border-0 bg-transparent p-0 text-label font-semibold text-brand"
              type="button"
              @click="openOriginalSource(selected.original_url)"
            >
              Open immutable original <ExternalLink :size="14" />
            </button></section
        ></template>
      </main>
    </div>
  </section>
</template>
