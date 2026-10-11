<script setup lang="ts">
import { Search } from "@lucide/vue";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "../api/client";
import PaginationControls from "../components/PaginationControls.vue";
import PageHeader from "../components/PageHeader.vue";
import type { AuditEventRecord, CurrentUser, RoleRecord } from "../types";

const props = defineProps<{
  kind: "users" | "roles" | "audit" | "settings";
  title: string;
  description: string;
}>();
const route = useRoute();
const router = useRouter();
const loading = ref(true);
const error = ref("");
const users = ref<CurrentUser[]>([]);
const roles = ref<RoleRecord[]>([]);
const events = ref<AuditEventRecord[]>([]);
const settings = ref<Record<string, unknown>>({});
const query = ref(
  props.kind === "audit" && typeof route.query.event_type === "string"
    ? route.query.event_type
    : "",
);
const page = ref(
  props.kind === "audit" ? Math.max(1, Number(route.query.page) || 1) : 1,
);
const total = ref(0);
const totalPages = ref(1);
let searchTimer: ReturnType<typeof setTimeout> | undefined;
let requestSequence = 0;

async function loadData(targetPage = page.value) {
  const request = ++requestSequence;
  loading.value = true;
  error.value = "";
  try {
    if (props.kind === "users") users.value = await api.listUsers();
    if (props.kind === "roles") roles.value = await api.listRoles();
    if (props.kind === "audit") {
      const result = await api.listAuditEvents(
        targetPage,
        15,
        query.value.trim(),
      );
      if (request !== requestSequence) return;
      if (result.total && targetPage > result.total_pages) {
        await loadData(result.total_pages);
        return;
      }
      events.value = result.items;
      page.value = result.page;
      total.value = result.total;
      totalPages.value = result.total_pages;
      await router.replace({
        query: {
          ...(query.value.trim() ? { event_type: query.value.trim() } : {}),
          ...(result.page > 1 ? { page: String(result.page) } : {}),
        },
      });
    }
    if (props.kind === "settings") settings.value = await api.readSettings();
  } catch (reason) {
    if (request !== requestSequence) return;
    error.value =
      reason instanceof Error
        ? reason.message
        : "Unable to load administration data.";
  } finally {
    if (request === requestSequence) loading.value = false;
  }
}

watch(query, () => {
  if (props.kind !== "audit") return;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => void loadData(1), 300);
});
onMounted(() => void loadData());
onBeforeUnmount(() => clearTimeout(searchTimer));
</script>

<template>
  <section
    class="page-content [width:min(1380px,_100%)] [margin:0_auto] [padding:36px_clamp(22px,_3.5vw,_52px)_64px] mobile:[padding:27px_16px_45px]"
  >
    <PageHeader
      eyebrow="Administration"
      :title="title"
      :description="description"
    />
    <div
      v-if="loading && kind !== 'audit'"
      class="loading-block [padding:40px] text-muted text-center"
    >
      Loading secure administration data…
    </div>
    <div
      v-else-if="error"
      class="alert alert-danger flex items-center justify-between [gap:16px] [margin:0_0_20px] [padding:12px_15px] rounded-action text-label [&_button]:[color:inherit] [&_button]:[background:transparent] [&_button]:border-0 [&_button]:font-bold [&_button]:underline [color:#7b3525] [background:#fbece6] [border:1px_solid_#efc8bc]"
      role="alert"
    >
      {{ error }}
    </div>
    <section
      v-else
      class="surface table-surface bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] [padding:22px]"
    >
      <div
        v-if="kind === 'audit'"
        class="mb-4 flex items-end justify-between gap-4 mobile:items-stretch mobile:flex-col"
      >
        <div>
          <h2 class="m-0 font-sans text-title font-medium">Logs history</h2>
          <p class="mb-0 mt-1 text-label text-muted">
            {{ total }} logs · 15 per page
          </p>
        </div>
        <label
          class="search-field flex min-h-9 items-center gap-2 rounded-control border border-line bg-[#f8f9f7] px-2 focus-within:border-brand focus-within:shadow-[0_0_0_3px_rgba(51,209,51,0.09)] [&_input]:text-label [&_input:focus]:!shadow-none"
        >
          <Search :size="16" /><span class="sr-only">Search event</span
          ><input
            v-model="query"
            class="w-[220px] border-0 bg-transparent text-label outline-none mobile:w-full"
            placeholder="Search event…"
          />
        </label>
      </div>
      <div
        v-if="kind === 'users'"
        class="responsive-table [&_table]:w-full [&_table]:border-collapse [&_table]:text-left [&_table]:text-label [&_th]:border-y [&_th]:border-[#e4e8e5] [&_th]:bg-[#f6f8f6] [&_th]:px-[10px] [&_th]:py-[11px] [&_th]:text-[9px] [&_th]:uppercase [&_th]:tracking-[0.08em] [&_th]:text-[#74817d] [&_td]:border-b [&_td]:border-[#edf0ee] [&_td]:px-[10px] [&_td]:py-[13px] [&_td]:align-middle [&_td]:text-label [&_td_code]:text-label [&_td_strong]:block [&_td_strong]:text-label [&_td_small]:block [&_td_small]:mt-1 [&_td_small]:text-label [&_td_small]:text-muted overflow-x-auto"
      >
        <table>
          <thead>
            <tr>
              <th>User</th>
              <th>Roles</th>
              <th>Permissions</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in users" :key="user.id">
              <td>
                <strong>{{ user.display_name }}</strong
                ><small>{{ user.email }}</small>
              </td>
              <td>{{ user.roles.join(", ") || "No roles" }}</td>
              <td>{{ user.permissions.length }}</td>
              <td>{{ user.is_active ? "Active" : "Disabled" }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div
        v-else-if="kind === 'roles'"
        class="responsive-table [&_table]:w-full [&_table]:border-collapse [&_table]:text-left [&_table]:text-label [&_th]:border-y [&_th]:border-[#e4e8e5] [&_th]:bg-[#f6f8f6] [&_th]:px-[10px] [&_th]:py-[11px] [&_th]:text-[9px] [&_th]:uppercase [&_th]:tracking-[0.08em] [&_th]:text-[#74817d] [&_td]:border-b [&_td]:border-[#edf0ee] [&_td]:px-[10px] [&_td]:py-[13px] [&_td]:align-middle [&_td]:text-label [&_td_code]:text-label [&_td_strong]:block [&_td_strong]:text-label [&_td_small]:block [&_td_small]:mt-1 [&_td_small]:text-label [&_td_small]:text-muted overflow-x-auto"
      >
        <table>
          <thead>
            <tr>
              <th>Role</th>
              <th>Description</th>
              <th>Permissions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="role in roles" :key="role.id">
              <td>
                <strong>{{ role.name }}</strong>
              </td>
              <td>{{ role.description }}</td>
              <td>
                <code>{{ role.permissions.join(", ") }}</code>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div
        v-else-if="kind === 'audit' && loading && !events.length"
        class="p-10 text-center text-muted"
      >
        Loading audit logs…
      </div>
      <div
        v-else-if="kind === 'audit' && !events.length"
        class="p-10 text-center text-muted"
      >
        No audit logs match this search.
      </div>
      <div
        v-else-if="kind === 'audit'"
        class="responsive-table [&_table]:w-full [&_table]:border-collapse [&_table]:text-left [&_table]:text-label [&_th]:border-y [&_th]:border-[#e4e8e5] [&_th]:bg-[#f6f8f6] [&_th]:px-[10px] [&_th]:py-[11px] [&_th]:text-[9px] [&_th]:uppercase [&_th]:tracking-[0.08em] [&_th]:text-[#74817d] [&_td]:border-b [&_td]:border-[#edf0ee] [&_td]:px-[10px] [&_td]:py-[13px] [&_td]:align-middle [&_td]:text-label [&_td_code]:text-label [&_td_strong]:block [&_td_strong]:text-label [&_td_small]:block [&_td_small]:mt-1 [&_td_small]:text-label [&_td_small]:text-muted overflow-x-auto"
      >
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Event</th>
              <th>Entity</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="event in events" :key="event.id">
              <td>{{ new Date(event.created_at).toLocaleString() }}</td>
              <td>
                <strong>{{ event.event_type }}</strong>
              </td>
              <td>{{ event.entity_type }} · {{ event.entity_id }}</td>
              <td>
                <code>{{ JSON.stringify(event.payload) }}</code>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <PaginationControls
        v-if="kind === 'audit'"
        :page="page"
        :total="total"
        :total-pages="totalPages"
        :loading="loading"
        @change="loadData"
      />
      <dl
        v-if="kind === 'settings'"
        class="grid [gap:0] m-0 [&_div]:grid [&_div]:[grid-template-columns:minmax(192px,_1fr)_2fr] [&_div]:[gap:16px] [&_div]:[padding:16px_20px] [&_div]:[border-bottom:1px_solid_#e2e8e5] [&_dt]:capitalize [&_dt]:font-bold"
      >
        <div v-for="(value, key) in settings" :key="key">
          <dt>{{ String(key).replaceAll("_", " ") }}</dt>
          <dd>
            <code>{{ value }}</code>
          </dd>
        </div>
      </dl>
    </section>
  </section>
</template>
