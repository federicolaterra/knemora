<script setup lang="ts">
import { Chart, registerables, type ChartConfiguration } from "chart.js";
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = defineProps<{
  configuration: ChartConfiguration;
  label: string;
}>();

Chart.register(...registerables);
Chart.defaults.font.family = "Outfit, ui-sans-serif, sans-serif";

const canvas = ref<HTMLCanvasElement>();
let chart: Chart | undefined;

async function renderChart() {
  await nextTick();
  chart?.destroy();
  if (canvas.value) chart = new Chart(canvas.value, props.configuration);
}

onMounted(renderChart);
watch(() => props.configuration, renderChart, { deep: true });
onBeforeUnmount(() => chart?.destroy());
</script>

<template>
  <div class="relative [height:260px] [margin-top:20px] [&_canvas]:max-w-full">
    <canvas ref="canvas" role="img" :aria-label="label"></canvas>
  </div>
</template>
