<script setup lang="ts">
import { Construction } from "@lucide/vue";

import PageHeader from "../components/PageHeader.vue";

defineProps<{ title: string; description: string }>();
</script>

<template>
  <section
    class="page-content [width:min(1380px,_100%)] [margin:0_auto] [padding:36px_clamp(22px,_3.5vw,_52px)_64px] mobile:[padding:27px_16px_45px]"
  >
    <PageHeader
      eyebrow="Product shell"
      :title="title"
      :description="description"
    />
    <div
      class="surface empty-state bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] grid justify-items-center [min-height:280px] place-content-center [padding:35px] [color:#7c8b86] text-center [&_h3]:[margin:12px_0_5px] [&_h3]:text-ink [&_h3]:font-sans [&_h3]:text-title-lg [&_h3]:font-medium [&_p]:[max-width:430px] [&_p]:[margin:0_0_18px] [&_p]:text-label [&_p]:[line-height:1.55]"
    >
      <Construction :size="36" />
      <h3>Workspace unavailable</h3>
      <p>
        This workspace is not enabled in the current local release
        configuration.
      </p>
    </div>
  </section>
</template>
