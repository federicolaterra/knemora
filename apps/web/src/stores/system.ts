import { defineStore } from "pinia";

import { api } from "../api/client";

export const useSystemStore = defineStore("system", {
  state: () => ({
    name: "Knemora",
    edition: "community",
    description:
      "Open-source, local-first knowledge and agent platform with a native Second Brain graph, a portable Markdown wiki, and local AI inference.",
    capabilities: [] as string[],
    demoActive: false,
    demoPreset: null as string | null,
    demoTopic: null as string | null,
    defaultLoginEmail: "admin@knemora.local",
    initialized: false,
  }),
  getters: {
    hasCapability: (state) => (capability: string) =>
      state.capabilities.includes(capability),
  },
  actions: {
    async initialize() {
      try {
        const metadata = await api.readSystem();
        this.name = metadata.product.name;
        this.edition = metadata.product.edition;
        this.description = metadata.product.description;
        this.capabilities = metadata.capabilities;
        this.demoActive = metadata.demo.active;
        this.demoPreset = metadata.demo.preset;
        this.demoTopic = metadata.demo.topic;
        this.defaultLoginEmail = metadata.authentication.default_email;
        document.title = metadata.product.name;
      } catch {
        // Keep safe, local product defaults if metadata is temporarily unavailable.
      } finally {
        this.initialized = true;
      }
    },
  },
});
