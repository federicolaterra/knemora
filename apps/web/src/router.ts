import { createRouter, createWebHistory } from "vue-router";

import ChatView from "./views/ChatView.vue";
import ConversationsView from "./views/ConversationsView.vue";
import AdministrationView from "./views/AdministrationView.vue";
import DatasetsView from "./views/DatasetsView.vue";
import DocumentsView from "./views/DocumentsView.vue";
import IngestionView from "./views/IngestionView.vue";
import KnowledgeView from "./views/KnowledgeView.vue";
import ObservabilityView from "./views/ObservabilityView.vue";
import OverviewView from "./views/OverviewView.vue";
import ProfileView from "./views/ProfileView.vue";
import SecondBrainView from "./views/SecondBrainView.vue";
import WikiMarkdownView from "./views/WikiMarkdownView.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "overview", component: OverviewView },
    { path: "/profile", name: "profile", component: ProfileView },
    {
      path: "/chat/conversations",
      name: "conversations",
      component: ConversationsView,
    },
    { path: "/chat/:id?", name: "chat", component: ChatView },
    { path: "/conversations", redirect: "/chat/conversations" },
    { path: "/documents", name: "documents", component: DocumentsView },
    { path: "/ingestion", name: "ingestion", component: IngestionView },
    { path: "/second-brain", name: "second-brain", component: SecondBrainView },
    {
      path: "/knowledge/file/:pathMatch(.*)",
      name: "wiki-markdown",
      component: WikiMarkdownView,
    },
    { path: "/knowledge/:id?", name: "knowledge", component: KnowledgeView },
    { path: "/datasets/:id?", name: "datasets", component: DatasetsView },
    {
      path: "/analytics",
      name: "analytics",
      component: ObservabilityView,
    },
    {
      path: "/audit-logs",
      name: "audit-logs",
      component: AdministrationView,
      props: {
        kind: "audit",
        title: "Audit logs",
        description: "Review traceable operations across your workspace.",
      },
    },
  ],
});
