import { defineStore } from "pinia";

import { api } from "../api/client";
import type { Conversation, DocumentRecord, PageSummary } from "../types";
import { useAuthStore } from "./auth";

export const useWorkspaceStore = defineStore("workspace", {
  state: () => ({
    documents: [] as DocumentRecord[],
    pages: [] as PageSummary[],
    conversations: [] as Conversation[],
    documentTotal: 0,
    pageTotal: 0,
    conversationTotal: 0,
    datasetTotal: 0,
    loading: false,
    error: "",
  }),
  getters: {
    datasets: (state) =>
      state.documents.filter((document) => document.is_dataset),
    completedDocuments: (state) =>
      state.documents.filter(
        (document) => document.compilation_status === "COMPLETED",
      ),
  },
  actions: {
    async refresh() {
      this.loading = true;
      this.error = "";
      try {
        const auth = useAuthStore();
        const emptyPage = <T>() => ({
          items: [] as T[],
          page: 1,
          page_limit: 1,
          total: 0,
          total_pages: 0,
        });
        const [documents, pages, conversations, datasets] = await Promise.all([
          auth.can("document.read")
            ? api.listDocumentPage(1, 5)
            : Promise.resolve(emptyPage<DocumentRecord>()),
          auth.can("knowledge.read")
            ? api.listWikiPageIndex(1, 8)
            : Promise.resolve(emptyPage<PageSummary>()),
          auth.can("chat.use")
            ? api.listConversationPage(1, 8)
            : Promise.resolve(emptyPage<Conversation>()),
          auth.can("dataset.analyze")
            ? api.listDatasetPage(1, 5)
            : Promise.resolve(emptyPage<DocumentRecord>()),
        ]);
        this.documents = documents.items;
        this.pages = pages.items;
        this.conversations = conversations.items;
        this.documentTotal = documents.total;
        this.pageTotal = pages.total;
        this.conversationTotal = conversations.total;
        this.datasetTotal = datasets.total;
      } catch (error) {
        this.error =
          error instanceof Error
            ? error.message
            : "Unable to load the workspace.";
      } finally {
        this.loading = false;
      }
    },
  },
});
