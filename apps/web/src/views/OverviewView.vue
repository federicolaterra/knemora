<script setup lang="ts">
import {
  ArrowRight,
  BarChart3,
  BookOpen,
  Database,
  FileCheck2,
  MessageSquare,
  Plus,
} from "@lucide/vue";
import { computed } from "vue";

import PageHeader from "../components/PageHeader.vue";
import StatusBadge from "../components/StatusBadge.vue";
import { useAuthStore } from "../stores/auth";
import { useSystemStore } from "../stores/system";
import { useWorkspaceStore } from "../stores/workspace";

const auth = useAuthStore();
const system = useSystemStore();
const workspace = useWorkspaceStore();
const welcomeName = computed(
  () =>
    auth.user?.visualization_name?.trim() ||
    auth.user?.first_name?.trim() ||
    auth.user?.display_name.trim().split(/\s+/)[0] ||
    "there",
);
const activeJobs = computed(
  () =>
    workspace.documents.filter(
      (item) => !["COMPLETED", null].includes(item.compilation_status),
    ).length,
);
const countCards = computed(() => [
  {
    label: "Conversations",
    value: workspace.conversationTotal,
    note: "Grounded in your sources",
    icon: MessageSquare,
  },
  {
    label: "Datasets",
    value: workspace.datasetTotal,
    note: "Deterministic analysis",
    icon: Database,
  },
]);
</script>

<template>
  <section
    class="page-content [width:min(1380px,_100%)] [margin:0_auto] [padding:36px_clamp(22px,_3.5vw,_52px)_64px] mobile:[padding:27px_16px_45px]"
  >
    <PageHeader
      eyebrow="Second Brain"
      :title="`Welcome, ${welcomeName}`"
      description="Your private company knowledge, connected and ready to explore."
    >
      <template #actions
        ><RouterLink
          v-if="!system.demoActive"
          class="button button-primary inline-flex [gap:8px] items-center justify-center [min-height:38px] [padding:0_15px] [border:1px_solid_transparent] rounded-action text-label font-bold no-underline [transition:0.16s_ease] text-white bg-brand [box-shadow:0_2px_7px_rgb(51_209_51_/_18%)] hover:text-white hover:bg-brand hover:[opacity:0.82] hover:[transform:translateY(-1px)]"
          to="/documents"
          ><Plus :size="16" /> Add sources</RouterLink
        ></template
      >
    </PageHeader>

    <div
      v-if="workspace.error"
      class="alert alert-danger flex items-center justify-between [gap:16px] [margin:0_0_20px] [padding:12px_15px] rounded-action text-label [&_button]:[color:inherit] [&_button]:[background:transparent] [&_button]:border-0 [&_button]:font-bold [&_button]:underline [color:#7b3525] [background:#fbece6] [border:1px_solid_#efc8bc]"
      role="alert"
    >
      {{ workspace.error }}
      <button type="button" @click="workspace.refresh">Retry</button>
    </div>

    <div
      class="grid [grid-template-columns:minmax(0,_1.5fr)_minmax(340px,_1fr)] [gap:16px] tablet:[grid-template-columns:1fr] mobile:[grid-template-columns:1fr]"
    >
      <RouterLink
        class="surface bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] relative grid [grid-template-columns:minmax(0,_1.2fr)_minmax(220px,_0.8fr)] [gap:28px] [min-height:258px] [padding:clamp(24px,_3vw,_38px)] overflow-hidden [color:inherit] [background:linear-gradient(145deg,_#eef9ef,_#fff_66%)] no-underline [&_h2]:[max-width:520px] [&_h2]:m-0 [&_h2]:[font-size:2.25rem] [&_h2]:font-medium [&_h2]:[letter-spacing:-0.035em] [&_h2]:[line-height:1.03] [&>div:first-child>p:last-child]:[max-width:520px] [&>div:first-child>p:last-child]:[margin:18px_0_0] [&>div:first-child>p:last-child]:text-muted [&>div:first-child>p:last-child]:text-body [&>div:first-child>p:last-child]:[line-height:1.55] phone:[grid-template-columns:1fr] phone:[min-height:440px]"
        to="/knowledge"
      >
        <div>
          <p
            class="section-kicker [margin:0_0_8px] text-brand text-caption font-medium [letter-spacing:0.13em] uppercase"
          >
            Knowledge workspace
          </p>
          <h2>
            {{
              activeJobs
                ? "Your knowledge is growing"
                : "Knowledge is up to date"
            }}
          </h2>
          <p>
            Explore your connected company knowledge and trace every answer to
            its source.
          </p>
        </div>
        <div
          class="flex items-center justify-center [gap:26px] [&_.pulse-orbit]:flex-none [&_.pulse-orbit]:m-0 [&_dl]:grid [&_dl]:[gap:14px] [&_dl]:m-0 [&_dl_div]:flex [&_dl_div]:[align-items:baseline] [&_dl_div]:justify-between [&_dl_div]:[gap:18px] [&_dl_div]:[padding-bottom:12px] [&_dl_div]:[border-bottom:1px_solid_#dfe9e0] [&_dt]:text-muted [&_dt]:text-label [&_dd]:m-0 [&_dd]:[font-size:27px] [&_dd]:font-medium phone:justify-start"
        >
          <span
            class="pulse-orbit relative grid place-items-center [width:88px] [height:88px] [margin:22px_auto] text-brand bg-surface [border:1px_solid_#cde0d7] rounded-full [box-shadow:0_0_0_10px_rgb(51_209_51_/_5%),_0_0_0_20px_rgb(51_209_51_/_3%)]"
            ><BookOpen :size="26" /><i
              class="orbit-dot absolute left-1/2 top-1/2 size-3 animate-orbit rounded-full bg-[#F4A440] [margin:-6px_0_0_-6px] motion-reduce:animate-none motion-reduce:[transform:translateX(38px)]"
            ></i
          ></span>
          <dl>
            <div>
              <dt>Knowledge pages</dt>
              <dd>{{ workspace.pageTotal }}</dd>
            </div>
            <div>
              <dt>Source documents</dt>
              <dd>{{ workspace.documentTotal }}</dd>
            </div>
          </dl>
        </div>
        <span
          class="absolute [right:30px] [bottom:24px] inline-flex items-center [gap:7px] text-brand text-label font-bold phone:[left:24px] phone:[right:auto]"
          >Explore knowledge <ArrowRight :size="16"
        /></span>
      </RouterLink>

      <div
        class="grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:16px] [&_.stat-card]:[min-height:258px] [&_.stat-card]:[padding:25px] [&_.stat-card>strong]:[margin-top:80px] [&_.stat-card>strong]:[font-size:31px] phone:[grid-template-columns:1fr] phone:[grid-template-columns:repeat(2,_minmax(0,_1fr))] phone:[gap:9px] phone:[&_.stat-card]:[min-height:170px] phone:[&_.stat-card]:[padding:15px] phone:[&_.stat-card>strong]:[margin-top:58px] phone:[&_.stat-card>strong]:[font-size:31px]"
      >
        <article
          v-for="stat in countCards"
          :key="stat.label"
          class="stat-card summary-card-copy relative [min-height:145px] [padding:20px] bg-surface border border-line rounded-composer [&>strong]:block [&>strong]:[margin-top:20px] [&>strong]:[font-size:31px] [&>strong]:font-medium [&_h2]:[margin:5px_0_3px] [&_h2]:text-label [&_h2]:font-bold [&_p]:m-0 [&_p]:text-muted [&_p]:text-label phone:[min-height:125px] phone:[padding:15px] phone:[&>strong]:[margin-top:30px]"
        >
          <span
            class="stat-icon absolute [top:17px] [right:17px] grid place-items-center [width:33px] [height:33px] text-brand bg-brand-pale rounded-action"
            ><component :is="stat.icon" :size="20"
          /></span>
          <strong>{{ stat.value }}</strong>
          <h2>{{ stat.label }}</h2>
          <p>{{ stat.note }}</p>
        </article>
      </div>
    </div>

    <div
      class="grid [grid-template-columns:minmax(0,_1.5fr)_minmax(340px,_1fr)] [gap:16px] [margin-top:16px] [&_.recent-card]:[min-height:380px] tablet:[grid-template-columns:1fr] mobile:[grid-template-columns:1fr] phone:[&_.recent-card]:[min-height:280px]"
    >
      <section
        class="surface recent-card bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] [padding:22px]"
      >
        <div
          class="section-heading flex items-center justify-between items-start [gap:16px] [&_h2]:m-0 [&_h2]:font-sans [&_h2]:text-title [&_h2]:font-medium [&_a]:flex [&_a]:[gap:5px] [&_a]:items-center [&_a]:text-brand [&_a]:text-label [&_a]:font-bold [&_a]:no-underline"
        >
          <div>
            <p
              class="section-kicker [margin:0_0_8px] text-brand text-caption font-medium [letter-spacing:0.13em] uppercase"
            >
              Latest activity
            </p>
            <h2>Recent sources</h2>
          </div>
          <RouterLink to="/documents"
            >View all <ArrowRight :size="15"
          /></RouterLink>
        </div>
        <div
          v-if="!workspace.documents.length"
          class="empty-compact flex [gap:12px] items-center [padding:25px_5px] text-muted text-label"
        >
          <FileCheck2 :size="28" />
          <p>
            No sources yet. Upload a document to begin building your company
            Wiki.
          </p>
        </div>
        <ul
          v-else
          class="[margin:16px_0_0] p-0 [list-style:none] [&_li]:flex [&_li]:[gap:11px] [&_li]:items-center [&_li]:[min-height:58px] [&_li]:[border-top:1px_solid_#edf0ee] [&_li>div]:min-w-0 [&_li>div]:flex-1 [&_strong]:block [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_small]:block [&_small]:overflow-hidden [&_small]:text-ellipsis [&_small]:whitespace-nowrap [&_strong]:text-label [&_strong]:font-semibold [&_small]:[margin-top:4px] [&_small]:text-muted [&_small]:text-label"
        >
          <li
            v-for="document in workspace.documents"
            :key="document.document_version_id"
          >
            <span
              class="file-symbol inline-grid place-items-center [width:35px] [height:35px] flex-none [color:#49635a] [background:#eef2ef] rounded-control text-caption font-semibold"
              >{{
                document.original_filename.split(".").pop()?.toUpperCase()
              }}</span
            >
            <div class="source-file-copy">
              <strong>{{ document.original_filename }}</strong
              ><small
                >{{ (document.byte_size / 1024).toFixed(1) }} KB · v{{
                  document.version_number
                }}</small
              >
            </div>
            <StatusBadge
              class="compact-status-badge !text-caption"
              :status="document.compilation_status ?? document.ingestion_status"
            />
          </li>
        </ul>
      </section>

      <aside
        class="grid [grid-template-rows:repeat(3,_1fr)] [gap:12px]"
        aria-label="Quick actions"
      >
        <RouterLink
          class="surface overview-action-card summary-card-copy featured bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] flex [gap:14px] items-center [min-height:110px] [padding:20px] [color:#284139] no-underline [transition:transform_0.16s_ease,_border-color_0.16s_ease] hover:[border-color:#aedbae] hover:[transform:translateY(-2px)] [&.featured]:bg-brand-pale [&.featured]:[border-color:#bce6bc] [&>span]:grid [&>span]:place-items-center [&>span]:[width:40px] [&>span]:[height:40px] [&>span]:flex-none [&>span]:text-brand [&>span]:bg-surface [&>span]:rounded-field [&>div]:min-w-0 [&>div]:flex-1 [&_strong]:block [&_small]:block [&_strong]:text-detail [&_strong]:font-bold [&_small]:[margin-top:4px] [&_small]:text-muted [&_small]:text-label [&_small]:[line-height:1.4]"
          to="/chat"
        >
          <span><MessageSquare :size="20" /></span>
          <div>
            <strong>Ask the Second Brain</strong
            ><small>Get a sourced answer from company knowledge.</small>
          </div>
          <ArrowRight :size="17" />
        </RouterLink>
        <RouterLink
          class="surface overview-action-card summary-card-copy bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] flex [gap:14px] items-center [min-height:110px] [padding:20px] [color:#284139] no-underline [transition:transform_0.16s_ease,_border-color_0.16s_ease] hover:[border-color:#aedbae] hover:[transform:translateY(-2px)] [&.featured]:bg-brand-pale [&.featured]:[border-color:#bce6bc] [&>span]:grid [&>span]:place-items-center [&>span]:[width:40px] [&>span]:[height:40px] [&>span]:flex-none [&>span]:text-brand [&>span]:bg-surface [&>span]:rounded-field [&>div]:min-w-0 [&>div]:flex-1 [&_strong]:block [&_small]:block [&_strong]:text-detail [&_strong]:font-bold [&_small]:[margin-top:4px] [&_small]:text-muted [&_small]:text-label [&_small]:[line-height:1.4]"
          to="/knowledge"
        >
          <span><BookOpen :size="20" /></span>
          <div>
            <strong>Browse knowledge</strong
            ><small>Move through pages, claims, and source links.</small>
          </div>
          <ArrowRight :size="17" />
        </RouterLink>
        <RouterLink
          class="surface overview-action-card summary-card-copy bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] flex [gap:14px] items-center [min-height:110px] [padding:20px] [color:#284139] no-underline [transition:transform_0.16s_ease,_border-color_0.16s_ease] hover:[border-color:#aedbae] hover:[transform:translateY(-2px)] [&.featured]:bg-brand-pale [&.featured]:[border-color:#bce6bc] [&>span]:grid [&>span]:place-items-center [&>span]:[width:40px] [&>span]:[height:40px] [&>span]:flex-none [&>span]:text-brand [&>span]:bg-surface [&>span]:rounded-field [&>div]:min-w-0 [&>div]:flex-1 [&_strong]:block [&_small]:block [&_strong]:text-detail [&_strong]:font-bold [&_small]:[margin-top:4px] [&_small]:text-muted [&_small]:text-label [&_small]:[line-height:1.4]"
          to="/analytics"
        >
          <span><BarChart3 :size="20" /></span>
          <div>
            <strong>Review workspace activity</strong
            ><small>See usage, processing, and audit trends.</small>
          </div>
          <ArrowRight :size="17" />
        </RouterLink>
      </aside>
    </div>
  </section>
</template>
