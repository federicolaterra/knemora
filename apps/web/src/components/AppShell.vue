<script setup lang="ts">
import {
  Activity,
  BarChart3,
  BrainCircuit,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Database,
  Download,
  FileUp,
  LayoutDashboard,
  Menu,
  MessageSquare,
  LogOut,
  ShieldCheck,
  ShieldEllipsis,
  RefreshCw,
  X,
} from "@lucide/vue";
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { useAuthStore } from "../stores/auth";
import { useWorkspaceStore } from "../stores/workspace";
import { useSystemStore } from "../stores/system";
import { api } from "../api/client";
import type { UpdateJob, UpdateSnapshot } from "../types";

const route = useRoute();
const auth = useAuthStore();
const workspace = useWorkspaceStore();
const system = useSystemStore();
const collapsed = ref(false);
const mobileOpen = ref(false);
const updateInfo = ref<UpdateSnapshot | null>(null);
const updateJob = ref<UpdateJob | null>(null);
const updateModalOpen = ref(false);
const updateBusy = ref(false);
const updateError = ref("");

const primary = [
  {
    label: "Overview",
    to: "/",
    icon: LayoutDashboard,
    permission: null,
    capability: null,
  },
  {
    label: "AI Chat",
    to: "/chat",
    icon: MessageSquare,
    permission: "chat.use",
    capability: "local_inference",
  },
  {
    label: "Second Brain",
    to: "/second-brain",
    icon: BrainCircuit,
    permission: "knowledge.read",
    capability: "wiki_graph",
  },
  {
    label: "Knowledge",
    to: "/knowledge",
    icon: BookOpen,
    permission: "knowledge.read",
    capability: "wiki_search",
  },
  {
    label: "Documents",
    to: "/documents",
    icon: FileUp,
    permission: "document.read",
    capability: "document_ingestion",
  },
  {
    label: "Ingestion",
    to: "/ingestion",
    icon: Activity,
    permission: "ingestion.read",
    capability: "document_ingestion",
  },
  {
    label: "Datasets",
    to: "/datasets",
    icon: Database,
    permission: "dataset.analyze",
    capability: "dataset_analysis",
  },
  {
    label: "Analytics",
    to: "/analytics",
    icon: BarChart3,
    permission: "audit.read",
    capability: "audit",
  },
];
const admin = [
  {
    label: "Audit logs",
    to: "/audit-logs",
    icon: ShieldEllipsis,
    permission: "audit.read",
    capability: "audit",
  },
];

const title = computed(() => String(route.name ?? "Workspace"));
const visiblePrimary = computed(() =>
  primary.filter(
    (item) =>
      (!item.permission || auth.can(item.permission)) &&
      (!item.capability || system.hasCapability(item.capability)),
  ),
);
const visibleAdmin = computed(() =>
  admin.filter(
    (item) =>
      auth.can(item.permission) && system.hasCapability(item.capability),
  ),
);
const avatarName = computed(() => {
  const personName = [auth.user?.first_name, auth.user?.last_name]
    .filter(Boolean)
    .join(" ");
  return (
    auth.user?.company?.trim() ||
    personName ||
    auth.user?.display_name ||
    "User"
  );
});
const initials = computed(() =>
  avatarName.value
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase(),
);

const updateLabel = computed(() => {
  if (updateJob.value?.status === "failed") return "Update failed";
  if (updateJob.value?.status === "complete") return "Restart required";
  if (
    updateJob.value?.status === "running" ||
    updateJob.value?.status === "queued"
  )
    return "Updating";
  const labels: Record<string, string> = {
    up_to_date: "Up to date",
    update_available: "Update available",
    development: "Development checkout",
    blocked: "Updates blocked",
    unavailable: "Update unavailable",
    disabled: "Checks disabled",
    checking: "Checking updates",
  };
  return labels[updateInfo.value?.state ?? "unavailable"];
});
const updateTone = computed(() => {
  if (updateJob.value?.status === "failed") return "error";
  if (
    updateJob.value?.status === "running" ||
    updateJob.value?.status === "queued"
  )
    return "progress";
  if (updateInfo.value?.state === "up_to_date") return "current";
  if (updateInfo.value?.state === "update_available") return "available";
  return "neutral";
});

async function loadUpdate() {
  if (!auth.can("settings.manage")) return;
  try {
    updateInfo.value = await api.readUpdate();
    updateJob.value = updateInfo.value.active_job ?? null;
    if (updateJob.value) void pollUpdate(updateJob.value.id);
    else if (updateInfo.value.state === "checking")
      window.setTimeout(() => void loadUpdate(), 1_500);
  } catch {
    // Update status is supplementary; local operation remains available offline.
  }
}

async function checkUpdate() {
  updateBusy.value = true;
  updateError.value = "";
  try {
    updateInfo.value = await api.checkUpdate();
  } catch (error) {
    updateError.value =
      error instanceof Error ? error.message : "Update check failed.";
  } finally {
    updateBusy.value = false;
  }
}

async function installUpdate() {
  if (!updateInfo.value?.target) return;
  updateBusy.value = true;
  updateError.value = "";
  try {
    updateJob.value = await api.startUpdate(updateInfo.value.target.sha);
    await pollUpdate(updateJob.value.id);
  } catch (error) {
    updateError.value =
      error instanceof Error ? error.message : "Update could not start.";
  } finally {
    updateBusy.value = false;
  }
}

async function pollUpdate(jobId: string) {
  const deadline = Date.now() + 20 * 60 * 1000;
  while (Date.now() < deadline) {
    await new Promise((resolve) => window.setTimeout(resolve, 1500));
    try {
      updateJob.value = await api.readUpdateJob(jobId);
      if (["complete", "failed"].includes(updateJob.value.status)) return;
    } catch {
      // The API is expected to disconnect while the independent updater restarts it.
    }
  }
  updateError.value =
    "Update status timed out. Run ./knemora status and ./knemora logs.";
}

function reloadApplication() {
  window.location.reload();
}

onMounted(() => {
  void workspace.refresh();
  void loadUpdate();
});
</script>

<template>
  <div class="flex [min-height:100vh]">
    <button
      class="hidden mobile:fixed mobile:[top:14px] mobile:[left:15px] mobile:[z-index:20] mobile:grid mobile:place-items-center mobile:[width:36px] mobile:[height:36px] mobile:[color:#43544e] mobile:bg-surface mobile:border mobile:border-line mobile:rounded-action"
      type="button"
      aria-label="Open navigation"
      @click="mobileOpen = true"
    >
      <Menu :size="20" />
    </button>
    <div
      v-if="mobileOpen"
      class="hidden mobile:fixed mobile:[inset:0] mobile:[z-index:25] mobile:block mobile:[background:rgb(8_24_19_/_40%)] mobile:[backdrop-filter:blur(2px)]"
      @click="mobileOpen = false"
    ></div>

    <aside
      class="sidebar sticky [top:0] [z-index:30] flex [flex:0_0_248px] flex-col [height:100vh] [padding:22px_16px_16px] text-ink bg-surface border-r border-line [transition:flex-basis_0.2s_ease,_transform_0.2s_ease] [&.collapsed]:[flex-basis:76px] [&.collapsed_.brand-row]:justify-center [&.collapsed_.brand-row]:w-full [&.collapsed_.brand]:justify-center [&.collapsed_.brand]:w-full mobile:fixed mobile:[left:0] mobile:[width:260px] mobile:-translate-x-[102%] mobile:[&.collapsed]:[flex-basis:260px] mobile:[&.collapsed_.nav-label]:[display:initial] mobile:[&.collapsed_.nav-item_span]:[display:initial] mobile:[&.collapsed_.runtime-card_div]:[display:initial] mobile:[&.collapsed_.brand-logo]:[display:initial] mobile:[&.collapsed_.brand-logo]:block mobile:[&.collapsed_.brand-icon]:hidden mobile:[&.collapsed_.brand-row]:justify-between mobile:[&.collapsed_.brand]:justify-start mobile:[&.collapsed_.brand]:[width:auto] mobile:[&.collapsed_.nav-item]:justify-start mobile:[&.collapsed_.nav-item]:[padding:0_11px] mobile:[&.collapsed_.runtime-card]:justify-start"
      :class="{ collapsed, 'mobile:!translate-x-0': mobileOpen }"
    >
      <div
        class="brand-row flex items-center justify-between relative [min-height:42px]"
      >
        <RouterLink
          to="/"
          class="brand flex items-center min-w-0 no-underline"
          :aria-label="`${system.name} overview`"
          @click="mobileOpen = false"
        >
          <img
            class="brand-logo block [width:172px] [height:auto] [.collapsed_&]:hidden"
            src="/knemora-logo.svg"
            alt="Knemora"
          /><img
            class="brand-icon hidden [width:38px] [height:38px] [.collapsed_&]:block"
            src="/favicon.svg"
            alt=""
            aria-hidden="true"
          />
        </RouterLink>
        <button
          class="absolute [top:50%] [right:-30px] [z-index:2] grid place-items-center [width:28px] [height:28px] [color:#385047] bg-surface border border-line rounded-full [box-shadow:0_4px_12px_rgb(24_52_31_/_10%)] [transform:translateY(-50%)] hover:text-brand hover:border-brand mobile:hidden"
          type="button"
          :aria-label="collapsed ? 'Expand navigation' : 'Collapse navigation'"
          @click="collapsed = !collapsed"
        >
          <ChevronRight v-if="collapsed" :size="16" />
          <ChevronLeft v-else :size="16" />
        </button>
        <button
          class="hidden mobile:grid mobile:place-items-center mobile:[color:#42544d] mobile:[background:none] mobile:border-0"
          type="button"
          aria-label="Close navigation"
          @click="mobileOpen = false"
        >
          <X :size="18" />
        </button>
      </div>

      <nav
        aria-label="Main navigation"
        class="flex flex-1 flex-col [gap:26px] [margin-top:34px] overflow-y-auto"
      >
        <div class="nav-group grid [gap:4px]">
          <p
            v-if="!collapsed"
            class="nav-label [margin:0_10px_7px] [color:#739085] text-caption font-bold [letter-spacing:0.13em] uppercase"
          >
            Workspace
          </p>
          <RouterLink
            v-for="item in visiblePrimary"
            :key="item.label"
            :to="item.to"
            class="nav-item flex [gap:12px] items-center [min-height:39px] [padding:0_11px] [color:#26332f] [border:1px_solid_transparent] rounded-nav text-detail font-medium no-underline [transition:0.16s_ease] hover:text-brand hover:[background:#f5faf5] [&.router-link-active]:[color:#18341f] [&.router-link-active]:bg-brand-pale [&.router-link-active]:border-brand [&.router-link-active]:[box-shadow:none] [.collapsed_&]:justify-center [.collapsed_&]:p-0"
            :title="collapsed ? item.label : undefined"
            @click="mobileOpen = false"
          >
            <component :is="item.icon" :size="18" :stroke-width="1.8" /><span
              v-if="!collapsed"
              >{{ item.label }}</span
            >
          </RouterLink>
        </div>
        <div
          v-if="visibleAdmin.length"
          class="nav-group grid [gap:4px] [margin-top:auto]"
        >
          <p
            v-if="!collapsed"
            class="nav-label [margin:0_10px_7px] [color:#739085] text-caption font-bold [letter-spacing:0.13em] uppercase"
          >
            Administration
          </p>
          <RouterLink
            v-for="item in visibleAdmin"
            :key="item.label"
            :to="item.to"
            class="nav-item flex [gap:12px] items-center [min-height:39px] [padding:0_11px] [color:#26332f] [border:1px_solid_transparent] rounded-nav text-detail font-medium no-underline [transition:0.16s_ease] hover:text-brand hover:[background:#f5faf5] [&.router-link-active]:[color:#18341f] [&.router-link-active]:bg-brand-pale [&.router-link-active]:border-brand [&.router-link-active]:[box-shadow:none] [.collapsed_&]:justify-center [.collapsed_&]:p-0"
            :title="collapsed ? item.label : undefined"
            @click="mobileOpen = false"
          >
            <component :is="item.icon" :size="18" :stroke-width="1.8" /><span
              v-if="!collapsed"
              >{{ item.label }}</span
            >
          </RouterLink>
        </div>
      </nav>

      <div class="grid [gap:10px] [padding-top:14px]">
        <div
          class="runtime-card update-status-card flex [gap:9px] items-center [padding:10px] border rounded-nav [&.compact]:justify-center"
          :title="`Knemora updates: ${updateLabel}`"
          :aria-label="`Knemora updates: ${updateLabel}`"
          :class="[
            { compact: collapsed },
            updateTone === 'current'
              ? 'bg-brand-pale border-brand'
              : updateTone === 'available'
                ? '[background:#fff4e8] [border-color:#e79a45]'
                : updateTone === 'error'
                  ? '[background:#fff2ef] border-danger'
                  : '[background:#f7f9f7] border-line',
          ]"
        >
          <span
            class="[width:7px] [height:7px] flex-none rounded-full"
            :class="
              updateTone === 'current'
                ? 'bg-brand [box-shadow:0_0_0_4px_rgb(51_209_51_/_13%)]'
                : updateTone === 'available'
                  ? '[background:#e58a2a]'
                  : updateTone === 'error'
                    ? 'bg-danger'
                    : 'bg-muted'
            "
          ></span>
          <div
            v-if="!collapsed"
            class="flex min-w-0 flex-1 flex-col [line-height:1.15]"
          >
            <strong class="text-control [color:#18341f]">Knemora updates</strong
            ><small class="[margin-top:2px] text-caption text-muted">{{
              updateLabel
            }}</small>
          </div>
          <button
            v-if="!collapsed && updateInfo?.state === 'update_available'"
            class="rounded-action [background:#e58a2a] px-2 py-1 text-caption font-bold text-white"
            type="button"
            @click="updateModalOpen = true"
          >
            Update
          </button>
          <button
            v-else-if="!collapsed && auth.can('settings.manage')"
            class="grid place-items-center text-muted hover:text-brand"
            type="button"
            title="Open update details"
            aria-label="Open update details"
            @click="updateModalOpen = true"
          >
            <RefreshCw :size="14" />
          </button>
        </div>
      </div>
    </aside>

    <main class="min-w-0 flex-1">
      <header
        class="topbar flex items-center justify-between [height:65px] [padding:0_34px] [background:rgb(255_255_255_/_82%)] border-b border-line [backdrop-filter:blur(12px)] mobile:[padding:0_16px_0_65px]"
      >
        <div>
          <span class="breadcrumb text-label text-muted">{{ system.name }}</span
          ><span class="text-label [margin:0_8px] [color:#b8c1bd]">/</span
          ><span class="text-label capitalize">{{ title }}</span>
        </div>
        <div class="flex items-center justify-between [gap:14px]">
          <span
            class="inline-flex [gap:6px] items-center text-ink text-control font-bold mobile:hidden"
            ><ShieldCheck :size="15" /> Local &amp; private</span
          ><button class="" type="button" title="Sign out" @click="auth.logout">
            <LogOut :size="16" />
          </button>
          <RouterLink
            class="avatar grid place-items-center [width:31px] [height:31px] text-white [background:#d97855] rounded-full text-caption font-bold no-underline [transition:transform_0.16s_ease,_box-shadow_0.16s_ease] hover:[box-shadow:0_0_0_3px_rgb(221_124_83_/_18%)] hover:[transform:translateY(-1px)] [&.router-link-active]:[box-shadow:0_0_0_3px_rgb(221_124_83_/_18%)] [&.router-link-active]:[transform:translateY(-1px)]"
            to="/profile"
            :aria-label="`Open profile for ${avatarName}`"
            title="Open profile"
            >{{ initials }}</RouterLink
          >
        </div>
      </header>
      <RouterView />
    </main>

    <div
      v-if="updateModalOpen"
      class="fixed inset-0 z-50 grid place-items-center [background:rgb(8_24_19_/_45%)] p-5 [backdrop-filter:blur(3px)]"
      role="presentation"
      @click.self="updateModalOpen = false"
    >
      <section
        class="update-modal max-h-[90vh] w-full max-w-[680px] overflow-y-auto rounded-panel border border-line bg-surface p-6 [box-shadow:0_22px_70px_rgb(8_24_19_/_24%)] [&_.text-caption]:text-label"
        role="dialog"
        aria-modal="true"
        aria-labelledby="update-title"
      >
        <div class="flex items-start justify-between gap-4">
          <div>
            <p
              class="m-0 text-caption font-bold uppercase tracking-wider text-brand"
            >
              Stable channel · master
            </p>
            <h2 id="update-title" class="mt-1 text-title text-ink">
              Knemora update
            </h2>
          </div>
          <button
            type="button"
            aria-label="Close update dialog"
            @click="updateModalOpen = false"
          >
            <X :size="20" />
          </button>
        </div>

        <div class="mt-5 grid grid-cols-2 gap-3 mobile:grid-cols-1">
          <div class="rounded-nav [background:#f7f9f7] p-3">
            <span class="text-caption text-muted">Running</span>
            <strong class="mt-1 block text-detail">
              {{ updateInfo?.running?.app_version || "Unknown version" }} ·
              {{ updateInfo?.running?.short_sha || "unknown" }}
            </strong>
          </div>
          <div class="rounded-nav [background:#f7f9f7] p-3">
            <span class="text-caption text-muted">Target</span>
            <strong class="mt-1 block text-detail">
              {{ updateInfo?.target?.app_version || "Not checked" }} ·
              {{ updateInfo?.target?.short_sha || "unknown" }}
            </strong>
          </div>
        </div>

        <div
          v-if="updateJob"
          class="mt-4 rounded-nav border border-line [background:#f7f9f7] p-3"
        >
          <strong class="capitalize">{{
            updateJob.stage.replaceAll("_", " ")
          }}</strong>
          <p class="mb-0 mt-1 text-detail text-muted">
            {{ updateJob.message }}
          </p>
          <p v-if="updateJob.error" class="mb-0 mt-2 text-detail text-danger">
            {{ updateJob.error }}
          </p>
        </div>

        <p
          v-if="updateInfo?.blocked_reason"
          class="mt-4 rounded-nav border border-line [background:#f7f9f7] p-3 text-detail"
        >
          <strong>Installation blocked:</strong> {{ updateInfo.blocked_reason }}
        </p>
        <p v-if="updateError" class="mt-4 text-detail text-danger">
          {{ updateError }}
        </p>

        <div v-if="updateInfo?.changes.length" class="mt-5">
          <h3 class="text-label font-bold">Changes</h3>
          <ul class="mt-2 grid gap-2 pl-5 text-detail">
            <li v-for="change in updateInfo.changes" :key="change.sha">
              <a
                class="font-semibold text-ink hover:text-brand"
                :href="change.pull_request_url || change.url"
                target="_blank"
                rel="noopener noreferrer"
              >
                {{ change.pull_request_title || change.subject }}
              </a>
              <span class="ml-2 text-caption text-muted">{{
                change.short_sha
              }}</span>
            </li>
          </ul>
          <p
            v-if="updateInfo.changes_truncated"
            class="text-caption text-muted"
          >
            Additional commits are omitted from this bounded preview.
          </p>
        </div>

        <div class="mt-5 grid gap-2 text-detail text-muted">
          <p class="m-0">
            Restart required:
            <strong>{{ updateInfo?.restart_required ? "Yes" : "No" }}</strong>
          </p>
          <p v-if="updateInfo?.dependency_changes.length" class="m-0">
            Locked dependency/runtime preparation required:
            {{ updateInfo.dependency_changes.join(", ") }}
          </p>
          <p v-if="updateInfo?.migration_changes.length" class="m-0">
            Guarded database migrations are present; a validated backup is
            created first: {{ updateInfo.migration_changes.join(", ") }}
          </p>
          <p class="m-0 text-caption">{{ updateInfo?.privacy_notice }}</p>
        </div>

        <div
          class="update-modal-actions mt-6 flex flex-wrap justify-end gap-2 [&_button]:text-label"
        >
          <button
            class="rounded-action border border-line bg-surface px-4 py-2 font-bold"
            type="button"
            :disabled="updateBusy"
            @click="updateModalOpen = false"
          >
            Cancel
          </button>
          <button
            class="inline-flex items-center gap-2 rounded-action border border-brand bg-brand-pale px-4 py-2 font-bold text-ink disabled:opacity-50"
            type="button"
            :disabled="updateBusy"
            @click="checkUpdate"
          >
            <RefreshCw
              :size="15"
              :class="{ 'animate-spin-fast': updateBusy }"
            />
            Check for updates
          </button>
          <button
            v-if="updateInfo?.installable && updateJob?.status !== 'complete'"
            class="inline-flex items-center gap-2 rounded-action bg-brand px-4 py-2 font-bold text-white disabled:opacity-50"
            type="button"
            :disabled="
              updateBusy ||
              ['queued', 'running'].includes(updateJob?.status || '')
            "
            @click="installUpdate"
          >
            <Download :size="15" /> Install update
          </button>
          <button
            v-if="updateJob?.status === 'complete'"
            class="rounded-action bg-brand px-4 py-2 font-bold text-white"
            type="button"
            @click="reloadApplication"
          >
            Reload application
          </button>
        </div>
      </section>
    </div>
  </div>
</template>
