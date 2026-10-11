<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ status: string | null | undefined }>();
const normalized = computed(
  () => props.status?.toLowerCase().replaceAll("_", " ") ?? "not started",
);
const tone = computed(() => {
  if (
    ["completed", "ready for compilation", "supported"].includes(
      normalized.value,
    )
  )
    return "success";
  if (["failed", "disputed"].includes(normalized.value)) return "danger";
  if (["not started", "queued"].includes(normalized.value)) return "neutral";
  return "active";
});
const toneClasses: Record<string, string> = {
  success: "bg-brand-pale text-brand [&>span]:bg-brand",
  danger: "bg-[#fae8e2] text-[#963e2b] [&>span]:bg-[#c45237]",
  active: "bg-[#f8f0db] text-[#775928] [&>span]:bg-[#c39031]",
  neutral: "bg-[#ecefed] text-[#64716d] [&>span]:bg-[#85918d]",
};
</script>

<template>
  <span
    class="status-badge inline-flex items-center gap-[6px] whitespace-nowrap rounded-[99px] px-[7px] py-[4px] text-control font-bold uppercase tracking-[0.04em]"
    :class="toneClasses[tone]"
  >
    <span class="h-[5px] w-[5px] rounded-full"></span>{{ normalized }}
  </span>
</template>
