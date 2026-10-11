<script setup lang="ts">
defineProps<{ eyebrow?: string; title: string; description: string }>();
</script>

<template>
  <header
    class="page-header flex items-center justify-between [align-items:flex-end] [gap:24px] [margin-bottom:30px] [&_h1]:m-0 [&_h1]:[font-size:2rem] [&_h1]:font-medium [&_h1]:[letter-spacing:-0.035em] [&_h1]:[line-height:1.05] [&>div>p:last-child]:[max-width:660px] [&>div>p:last-child]:[margin:10px_0_0] [&>div>p:last-child]:text-muted [&>div>p:last-child]:text-body [&>div>p:last-child]:[line-height:1.55] mobile:items-start mobile:flex-col mobile:[margin-bottom:23px]"
  >
    <div>
      <p
        v-if="eyebrow"
        class="[margin:0_0_8px] text-brand text-caption font-medium [letter-spacing:0.13em] uppercase"
      >
        {{ eyebrow }}
      </p>
      <h1>{{ title }}</h1>
      <p>{{ description }}</p>
    </div>
    <div
      v-if="$slots.actions"
      class="flex [gap:10px] mobile:w-full mobile:[&_.button]:w-full"
    >
      <slot name="actions" />
    </div>
  </header>
</template>
