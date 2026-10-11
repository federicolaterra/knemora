<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    page: number;
    total: number;
    totalPages: number;
    loading?: boolean;
    pageLimit?: number;
  }>(),
  { pageLimit: 15 },
);

defineEmits<{ change: [page: number] }>();

const pages = computed(() => {
  const start = Math.floor((Math.max(props.page, 1) - 1) / 5) * 5 + 1;
  const end = Math.min(start + 4, props.totalPages);
  return Array.from(
    { length: Math.max(0, end - start + 1) },
    (_, index) => start + index,
  );
});
const firstRecord = computed(() => (props.page - 1) * props.pageLimit + 1);
const lastRecord = computed(() =>
  Math.min(props.page * props.pageLimit, props.total),
);
</script>

<template>
  <div
    v-if="totalPages > 1"
    class="pagination flex flex-wrap items-center justify-between [gap:12px] [min-height:48px] [padding:12px_10px_0] [border-top:1px_solid_#edf0ee] [&_p]:m-0 [&_p]:text-muted [&_p]:text-label [&_p_strong]:text-ink [&>div]:flex [&>div]:flex-wrap [&>div]:[gap:6px] [&_button]:grid [&_button]:place-items-center [&_button]:[width:28px] [&_button]:[height:28px] [&_button]:[color:#30443a] [&_button]:bg-surface [&_button]:border [&_button]:border-line [&_button]:rounded-control [&_button]:text-label [&_button.active]:text-white [&_button.active]:bg-brand [&_button.active]:border-brand [&_button.active]:font-semibold [&_button.active]:opacity-100 [&_button:not(:disabled):not(.active):hover]:text-brand [&_button:not(:disabled):not(.active):hover]:bg-brand-pale [&_button:not(:disabled):not(.active):hover]:border-brand mobile:items-start"
    aria-label="Pagination"
  >
    <div class="">
      <button
        type="button"
        class="!w-auto px-2"
        aria-label="Go to previous page"
        :disabled="loading || page <= 1"
        @click="$emit('change', page - 1)"
      >
        Prev
      </button>
      <button
        v-for="pageNumber in pages"
        :key="pageNumber"
        type="button"
        :aria-label="`Go to page ${pageNumber}`"
        :aria-current="pageNumber === page ? 'page' : undefined"
        :class="{ active: pageNumber === page }"
        :disabled="loading || pageNumber === page"
        @click="$emit('change', pageNumber)"
      >
        {{ pageNumber }}
      </button>
      <button
        type="button"
        class="!w-auto px-2"
        aria-label="Go to next page"
        :disabled="loading || page >= totalPages"
        @click="$emit('change', page + 1)"
      >
        Next
      </button>
    </div>
    <p>{{ firstRecord }}–{{ lastRecord }} of {{ total }} records</p>
  </div>
</template>
