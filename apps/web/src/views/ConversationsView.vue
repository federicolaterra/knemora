<script setup lang="ts">
import { ArrowLeft, Check, Eye, Pencil, Search, Trash2, X } from "@lucide/vue";
import { nextTick, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "../api/client";
import PageHeader from "../components/PageHeader.vue";
import PaginationControls from "../components/PaginationControls.vue";
import { useWorkspaceStore } from "../stores/workspace";
import type { Conversation } from "../types";

const route = useRoute();
const router = useRouter();
const workspace = useWorkspaceStore();
const conversations = ref<Conversation[]>([]);
const query = ref(typeof route.query.q === "string" ? route.query.q : "");
const page = ref(Math.max(1, Number(route.query.page) || 1));
const total = ref(0);
const totalPages = ref(0);
const loading = ref(false);
const deleting = ref("");
const editingId = ref("");
const editTitle = ref("");
const renaming = ref(false);
const renameError = ref("");
const error = ref("");
let searchTimer: ReturnType<typeof setTimeout> | undefined;
let requestSequence = 0;

async function loadPage(targetPage = page.value) {
  const request = ++requestSequence;
  loading.value = true;
  error.value = "";
  try {
    const response = await api.listConversationPage(
      targetPage,
      15,
      query.value.trim(),
    );
    if (request !== requestSequence) return;
    if (response.total && targetPage > response.total_pages) {
      await loadPage(response.total_pages);
      return;
    }
    conversations.value = response.items;
    page.value = response.page;
    total.value = response.total;
    totalPages.value = response.total_pages;
    await router.replace({
      query: {
        ...(query.value.trim() ? { q: query.value.trim() } : {}),
        ...(response.page > 1 ? { page: String(response.page) } : {}),
      },
    });
  } catch (reason) {
    if (request !== requestSequence) return;
    error.value =
      reason instanceof Error
        ? reason.message
        : "Unable to load conversations.";
  } finally {
    if (request === requestSequence) loading.value = false;
  }
}

watch(
  query,
  () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => void loadPage(1), 300);
  },
  { immediate: true },
);
onBeforeUnmount(() => clearTimeout(searchTimer));

async function beginRename(conversation: Conversation) {
  editingId.value = conversation.id;
  editTitle.value = conversation.title || "Untitled conversation";
  renameError.value = "";
  await nextTick();
  const input = document.querySelector<HTMLInputElement>(
    `[data-history-rename-id="${conversation.id}"]`,
  );
  input?.focus();
  input?.select();
}

function cancelRename() {
  editingId.value = "";
  editTitle.value = "";
  renameError.value = "";
}

async function saveRename(conversation: Conversation) {
  if (renaming.value) return;
  renaming.value = true;
  renameError.value = "";
  try {
    const renamed = await api.renameConversation(
      conversation.id,
      editTitle.value,
    );
    const pageIndex = conversations.value.findIndex(
      (item) => item.id === renamed.id,
    );
    if (pageIndex >= 0)
      conversations.value[pageIndex] = {
        ...conversations.value[pageIndex],
        ...renamed,
      };
    const recentIndex = workspace.conversations.findIndex(
      (item) => item.id === renamed.id,
    );
    if (recentIndex >= 0)
      workspace.conversations[recentIndex] = {
        ...workspace.conversations[recentIndex],
        ...renamed,
      };
    cancelRename();
  } catch (reason) {
    renameError.value =
      reason instanceof Error
        ? reason.message
        : "Unable to rename the conversation.";
  } finally {
    renaming.value = false;
  }
}

async function deleteConversation(conversation: Conversation) {
  if (
    !window.confirm(
      `Delete “${conversation.title || "Untitled conversation"}” and all its messages?`,
    )
  )
    return;
  deleting.value = conversation.id;
  error.value = "";
  try {
    await api.deleteConversation(conversation.id);
    await workspace.refresh();
    await loadPage(
      conversations.value.length === 1
        ? Math.max(1, page.value - 1)
        : page.value,
    );
  } catch (reason) {
    error.value =
      reason instanceof Error
        ? reason.message
        : "Unable to delete the conversation.";
  } finally {
    deleting.value = "";
  }
}

function formatDate(value?: string | null) {
  return value
    ? new Date(value).toLocaleString("en", {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : "Unavailable";
}
</script>

<template>
  <section
    class="page-content [width:min(1380px,_100%)] [margin:0_auto] [padding:36px_clamp(22px,_3.5vw,_52px)_64px] mobile:[padding:27px_16px_45px]"
  >
    <PageHeader
      eyebrow="AI Chat"
      title="All Conversations"
      description="Search and manage your complete owner-scoped conversation history."
    >
      <template #actions
        ><RouterLink
          class="inline-flex items-center gap-2 text-brand no-underline"
          to="/chat"
          ><ArrowLeft :size="16" /> Back to AI Chat</RouterLink
        ></template
      >
    </PageHeader>
    <section
      class="surface table-surface rounded-panel border border-line bg-surface p-[22px] [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)]"
    >
      <div
        class="mb-4 flex items-end justify-between gap-4 mobile:items-stretch mobile:flex-col"
      >
        <div>
          <h2 class="m-0 font-sans text-title font-medium">
            Conversation history
          </h2>
          <p class="mb-0 mt-1 text-label text-muted">
            {{ total }} conversations · 15 per page
          </p>
        </div>
        <label
          class="search-field flex min-h-9 items-center gap-2 rounded-control border border-line bg-[#f8f9f7] px-2 focus-within:border-brand focus-within:shadow-[0_0_0_3px_rgba(51,209,51,0.09)] [&_input]:text-label [&_input:focus]:!shadow-none"
        >
          <Search :size="16" /><span class="sr-only">Search title</span
          ><input
            v-model="query"
            class="w-[220px] border-0 bg-transparent text-label outline-none mobile:w-full"
            placeholder="Search title…"
          />
        </label>
      </div>
      <div
        v-if="error"
        class="mb-4 rounded-action border border-[#efc8bc] bg-[#fbece6] p-3 text-label text-danger"
        role="alert"
      >
        {{ error }}
      </div>
      <div
        v-if="loading && !conversations.length"
        class="p-10 text-center text-muted"
      >
        Loading conversations…
      </div>
      <div
        v-else-if="!conversations.length"
        class="p-10 text-center text-muted"
      >
        No conversations match this search.
      </div>
      <div
        v-else
        class="responsive-table overflow-x-auto [&_table]:w-full [&_table]:border-collapse [&_table]:text-left [&_table]:text-label [&_th]:border-y [&_th]:border-[#e4e8e5] [&_th]:bg-[#f6f8f6] [&_th]:px-[10px] [&_th]:py-[11px] [&_th]:text-[9px] [&_th]:uppercase [&_th]:tracking-[0.08em] [&_th]:text-[#74817d] [&_td]:border-b [&_td]:border-[#edf0ee] [&_td]:px-[10px] [&_td]:py-[13px] [&_td]:text-label [&_td_code]:text-label [&_td_small]:text-label [&_td_strong]:text-label"
      >
        <table>
          <thead>
            <tr>
              <th>Title</th>
              <th>Messages</th>
              <th>Created</th>
              <th>Last activity</th>
              <th><span class="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="conversation in conversations" :key="conversation.id">
              <td>
                <template v-if="editingId === conversation.id">
                  <input
                    v-model="editTitle"
                    :data-history-rename-id="conversation.id"
                    class="w-full max-w-[360px] rounded-control border border-brand px-2 py-1 text-control outline-none"
                    maxlength="300"
                    aria-label="Conversation title"
                    @keydown.enter.prevent="saveRename(conversation)"
                    @keydown.esc.prevent="cancelRename"
                  />
                  <small v-if="renameError" class="mt-1 block text-danger">{{
                    renameError
                  }}</small>
                </template>
                <strong
                  v-else
                  class="block max-w-[360px] overflow-hidden text-ellipsis whitespace-nowrap"
                  >{{ conversation.title || "Untitled conversation" }}</strong
                >
              </td>
              <td>{{ conversation.message_count ?? 0 }}</td>
              <td>{{ formatDate(conversation.created_at) }}</td>
              <td>
                {{
                  formatDate(
                    conversation.last_activity_at || conversation.updated_at,
                  )
                }}
              </td>
              <td class="whitespace-nowrap">
                <RouterLink
                  class="inline-grid h-[31px] w-[31px] place-items-center rounded-control text-[#546861] hover:bg-[#edf2ef] hover:text-ink"
                  :to="`/chat/${conversation.id}`"
                  :aria-label="`View ${conversation.title || 'conversation'}`"
                  title="View conversation"
                  ><Eye :size="17"
                /></RouterLink>
                <button
                  v-if="editingId === conversation.id"
                  class="inline-grid h-[31px] w-[31px] place-items-center rounded-control text-[#546861] hover:bg-[#edf2ef] hover:text-ink"
                  type="button"
                  :disabled="renaming"
                  aria-label="Save conversation title"
                  title="Save title"
                  @click="saveRename(conversation)"
                >
                  <Check :size="17" />
                </button>
                <button
                  v-else
                  class="inline-grid h-[31px] w-[31px] place-items-center rounded-control text-[#546861] hover:bg-[#edf2ef] hover:text-ink"
                  type="button"
                  :aria-label="`Rename ${conversation.title || 'conversation'}`"
                  title="Rename conversation"
                  @click="beginRename(conversation)"
                >
                  <Pencil :size="17" />
                </button>
                <button
                  v-if="editingId === conversation.id"
                  class="inline-grid h-[31px] w-[31px] place-items-center rounded-control text-[#546861] hover:bg-[#fbece6] hover:text-danger"
                  type="button"
                  aria-label="Cancel conversation rename"
                  title="Cancel rename"
                  @click="cancelRename"
                >
                  <X :size="17" />
                </button>
                <button
                  v-else
                  class="inline-grid h-[31px] w-[31px] place-items-center rounded-control text-[#546861] hover:bg-[#fbece6] hover:text-danger"
                  type="button"
                  :disabled="deleting === conversation.id"
                  :aria-label="`Delete ${conversation.title || 'conversation'}`"
                  title="Delete conversation"
                  @click="deleteConversation(conversation)"
                >
                  <Trash2 :size="17" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <PaginationControls
        :page="page"
        :page-limit="15"
        :total="total"
        :total-pages="totalPages"
        :loading="loading"
        @change="loadPage"
      />
    </section>
  </section>
</template>
