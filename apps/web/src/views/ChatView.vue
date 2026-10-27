<script setup lang="ts">
import { useTextareaAutosize } from "@vueuse/core";
import {
  Check,
  Clipboard,
  Globe2,
  ArrowRight,
  MessageSquarePlus,
  Pencil,
  RotateCcw,
  Send,
  Square,
  Trash2,
  WandSparkles,
  X,
} from "@lucide/vue";
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api, openOriginalSource, streamMessage } from "../api/client";
import ChatResponseContent from "../components/ChatResponseContent.vue";
import ConfirmActionModal from "../components/ConfirmActionModal.vue";
import MiniScrollbar from "../components/MiniScrollbar.vue";
import PageHeader from "../components/PageHeader.vue";
import { useSystemStore } from "../stores/system";
import { useWorkspaceStore } from "../stores/workspace";
import type {
  ChatCapabilities,
  ChatExecutionMetadata,
  Conversation,
  Message,
  ResponseMode,
  ThinkingMode,
} from "../types";
import {
  groupMessagesByPromptDay,
  localDateTimeTitle,
  promptTimeLabel,
} from "../utils/chatDates";

const conversationTitleMaxLength = 74;
type MiniScrollToOptions = {
  top?: number;
  left?: number;
  behavior?: "auto" | "instant" | "smooth";
};

const route = useRoute();
const router = useRouter();
const workspace = useWorkspaceStore();
const system = useSystemStore();
const messages = ref<Message[]>([]);
const loading = ref(false);
const error = ref("");
const activeId = ref("");
const lastPrompt = ref("");
const controller = ref<AbortController>();
const copied = ref("");
const pendingDeletion = ref<Conversation | null>(null);
const deleting = ref(false);
const activeDetail = ref<Conversation | null>(null);
const editingId = ref("");
const editTitle = ref("");
const renameError = ref("");
const clock = ref(new Date());
const clockTimer = window.setInterval(() => {
  clock.value = new Date();
}, 30_000);
const chatScroll = ref<{
  scrollHeight: () => number;
  scrollTo: (options: MiniScrollToOptions) => void;
}>();
const { textarea, input } = useTextareaAutosize({ styleProp: "height" });
// The template resolves this ref by name; keep an explicit script read for static analysis.
void textarea;
const progress = ref("Understanding request…");
const responseMode = ref<ResponseMode>("wiki");
const thinkingMode = ref<ThinkingMode | null>(null);
const thinkingOptions: ThinkingMode[] = ["fast", "deep"];
const directWebPreference = ref(false);
const chatCapabilities = ref<ChatCapabilities | null>(null);
const runtimeSessionId = ref<string | null>(null);
const webSearch = computed({
  get: () => responseMode.value === "direct" && directWebPreference.value,
  set: (enabled: boolean) => {
    if (responseMode.value === "direct") directWebPreference.value = enabled;
  },
});
const webHelp = computed(() => {
  if (responseMode.value === "wiki")
    return "Web unavailable in Wiki to keep private knowledge local";
  return webSearch.value
    ? "Web ON for this browser session"
    : "Web OFF · local model only";
});

function thinkingOptionTitle(option: ThinkingMode): string {
  if (!chatCapabilities.value?.supported_thinking_modes.includes(option))
    return (
      chatCapabilities.value?.thinking_unavailable_reason ??
      `${option === "deep" ? "Deep" : "Fast"} is unavailable for the selected model.`
    );
  return option === "deep"
    ? "Deep: requests model thinking when supported"
    : "Fast: requests thinking off";
}
let progressTimer: ReturnType<typeof setInterval> | undefined;
const wikiProgressSteps = [
  "Understanding request…",
  "Searching company knowledge…",
  "Reviewing sources…",
  "Generating response…",
];
const directProgressSteps = ["Generating answer…"];
const directWebProgressSteps = ["Searching public web…", "Generating answer…"];
const demoPrompt =
  "Which gateway, owner, policy, and freeze day apply to ORBIT-LANTERN? Cite sources.";

function roundedTiming(value: number | null): number | null {
  return value === null ? null : Number(value.toFixed(3));
}

function modelLabel(message: Message): string | null {
  return message.execution?.model_name || message.model || null;
}

function thinkingLabel(
  execution?: ChatExecutionMetadata | null,
): string | null {
  if (!execution?.thinking_mode) return null;
  return execution.thinking_mode === "deep" ? "Deep" : "Fast";
}

function responseModeLabel(
  execution?: ChatExecutionMetadata | null,
): string | null {
  if (!execution) return null;
  return execution.response_mode === "direct" ? "Direct" : "Wiki";
}

function webLabel(execution?: ChatExecutionMetadata | null): string | null {
  if (!execution) return null;
  if (!execution.web_requested) return "Web OFF";
  if (execution.web_outcome === "error") return "Web ON (failed)";
  if (execution.web_outcome === "no_results") return "Web ON (no results)";
  return execution.web_succeeded ? "Web ON" : "Web ON (not completed)";
}

async function loadChatCapabilities(): Promise<boolean> {
  try {
    const capabilities = await api.readChatCapabilities();
    const runtimeChanged =
      runtimeSessionId.value !== capabilities.runtime_session_id;
    chatCapabilities.value = capabilities;
    if (runtimeChanged) {
      runtimeSessionId.value = capabilities.runtime_session_id;
      const supported = capabilities.supported_thinking_modes;
      thinkingMode.value = supported.includes(capabilities.thinking_default)
        ? capabilities.thinking_default
        : (supported[0] ?? null);
      directWebPreference.value = capabilities.web_search_default;
    }
    return true;
  } catch {
    if (runtimeSessionId.value === null) {
      chatCapabilities.value = null;
      thinkingMode.value = null;
      directWebPreference.value = false;
    }
    return false;
  }
}

const activeConversation = computed(
  () =>
    workspace.conversations.find((item) => item.id === activeId.value) ??
    activeDetail.value,
);
const messageGroups = computed(() =>
  groupMessagesByPromptDay(messages.value, clock.value),
);

async function loadConversation(id: string) {
  activeId.value = id;
  loading.value = true;
  error.value = "";
  try {
    const [conversation, persistedMessages] = await Promise.all([
      api.getConversation(id),
      api.listMessages(id),
    ]);
    activeDetail.value = conversation;
    messages.value = persistedMessages;
  } catch (reason) {
    error.value =
      reason instanceof Error ? reason.message : "Unable to load conversation.";
  } finally {
    loading.value = false;
  }
}

async function newConversation(resetMode = true) {
  if (resetMode) responseMode.value = "wiki";
  const conversation = await api.createConversation();
  workspace.conversations = [conversation, ...workspace.conversations].slice(
    0,
    8,
  );
  messages.value = [];
  activeId.value = conversation.id;
  activeDetail.value = conversation;
  await router.push(`/chat/${conversation.id}`);
}

async function beginRename(conversation: Conversation) {
  editingId.value = conversation.id;
  editTitle.value = (conversation.title || "Untitled conversation").slice(
    0,
    conversationTitleMaxLength,
  );
  renameError.value = "";
  await nextTick();
  const input = document.querySelector<HTMLInputElement>(
    `[data-rename-id="${conversation.id}"]`,
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
  renameError.value = "";
  try {
    const renamed = await api.renameConversation(
      conversation.id,
      editTitle.value,
    );
    const index = workspace.conversations.findIndex(
      (item) => item.id === renamed.id,
    );
    if (index >= 0)
      workspace.conversations[index] = {
        ...workspace.conversations[index],
        ...renamed,
      };
    if (activeId.value === renamed.id)
      activeDetail.value = {
        ...activeDetail.value,
        ...renamed,
      } as Conversation;
    cancelRename();
  } catch (reason) {
    renameError.value =
      reason instanceof Error
        ? reason.message
        : "Unable to rename conversation.";
  }
}

function requestConversationDeletion(conversation: Conversation) {
  pendingDeletion.value = conversation;
}

function closeDeletionModal() {
  if (!deleting.value) pendingDeletion.value = null;
}

async function confirmConversationDeletion() {
  const conversation = pendingDeletion.value;
  if (!conversation || deleting.value) return;
  deleting.value = true;
  error.value = "";
  try {
    await api.deleteConversation(conversation.id);
    workspace.conversations = workspace.conversations.filter(
      (item) => item.id !== conversation.id,
    );
    if (activeId.value === conversation.id) {
      const next = workspace.conversations[0];
      messages.value = [];
      activeId.value = "";
      activeDetail.value = null;
      await router.replace(next ? `/chat/${next.id}` : "/chat");
    }
    pendingDeletion.value = null;
  } catch (reason) {
    error.value =
      reason instanceof Error
        ? reason.message
        : "Unable to delete the conversation.";
  } finally {
    deleting.value = false;
  }
}

async function send(content = input.value.trim()) {
  if (!content || loading.value) return;
  if (!(await loadChatCapabilities())) {
    error.value =
      "Unable to verify the current chat runtime settings. Try again.";
    return;
  }
  if (!activeId.value) await newConversation(false);
  const submittedMode = responseMode.value;
  const submittedThinking =
    thinkingMode.value !== null &&
    chatCapabilities.value?.supported_thinking_modes.includes(
      thinkingMode.value,
    )
      ? thinkingMode.value
      : null;
  const submittedWeb = submittedMode === "direct" && webSearch.value;
  const progressSteps =
    submittedMode === "wiki"
      ? wikiProgressSteps
      : submittedWeb
        ? directWebProgressSteps
        : directProgressSteps;
  lastPrompt.value = content;
  input.value = "";
  messages.value.push(
    { role: "user", content },
    { role: "assistant", content: "" },
  );
  const target = messages.value[messages.value.length - 1];
  loading.value = true;
  error.value = "";
  controller.value = new AbortController();
  let progressIndex = 0;
  progress.value = progressSteps[0];
  progressTimer = setInterval(() => {
    progressIndex = Math.min(progressIndex + 1, progressSteps.length - 1);
    progress.value = progressSteps[progressIndex];
  }, 1600);
  await nextTick();
  chatScroll.value?.scrollTo({
    top: chatScroll.value.scrollHeight(),
    behavior: "smooth",
  });
  const streamStarted = performance.now();
  let firstDeltaMs: number | null = null;
  let lastDeltaAt = streamStarted;
  let deltaCount = 0;
  try {
    await streamMessage(
      activeId.value,
      content,
      submittedMode,
      submittedThinking,
      submittedWeb,
      controller.value.signal,
      (delta) => {
        const receivedAt = performance.now();
        if (firstDeltaMs === null) firstDeltaMs = receivedAt - streamStarted;
        lastDeltaAt = receivedAt;
        deltaCount += 1;
        target.content += delta;
        void nextTick(() =>
          chatScroll.value?.scrollTo({
            top: chatScroll.value.scrollHeight(),
            behavior: "smooth",
          }),
        );
      },
    );
    await nextTick();
    const renderedAt = performance.now();
    console.info("chat_stream_completed", {
      responseMode: submittedMode,
      durationMs: Number((renderedAt - streamStarted).toFixed(3)),
      timeToFirstDeltaMs: roundedTiming(firstDeltaMs),
      renderAfterLastDeltaMs: Number((renderedAt - lastDeltaAt).toFixed(3)),
      deltaCount,
    });
    await workspace.refresh();
    messages.value = await api.listMessages(activeId.value);
  } catch (reason) {
    if ((reason as Error).name === "AbortError") {
      if (!target.content) messages.value.pop();
    } else {
      error.value =
        reason instanceof Error
          ? reason.message
          : "The answer could not be generated.";
      if (!target.content) messages.value.pop();
    }
  } finally {
    clearInterval(progressTimer);
    loading.value = false;
    controller.value = undefined;
  }
}

function stop() {
  controller.value?.abort();
}
async function copyMessage(message: Message, index: string | number) {
  await navigator.clipboard.writeText(message.content);
  copied.value = String(index);
  setTimeout(() => {
    copied.value = "";
  }, 1600);
}
function sourceDocuments(content: string) {
  return workspace.documents.filter((document) =>
    content.toLowerCase().includes(document.original_filename.toLowerCase()),
  );
}

onBeforeUnmount(() => {
  window.clearInterval(clockTimer);
  clearInterval(progressTimer);
});

watch(
  () => route.params.id,
  (id) => {
    if (typeof id === "string" && id !== activeId.value) {
      responseMode.value = "wiki";
      void loadConversation(id);
    } else if (!id) {
      responseMode.value = "wiki";
      activeId.value = "";
      messages.value = [];
      activeDetail.value = null;
    }
  },
  { immediate: true },
);

void loadChatCapabilities();
</script>

<template>
  <section
    class="grid [grid-template-columns:minmax(0,_1fr)_245px] [height:calc(100vh_-_60px)] tablet:[grid-template-columns:1fr] mobile:[height:calc(100vh_-_60px)]"
  >
    <div
      class="relative grid [grid-template-rows:auto_1fr_auto] min-w-0 [padding:30px_clamp(22px,_4vw,_60px)_8px] overflow-hidden [&_.page-header]:[margin-bottom:14px] mobile:[padding:26px_14px_14px] mobile:[&_.page-header]:hidden"
    >
      <PageHeader
        class="[&>div:first-child]:min-w-0 [&>div:first-child]:[flex:0_1_820px] [&>div:last-child]:shrink-0"
        eyebrow="Grounded assistant"
        :title="activeConversation?.title || 'AI Chat'"
        description="Ask questions across company knowledge. Every factual answer should lead back to evidence."
      >
        <template #actions
          ><RouterLink
            class="inline-flex items-center gap-1 text-body text-brand no-underline"
            to="/chat/conversations"
            >View all <ArrowRight :size="15" /></RouterLink
          ><button
            type="button"
            class="button button-primary inline-flex [gap:8px] items-center justify-center [min-height:38px] [padding:0_15px] [border:1px_solid_transparent] rounded-action text-label font-bold no-underline [transition:0.16s_ease] text-white bg-brand [box-shadow:0_2px_7px_rgb(51_209_51_/_18%)] hover:text-white hover:bg-brand hover:[opacity:0.82] hover:[transform:translateY(-1px)]"
            @click="newConversation()"
          >
            <MessageSquarePlus :size="16" /> New conversation
          </button></template
        >
      </PageHeader>
      <MiniScrollbar
        ref="chatScroll"
        class="min-h-0 [padding:0_max(0px,_calc((100%_-_840px)_/_2))_28px]"
        aria-live="polite"
      >
        <div
          v-if="!messages.length && !loading"
          class="grid justify-items-center [min-height:100%] place-content-center [padding:40px] text-center [&>span]:grid [&>span]:place-items-center [&>span]:[width:54px] [&>span]:[height:54px] [&>span]:text-brand [&>span]:bg-brand-pale [&>span]:[border-radius:15px] [&_h2]:[margin:18px_0_7px] [&_h2]:font-sans [&_h2]:[font-size:33px] [&_h2]:font-medium [&_p]:m-0 [&_p]:text-muted [&_p]:text-body"
        >
          <span><WandSparkles :size="26" /></span>
          <h2>What would you like to understand?</h2>
          <p>
            I’ll search your connected knowledge and show where the answer comes
            from.
          </p>
          <div
            class="grid [grid-template-columns:repeat(3,_minmax(0,_1fr))] [gap:8px] [margin-top:25px] [&_button]:[padding:20px] [&_button]:[color:#44554f] [&_button]:bg-surface [&_button]:border [&_button]:border-line [&_button]:rounded-action [&_button]:text-label [&_button]:[line-height:1.4] [&_button]:text-left mobile:[grid-template-columns:1fr]"
          >
            <button
              v-if="system.demoActive"
              type="button"
              @click="send(demoPrompt)"
            >
              {{ demoPrompt }}
            </button>
            <button
              v-for="suggestion in [
                'Summarize our operating standards and cite the supporting internal sources.',
                'Identify conflicting evidence across our sources and explain what needs review.',
                'Compare the most important themes across our recent sources and cite the evidence.',
              ]"
              :key="suggestion"
              type="button"
              @click="send(suggestion)"
            >
              {{ suggestion }}
            </button>
          </div>
        </div>
        <template v-for="group in messageGroups" :key="group.key">
          <h3
            v-if="group.label"
            class="sticky top-0 z-[1] mb-3 mt-[15px] bg-[rgb(255_255_255_/_92%)] pb-2 pt-[8px] text-center text-caption font-bold text-muted backdrop-blur-sm"
          >
            {{ group.label }}
          </h3>
          <article
            v-for="message in group.messages"
            :key="
              message.id ||
              `${message.role}-${message.sequence || message.content}`
            "
            class="message grid [grid-template-columns:30px_minmax(0,_1fr)] [gap:11px] [padding:18px_0] [border-bottom:1px_solid_#e3e7e4]"
            :class="{ 'message-assistant': message.role === 'assistant' }"
          >
            <div
              class="chat-avatar grid place-items-center [width:28px] [height:28px] rounded-action bg-[#F4A440] text-caption font-bold text-white [.message-assistant_&]:bg-brand [.message-assistant_&]:text-white"
            >
              {{ message.role === "user" ? "FL" : "K" }}
            </div>
            <div class="">
              <p
                class="flex items-center [min-height:28px] [margin:0_0_8px] text-label font-bold"
              >
                {{ message.role === "user" ? "You" : system.name }}
                <time
                  v-if="message.created_at"
                  class="ml-2 text-control font-normal text-muted"
                  :datetime="message.created_at"
                  :title="localDateTimeTitle(message.created_at)"
                  >{{ promptTimeLabel(message.created_at, clock) }}</time
                >
              </p>
              <div
                v-if="
                  message.role === 'assistant' && !message.content && loading
                "
                class="flex items-center gap-[9px] font-sans text-[13px] italic text-muted [&_span]:h-[7px] [&_span]:w-[7px] [&_span]:animate-thinking [&_span]:rounded-full [&_span]:bg-brand"
              >
                <span></span>{{ progress }}
              </div>
              <ChatResponseContent v-else :content="message.content" />
              <div
                v-if="message.role === 'assistant' && message.content"
                class="flex items-center flex-wrap [gap:7px] [margin-top:12px] [&_button]:inline-flex [&_button]:[gap:5px] [&_button]:items-center [&_button]:p-0 [&_button]:[color:#71807b] [&_button]:[background:none] [&_button]:border-0 [&_button]:text-caption"
              >
                <button
                  v-if="message === messages[messages.length - 1] && !loading"
                  type="button"
                  @click="send(lastPrompt)"
                >
                  <RotateCcw :size="14" /> Retry</button
                ><button
                  type="button"
                  @click="copyMessage(message, message.id || message.content)"
                >
                  <Check
                    v-if="copied === String(message.id || message.content)"
                    :size="14"
                  /><Clipboard v-else :size="14" />{{
                    copied === String(message.id || message.content)
                      ? "Copied"
                      : "Copy"
                  }}</button
                ><template v-if="modelLabel(message)">
                  <span class="text-muted" aria-hidden="true">|</span>
                  <span class="text-caption text-muted">
                    {{ modelLabel(message) }}
                    <template v-if="responseModeLabel(message.execution)">
                      · {{ responseModeLabel(message.execution) }}
                    </template>
                    <template v-if="thinkingLabel(message.execution)">
                      · {{ thinkingLabel(message.execution) }}
                    </template>
                    <template v-if="webLabel(message.execution)">
                      · {{ webLabel(message.execution) }}
                    </template>
                  </span>
                </template>
              </div>
              <div
                v-if="sourceDocuments(message.content).length"
                class="flex flex-wrap [gap:7px] [margin-top:12px] [&_a]:[padding:5px_7px] [&_a]:[color:#47645b] [&_a]:[background:#edf3f0] [&_a]:[border-radius:5px] [&_a]:text-fine [&_a]:font-bold [&_a]:no-underline"
              >
                <button
                  v-for="source in sourceDocuments(message.content)"
                  :key="source.document_version_id"
                  type="button"
                  @click="openOriginalSource(source.original_url)"
                >
                  Source · {{ source.original_filename }}
                </button>
              </div>
            </div>
          </article>
        </template>
        <div
          v-if="error"
          class="alert alert-danger flex items-center justify-between [gap:16px] [margin:0_0_20px] [padding:12px_15px] rounded-action text-label [&_button]:[color:inherit] [&_button]:[background:transparent] [&_button]:border-0 [&_button]:font-bold [&_button]:underline [color:#7b3525] [background:#fbece6] [border:1px_solid_#efc8bc]"
        >
          <span>{{ error }}</span
          ><button v-if="lastPrompt" type="button" @click="send(lastPrompt)">
            Try again
          </button>
        </div>
      </MiniScrollbar>
      <form
        class="composer grid [width:min(840px,_100%)] [margin:0_auto] [padding:7px] bg-surface [border:1px_solid_#cfd8d3] rounded-composer [box-shadow:0_5px_22px_rgb(35_57_49_/_8%)] [&_textarea]:min-w-0 [&_textarea]:flex-1 [&_textarea]:[max-height:150px] [&_textarea]:[min-height:70px] [&_textarea]:[padding:10px] [&_textarea]:[resize:none] [&_textarea]:[background:transparent] [&_textarea]:border-0 [&_textarea]:outline-none [&_textarea]:text-copy [&_textarea]:[line-height:1.5] [&_textarea]:[vertical-align:middle] [&_textarea:focus]:!shadow-none"
        @submit.prevent="send()"
      >
        <div class="flex min-w-0 items-start gap-1">
          <textarea
            ref="textarea"
            v-model="input"
            rows="1"
            aria-label="Message"
            placeholder="Ask your Second Brain…"
            @keydown.enter.exact.prevent="send()"
          ></textarea
          ><button
            v-if="loading"
            type="button"
            class="composer-send stop grid [width:36px] [height:36px] shrink-0 place-items-center [margin:2px] text-white bg-brand border-0 rounded-action [&.stop]:[background:#9e4935]"
            aria-label="Stop generating"
            @click="stop"
          >
            <Square :size="16" fill="currentColor" /></button
          ><button
            v-else
            type="submit"
            class="composer-send grid [width:36px] [height:36px] shrink-0 place-items-center [margin:2px] text-white bg-brand border-0 rounded-action"
            :disabled="!input.trim()"
            aria-label="Send message"
          >
            <Send :size="17" />
          </button>
        </div>
        <div class="flex min-w-0 flex-wrap items-center gap-2 px-2 pb-1">
          <fieldset
            class="m-0 flex shrink-0 rounded-control border border-line bg-[#edf1ee] p-px"
            aria-label="Response mode"
          >
            <legend class="sr-only">Response mode</legend>
            <label
              class="cursor-pointer"
              title="Wiki: answers grounded in your knowledge"
            >
              <input
                v-model="responseMode"
                class="peer sr-only"
                type="radio"
                name="response-mode"
                value="wiki"
                :disabled="loading"
              />
              <span
                class="block rounded-[5px] px-[7px] py-[3px] [font-size:10px] font-bold text-muted transition-colors peer-checked:bg-brand peer-checked:text-white peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-brand peer-disabled:cursor-not-allowed peer-disabled:opacity-60"
                >Wiki</span
              >
            </label>
            <label
              class="cursor-pointer"
              title="Direct: local AI without knowledge search"
            >
              <input
                v-model="responseMode"
                class="peer sr-only"
                type="radio"
                name="response-mode"
                value="direct"
                :disabled="loading"
              />
              <span
                class="block rounded-[5px] px-[7px] py-[3px] [font-size:10px] font-bold text-muted transition-colors peer-checked:bg-brand peer-checked:text-white peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-brand peer-disabled:cursor-not-allowed peer-disabled:opacity-60"
                >Direct</span
              >
            </label>
          </fieldset>
          <fieldset
            class="m-0 flex shrink-0 rounded-control border border-line bg-[#edf1ee] p-px"
            aria-label="Thinking mode"
          >
            <legend class="sr-only">Thinking mode</legend>
            <label
              v-for="option in thinkingOptions"
              :key="option"
              class="cursor-pointer"
              :title="thinkingOptionTitle(option)"
            >
              <input
                v-model="thinkingMode"
                class="peer sr-only"
                type="radio"
                name="thinking-mode"
                :value="option"
                :disabled="
                  loading ||
                  !chatCapabilities?.supported_thinking_modes.includes(option)
                "
              />
              <span
                class="block rounded-[5px] px-[7px] py-[3px] [font-size:10px] font-bold capitalize text-muted transition-colors peer-checked:bg-brand peer-checked:text-white peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-brand peer-disabled:cursor-not-allowed peer-disabled:opacity-60"
                >{{ option }}</span
              >
            </label>
          </fieldset>
          <label
            class="inline-flex shrink-0 cursor-pointer rounded-control border border-line bg-[#edf1ee] p-px"
            :title="webHelp"
          >
            <input
              v-model="webSearch"
              class="peer sr-only"
              type="checkbox"
              :disabled="
                loading ||
                responseMode === 'wiki' ||
                !chatCapabilities?.web_search_available
              "
            />
            <span
              class="inline-flex items-center gap-1 rounded-[5px] px-[7px] py-[3px] [font-size:10px] font-bold text-muted transition-colors peer-checked:bg-brand peer-checked:text-white peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-brand peer-disabled:cursor-not-allowed peer-disabled:opacity-60"
            >
              <Globe2 :size="12" /> Web {{ webSearch ? "ON" : "OFF" }}
            </span>
          </label>
        </div>
      </form>
      <p
        class="[width:min(840px,_100%)] [margin:6px_auto_0] text-center [font-size:11px] text-muted"
      >
        AI responses may include mistakes.
      </p>
    </div>
    <aside
      class="[padding:20px_13px] overflow-y-auto [background:#eef1ee] border-l border-line [&_nav]:grid [&_nav]:[gap:6px] tablet:hidden"
    >
      <div
        class="flex items-center justify-between [padding:0_6px_13px] [&_h2]:m-0 [&_h2]:text-caption [&_h2]:[letter-spacing:0.09em] [&_h2]:uppercase [&_button]:grid [&_button]:place-items-center [&_button]:text-brand [&_button]:[background:none] [&_button]:border-0"
      >
        <h2>Recent Conversations</h2>
      </div>
      <nav>
        <div
          v-for="conversation in workspace.conversations"
          :key="conversation.id"
          class="group relative min-h-[93px] rounded-control bg-surface"
          :class="{ active: conversation.id === activeId }"
        >
          <form
            v-if="editingId === conversation.id"
            class="grid min-h-[93px] grid-rows-[1fr_auto] gap-1 px-[10px] pb-[15px] pt-[9px]"
            @submit.prevent="saveRename(conversation)"
          >
            <input
              v-model="editTitle"
              :data-rename-id="conversation.id"
              class="min-w-0 self-start rounded-control border border-brand px-2 py-1 text-control outline-none"
              :maxlength="conversationTitleMaxLength"
              aria-label="Conversation title"
              @keydown.esc.prevent="cancelRename"
            />
            <small
              class="self-end pr-[60px] text-right text-caption text-muted"
              aria-live="polite"
            >
              {{ editTitle.length }}/{{ conversationTitleMaxLength }}
            </small>
            <small
              v-if="renameError"
              class="self-end pr-[60px] text-body text-danger"
              >{{ renameError }}</small
            >
            <div class="absolute bottom-2 right-1 flex">
              <button
                type="submit"
                class="grid h-[30px] w-7 place-items-center rounded-[6px] border-0 bg-transparent text-[#87938f] hover:bg-[#edf2ef] hover:text-ink"
                aria-label="Save conversation title"
                title="Save title"
              >
                <Check :size="14" />
              </button>
              <button
                type="button"
                class="grid h-[30px] w-7 place-items-center rounded-[6px] border-0 bg-transparent text-[#87938f] hover:bg-[#fbece6] hover:text-danger"
                aria-label="Cancel conversation rename"
                title="Cancel rename"
                @click="cancelRename"
              >
                <X :size="14" />
              </button>
            </div>
          </form>
          <template v-else>
            <RouterLink
              :to="`/chat/${conversation.id}`"
              class="grid min-h-[93px] min-w-0 grid-rows-[1fr_auto] px-[10px] pb-[15px] pt-[9px] no-underline"
              ><strong
                class="overflow-hidden text-control [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:2]"
                >{{ conversation.title || "Untitled conversation" }}</strong
              ><small class="self-end pr-[60px] pt-1 text-control text-muted"
                >{{ conversation.message_count ?? 0 }} messages</small
              ></RouterLink
            >
            <div
              class="absolute bottom-2 right-1 flex [opacity:0.55] focus-within:opacity-100 group-hover:opacity-100 [.active_&]:opacity-100 tablet:opacity-100"
            >
              <button
                type="button"
                :aria-label="`Rename ${conversation.title || 'conversation'}`"
                title="Rename conversation"
                class="grid h-[30px] w-7 place-items-center rounded-[6px] border-0 bg-transparent text-[#87938f] hover:bg-[#edf2ef] hover:text-ink"
                @click.stop="beginRename(conversation)"
              >
                <Pencil :size="14" />
              </button>
              <button
                type="button"
                :aria-label="`Delete ${conversation.title || 'conversation'}`"
                title="Delete conversation"
                class="grid h-[30px] w-7 place-items-center rounded-[6px] border-0 bg-transparent text-[#87938f] hover:bg-[#fbece6] hover:text-danger"
                @click.stop="requestConversationDeletion(conversation)"
              >
                <Trash2 :size="14" />
              </button>
            </div>
          </template>
        </div>
      </nav>
    </aside>
    <ConfirmActionModal
      v-if="pendingDeletion"
      title="Delete conversation?"
      :description="`Are you sure you want to confirm this action? “${pendingDeletion.title || 'Untitled conversation'}” and all its messages will be permanently deleted.`"
      confirm-label="Confirm"
      busy-label="Deleting…"
      close-label="Close deletion confirmation"
      :busy="deleting"
      @close="closeDeletionModal"
      @confirm="confirmConversationDeletion"
    >
      <template #confirm-icon><Trash2 :size="16" /></template>
    </ConfirmActionModal>
  </section>
</template>
