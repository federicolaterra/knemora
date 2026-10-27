<script setup lang="ts">
import { CircleQuestionMark, X } from "@lucide/vue";
import { useId } from "vue";

const props = withDefaults(
  defineProps<{
    title: string;
    description: string;
    confirmLabel?: string;
    busyLabel?: string;
    busy?: boolean;
    tone?: "danger" | "warning";
    closeLabel?: string;
  }>(),
  {
    confirmLabel: "Confirm",
    busyLabel: "Working…",
    busy: false,
    tone: "danger",
    closeLabel: "Close confirmation",
  },
);

const emit = defineEmits<{
  close: [];
  confirm: [];
}>();

const titleId = `confirm-action-title-${useId()}`;
const descriptionId = `confirm-action-description-${useId()}`;

function close() {
  if (!props.busy) emit("close");
}
</script>

<template>
  <div
    class="fixed inset-0 z-[100] grid place-items-center bg-[rgb(12_25_20_/_48%)] p-5 [backdrop-filter:blur(3px)]"
    role="presentation"
    @click.self="close"
  >
    <section
      class="relative w-[min(100%,_460px)] rounded-[14px] border border-line bg-surface p-[30px] [box-shadow:0_24px_70px_rgb(15_32_25_/_24%)] [&_h2]:mb-2 [&_h2]:mt-5 [&_h2]:text-[22px] [&_h2]:font-medium [&_p]:m-0 [&_p]:text-detail [&_p]:leading-[1.55] [&_p]:text-muted"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="titleId"
      :aria-describedby="descriptionId"
      @keydown.esc="close"
    >
      <button
        class="absolute right-[14px] top-[14px] grid h-8 w-8 place-items-center rounded-control border-0 bg-transparent text-muted hover:!translate-y-0 hover:bg-[#f2f4f2]"
        type="button"
        :aria-label="closeLabel"
        :disabled="busy"
        @click="close"
      >
        <X :size="18" />
      </button>
      <span
        class="grid h-[46px] w-[46px] place-items-center rounded-panel"
        :class="
          tone === 'warning'
            ? 'bg-[#fff2ec] text-[#F4A440]'
            : 'bg-[#fbece6] text-danger'
        "
      >
        <CircleQuestionMark :size="23" />
      </span>
      <h2 :id="titleId">{{ title }}</h2>
      <p :id="descriptionId">{{ description }}</p>
      <div class="mt-[26px] flex justify-end">
        <button
          class="button inline-flex min-h-[38px] items-center justify-center gap-2 rounded-action border px-[15px] text-label font-bold text-white no-underline transition-[opacity] hover:!translate-y-0 hover:opacity-85"
          :class="
            tone === 'warning'
              ? 'border-[#F4A440] bg-[#F4A440]'
              : 'border-danger bg-danger'
          "
          type="button"
          :disabled="busy"
          autofocus
          @click="emit('confirm')"
        >
          <slot name="confirm-icon" />
          {{ busy ? busyLabel : confirmLabel }}
        </button>
      </div>
    </section>
  </div>
</template>
