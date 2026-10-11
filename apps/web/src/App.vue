<script setup lang="ts">
import { onMounted, onUnmounted } from "vue";

import AppShell from "./components/AppShell.vue";
import { useAuthStore } from "./stores/auth";
import { useSystemStore } from "./stores/system";
import LoginView from "./views/LoginView.vue";

const auth = useAuthStore();
const system = useSystemStore();
const handleUnauthorized = () => {
  auth.user = null;
};

onMounted(() => {
  window.addEventListener("knemora:unauthorized", handleUnauthorized);
  void Promise.all([auth.initialize(), system.initialize()]);
});
onUnmounted(() =>
  window.removeEventListener("knemora:unauthorized", handleUnauthorized),
);
</script>

<template>
  <div
    v-if="!auth.initialized || !system.initialized"
    class="loading-block [padding:40px] text-muted text-center"
  >
    Opening secure workspace…
  </div>
  <AppShell v-else-if="auth.authenticated" />
  <LoginView v-else />
</template>
