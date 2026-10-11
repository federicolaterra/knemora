<script setup lang="ts">
import { FileUp, LoaderCircle, UploadCloud, X } from "@lucide/vue";
import { ref } from "vue";

import { api } from "../api/client";

const emit = defineEmits<{ complete: [] }>();
const input = ref<HTMLInputElement>();
const dragging = ref(false);
const queue = ref<
  Array<{
    file: File;
    state: "queued" | "uploading" | "complete" | "error";
    error?: string;
  }>
>([]);

const accepted = [".pdf", ".txt", ".md", ".docx", ".csv", ".xlsx"];

function addFiles(files: FileList | File[]) {
  const additions = Array.from(files).map((file) => {
    const extension = `.${file.name.split(".").pop()?.toLowerCase()}`;
    if (!accepted.includes(extension))
      return { file, state: "error" as const, error: "Unsupported file type" };
    if (file.size > 25 * 1024 * 1024)
      return { file, state: "error" as const, error: "File exceeds 25 MB" };
    return { file, state: "queued" as const };
  });
  queue.value.push(...additions);
}

async function uploadAll() {
  for (const item of queue.value.filter((entry) => entry.state === "queued")) {
    item.state = "uploading";
    try {
      const result = await api.uploadDocument(item.file);
      await api.compileDocument(result.document_version_id);
      item.state = "complete";
    } catch (error) {
      item.state = "error";
      item.error = error instanceof Error ? error.message : "Upload failed";
    }
  }
  emit("complete");
}

function drop(event: DragEvent) {
  dragging.value = false;
  if (event.dataTransfer?.files) addFiles(event.dataTransfer.files);
}
</script>

<template>
  <div class="grid [margin-bottom:20px]">
    <div
      class="grid justify-items-center [padding:29px_20px] bg-white [border:1px_dashed_#a9bbb4] rounded-panel [transition:0.15s_ease] hover:[background:#f6f8f6] [&.dragging]:bg-brand-pale [&.dragging]:border-brand [&.dragging]:[transform:scale(0.997)] [&_h3]:[margin:13px_0_4px] [&_h3]:font-sans [&_h3]:[font-size:17px] [&_h3]:font-medium [&_p]:[margin:0_0_14px] [&_p]:text-muted [&_p]:text-label"
      :class="{ dragging }"
      @dragenter.prevent="dragging = true"
      @dragover.prevent
      @dragleave.prevent="dragging = false"
      @drop.prevent="drop"
    >
      <span
        class="grid place-items-center [width:49px] [height:49px] text-brand bg-brand-pale [border-radius:13px]"
        ><UploadCloud :size="28"
      /></span>
      <h3>Drop source files here</h3>
      <p>PDF, TXT, Markdown, DOCX, CSV, or XLSX · up to 25 MB each</p>
      <button
        type="button"
        class="button button-primary inline-flex [gap:8px] items-center justify-center [min-height:38px] [padding:0_15px] [border:1px_solid_transparent] rounded-action text-label font-bold no-underline [transition:0.16s_ease] text-white bg-brand [box-shadow:0_2px_7px_rgb(51_209_51_/_18%)] hover:text-white hover:bg-brand hover:[opacity:0.82] hover:[transform:translateY(-1px)]"
        @click="input?.click()"
      >
        <FileUp :size="16" /> Choose files
      </button>
      <input
        ref="input"
        class="sr-only absolute [width:1px] [height:1px] p-0 [margin:-1px] overflow-hidden [clip:rect(0,_0,_0,_0)] whitespace-nowrap border-0"
        type="file"
        multiple
        accept=".pdf,.txt,.md,.docx,.csv,.xlsx"
        @change="addFiles(($event.target as HTMLInputElement).files ?? [])"
      />
    </div>
    <ul
      v-if="queue.length"
      class="[margin:16px_0_0] p-0 [list-style:none] [padding:8px_12px] bg-surface border border-line [border-top:0] [border-radius:0_0_10px_10px] [&_li]:flex [&_li]:[gap:11px] [&_li]:items-center [&_li]:[padding:8px_4px] [&_li]:[border-bottom:1px_solid_#edf0ee] [&_li:last-child]:border-0 [&_li>div]:flex-1 [&_strong]:block [&_strong]:text-label [&_small]:block [&_small]:text-label [&_small]:[margin-top:2px] [&_small]:text-muted [&_small]:capitalize [&_button]:[background:transparent] [&_button]:border-0"
      aria-live="polite"
    >
      <li v-for="(item, index) in queue" :key="`${item.file.name}-${index}`">
        <FileUp :size="18" />
        <div>
          <strong>{{ item.file.name }}</strong
          ><small :class="{ 'text-danger': item.state === 'error' }">{{
            item.error ?? item.state
          }}</small>
        </div>
        <LoaderCircle
          v-if="item.state === 'uploading'"
          class="animate-spin-fast"
          :size="18"
        />
        <button
          v-else-if="item.state !== 'complete'"
          type="button"
          aria-label="Remove file"
          @click="queue.splice(index, 1)"
        >
          <X :size="16" />
        </button>
        <span v-else class="text-brand text-caption font-bold">Done</span>
      </li>
    </ul>
    <button
      v-if="queue.some((item) => item.state === 'queued')"
      type="button"
      class="button button-primary inline-flex [gap:8px] items-center justify-center [min-height:38px] [padding:0_15px] [border:1px_solid_transparent] rounded-action text-label font-bold no-underline [transition:0.16s_ease] text-white bg-brand [box-shadow:0_2px_7px_rgb(51_209_51_/_18%)] hover:text-white hover:bg-brand hover:[opacity:0.82] hover:[transform:translateY(-1px)] justify-self-end [margin-top:10px]"
      @click="uploadAll"
    >
      Upload &amp; build knowledge
    </button>
  </div>
</template>
