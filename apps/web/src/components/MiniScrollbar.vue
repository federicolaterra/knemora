<script setup lang="ts">
import type { PartialOptions } from "overlayscrollbars";
import {
  OverlayScrollbarsComponent,
  type OverlayScrollbarsComponentRef,
} from "overlayscrollbars-vue";
import { ref, useAttrs } from "vue";

type MiniScrollToOptions = {
  top?: number;
  left?: number;
  behavior?: "auto" | "instant" | "smooth";
};

defineOptions({ inheritAttrs: false });

withDefaults(
  defineProps<{
    element?: string;
    horizontal?: boolean;
  }>(),
  {
    element: "div",
    horizontal: false,
  },
);

const attrs = useAttrs();
const scrollbar = ref<OverlayScrollbarsComponentRef | null>(null);
const options: PartialOptions = {
  overflow: { x: "hidden", y: "scroll" },
  scrollbars: {
    theme: "os-theme-knemora",
    visibility: "auto",
    autoHide: "leave",
    autoHideDelay: 500,
    autoHideSuspend: true,
  },
};

function scrollTo(options: MiniScrollToOptions) {
  const instance = scrollbar.value?.osInstance();
  const viewport =
    instance?.elements().viewport ?? scrollbar.value?.getElement();
  viewport?.scrollTo(options);
}

function scrollHeight() {
  const instance = scrollbar.value?.osInstance();
  const viewport =
    instance?.elements().viewport ?? scrollbar.value?.getElement();
  return viewport?.scrollHeight ?? 0;
}

defineExpose({ scrollTo, scrollHeight });
</script>

<template>
  <OverlayScrollbarsComponent
    ref="scrollbar"
    v-bind="attrs"
    :element="element"
    :options="{
      ...options,
      overflow: horizontal
        ? { x: 'scroll', y: 'hidden' }
        : { x: 'hidden', y: 'scroll' },
    }"
    defer
  >
    <slot />
  </OverlayScrollbarsComponent>
</template>
