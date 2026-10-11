<script setup lang="ts">
import { Eye, EyeOff } from "@lucide/vue";
import { ref } from "vue";

defineOptions({ inheritAttrs: false });
const model = defineModel<string>({ required: true });
const visible = ref(false);
</script>

<template>
  <div
    class="password-input relative flex items-center w-full [height:36px] bg-surface border-0 rounded-control [&_input]:w-full [&_input]:h-full [&_input]:[padding-right:42px] [&_input]:[background:transparent] [&_input]:border [&_input]:border-line [&_input]:rounded-control [&_input]:outline-none [&_button]:absolute [&_button]:[right:8px] [&_button]:grid [&_button]:place-items-center [&_button]:[width:30px] [&_button]:[height:30px] [&_button]:p-0 [&_button]:text-muted [&_button]:[background:transparent] [&_button]:border-0 focus-within:[box-shadow:none] [&:focus-within_input]:border-brand [&:focus-within_input]:[box-shadow:0_0_0_3px_rgb(51_209_51_/_9%)]"
  >
    <input
      v-model="model"
      v-bind="$attrs"
      :type="visible ? 'text' : 'password'"
    />
    <button
      type="button"
      :aria-label="visible ? 'Hide password' : 'Show password'"
      :title="visible ? 'Hide password' : 'Show password'"
      @click="visible = !visible"
    >
      <EyeOff v-if="visible" :size="17" />
      <Eye v-else :size="17" />
    </button>
  </div>
</template>
