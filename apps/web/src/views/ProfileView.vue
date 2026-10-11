<script setup lang="ts">
import { KeyRound, Save, UserRound } from "@lucide/vue";
import { reactive, ref, watch } from "vue";

import { ApiError, api } from "../api/client";
import PageHeader from "../components/PageHeader.vue";
import PasswordInput from "../components/PasswordInput.vue";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const savingProfile = ref(false);
const savingPassword = ref(false);
const profileMessage = ref("");
const profileError = ref("");
const passwordMessage = ref("");
const passwordError = ref("");
const profile = reactive({
  email: "",
  first_name: "",
  last_name: "",
  company: "",
  visualization_name: "",
});
const passwords = reactive({ current: "", next: "", confirm: "" });

watch(
  () => auth.user,
  (user) => {
    if (!user) return;
    profile.email = user.email;
    profile.first_name = user.first_name ?? "";
    profile.last_name = user.last_name ?? "";
    profile.company = user.company ?? "";
    profile.visualization_name = user.visualization_name ?? "";
  },
  { immediate: true },
);

function messageFor(error: unknown, fallback: string) {
  return error instanceof ApiError || error instanceof Error
    ? error.message
    : fallback;
}

async function saveProfile() {
  savingProfile.value = true;
  profileError.value = "";
  profileMessage.value = "";
  try {
    auth.user = await api.updateProfile({
      email: profile.email,
      first_name: profile.first_name || null,
      last_name: profile.last_name || null,
      company: profile.company || null,
      visualization_name: profile.visualization_name || null,
    });
    profileMessage.value = "Profile saved.";
  } catch (error) {
    profileError.value = messageFor(error, "The profile could not be saved.");
  } finally {
    savingProfile.value = false;
  }
}

async function savePassword() {
  passwordError.value = "";
  passwordMessage.value = "";
  if (passwords.next !== passwords.confirm) {
    passwordError.value = "The new passwords do not match.";
    return;
  }
  savingPassword.value = true;
  try {
    await api.updatePassword(
      passwords.current,
      passwords.next,
      passwords.confirm,
    );
    passwords.current = "";
    passwords.next = "";
    passwords.confirm = "";
    passwordMessage.value = "Password updated.";
  } catch (error) {
    passwordError.value = messageFor(
      error,
      "The password could not be updated.",
    );
  } finally {
    savingPassword.value = false;
  }
}
</script>

<template>
  <section
    class="page-content [width:min(1380px,_100%)] [margin:0_auto] [padding:36px_clamp(22px,_3.5vw,_52px)_64px] mobile:[padding:27px_16px_45px]"
  >
    <PageHeader
      eyebrow="Account"
      title="Profile"
      description="Manage how Knemora greets and identifies you in this local workspace."
    />

    <div
      class="grid [grid-template-columns:minmax(0,_1.5fr)_minmax(300px,_0.8fr)] [gap:16px] items-stretch tablet:[grid-template-columns:1fr]"
    >
      <form
        class="surface profile-card bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] flex self-stretch flex-col [padding:clamp(22px,_3vw,_32px)] [&_.form-grid]:[margin-bottom:20px] [&_.two-column]:[grid-template-columns:repeat(2,_minmax(0,_1fr))] [&_.full-width]:[grid-column:1_/_-1] [&>.button]:self-start [&_.password-form-grid]:[grid-template-columns:1fr] mobile:[&_.two-column]:[grid-template-columns:1fr] mobile:[&_.full-width]:[grid-column:auto]"
        @submit.prevent="saveProfile"
      >
        <div
          class="profile-card-heading flex [gap:13px] items-center [margin-bottom:24px] [&>span]:grid [&>span]:place-items-center [&>span]:[width:42px] [&>span]:[height:42px] [&>span]:text-brand [&>span]:bg-brand-pale [&>span]:rounded-field [&_h2]:m-0 [&_p]:m-0 [&_h2]:text-title [&_h2]:font-medium [&_p]:[margin-top:3px] [&_p]:text-muted [&_p]:text-label"
        >
          <span><UserRound :size="20" /></span>
          <div>
            <h2>Personal details</h2>
            <p>Used only inside this workspace.</p>
          </div>
        </div>
        <div
          class="form-grid [&_input]:h-9 [&_input]:rounded-[7px] [&_input]:border [&_input]:border-line [&_input]:bg-white [&_input]:py-0 [&_input]:pl-[10px] [&_input]:pr-[30px] [&_input]:text-label [&_input]:outline-none [&_input:focus]:border-brand [&_input:focus]:shadow-[0_0_0_3px_rgba(51,209,51,0.09)] two-column grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:11px] [margin:18px_0] [&_label]:grid [&_label]:[gap:6px] [&_label]:[color:#55665f] [&_label]:text-label [&_label]:font-semibold [&_select]:w-full [&_input]:w-full mobile:[grid-template-columns:1fr]"
        >
          <label
            >Email<input
              v-model="profile.email"
              type="email"
              autocomplete="email"
              required
          /></label>
          <label
            >Visualization name<input
              v-model="profile.visualization_name"
              maxlength="200"
              placeholder="Shown after Welcome"
          /></label>
          <label
            >Name<input
              v-model="profile.first_name"
              maxlength="100"
              autocomplete="given-name"
          /></label>
          <label
            >Surname<input
              v-model="profile.last_name"
              maxlength="100"
              autocomplete="family-name"
          /></label>
          <label class="full-width"
            >Company<input
              v-model="profile.company"
              maxlength="200"
              autocomplete="organization"
              placeholder="Used for the avatar when provided"
          /></label>
        </div>
        <div
          v-if="profileError"
          class="alert alert-danger flex items-center justify-between [gap:16px] [margin:0_0_20px] [padding:12px_15px] rounded-action text-label [&_button]:[color:inherit] [&_button]:[background:transparent] [&_button]:border-0 [&_button]:font-bold [&_button]:underline [color:#7b3525] [background:#fbece6] [border:1px_solid_#efc8bc]"
          role="alert"
        >
          {{ profileError }}
        </div>
        <div
          v-if="profileMessage"
          class="alert alert-success flex items-center justify-between [gap:16px] [margin:0_0_20px] [padding:12px_15px] rounded-action text-label [&_button]:[color:inherit] [&_button]:[background:transparent] [&_button]:border-0 [&_button]:font-bold [&_button]:underline [color:#235c2d] bg-brand-pale [border:1px_solid_#bce6bc]"
          role="status"
        >
          {{ profileMessage }}
        </div>
        <button
          class="button button-primary inline-flex [gap:8px] items-center justify-center [min-height:38px] [padding:0_15px] [border:1px_solid_transparent] rounded-action text-label font-bold no-underline [transition:0.16s_ease] text-white bg-brand [box-shadow:0_2px_7px_rgb(51_209_51_/_18%)] hover:text-white hover:bg-brand hover:[opacity:0.82] hover:[transform:translateY(-1px)]"
          type="submit"
          :disabled="savingProfile"
        >
          <Save :size="17" /> {{ savingProfile ? "Saving…" : "Save profile" }}
        </button>
      </form>

      <form
        class="surface profile-card bg-surface border border-line rounded-panel [box-shadow:0_5px_20px_rgb(38_61_53_/_4%)] flex self-stretch flex-col [padding:clamp(22px,_3vw,_32px)] [&_.form-grid]:[margin-bottom:20px] [&_.two-column]:[grid-template-columns:repeat(2,_minmax(0,_1fr))] [&_.full-width]:[grid-column:1_/_-1] [&>.button]:self-start [&_.password-form-grid]:[grid-template-columns:1fr] mobile:[&_.two-column]:[grid-template-columns:1fr] mobile:[&_.full-width]:[grid-column:auto]"
        @submit.prevent="savePassword"
      >
        <div
          class="profile-card-heading flex [gap:13px] items-center [margin-bottom:24px] [&>span]:grid [&>span]:place-items-center [&>span]:[width:42px] [&>span]:[height:42px] [&>span]:text-brand [&>span]:bg-brand-pale [&>span]:rounded-field [&_h2]:m-0 [&_p]:m-0 [&_h2]:text-title [&_h2]:font-medium [&_p]:[margin-top:3px] [&_p]:text-muted [&_p]:text-label"
        >
          <span><KeyRound :size="20" /></span>
          <div>
            <h2>Password</h2>
            <p>Use at least 12 characters.</p>
          </div>
        </div>
        <div
          class="form-grid [&_input]:h-9 [&_input]:rounded-[7px] [&_input]:border [&_input]:border-line [&_input]:bg-white [&_input]:py-0 [&_input]:pl-[10px] [&_input]:pr-[30px] [&_input]:text-label [&_input]:outline-none [&_input:focus]:border-brand [&_input:focus]:shadow-[0_0_0_3px_rgba(51,209,51,0.09)] password-form-grid grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:11px] [margin:18px_0] [&_label]:grid [&_label]:[gap:6px] [&_label]:[color:#55665f] [&_label]:text-label [&_label]:font-semibold [&_select]:w-full [&_input]:w-full mobile:[grid-template-columns:1fr]"
        >
          <label
            >Current password<PasswordInput
              v-model="passwords.current"
              autocomplete="current-password"
              required
          /></label>
          <label
            >New password<PasswordInput
              v-model="passwords.next"
              autocomplete="new-password"
              minlength="12"
              required
          /></label>
          <label
            >Confirm new password<PasswordInput
              v-model="passwords.confirm"
              autocomplete="new-password"
              minlength="12"
              required
          /></label>
        </div>
        <div
          v-if="passwordError"
          class="alert alert-danger flex items-center justify-between [gap:16px] [margin:0_0_20px] [padding:12px_15px] rounded-action text-label [&_button]:[color:inherit] [&_button]:[background:transparent] [&_button]:border-0 [&_button]:font-bold [&_button]:underline [color:#7b3525] [background:#fbece6] [border:1px_solid_#efc8bc]"
          role="alert"
        >
          {{ passwordError }}
        </div>
        <div
          v-if="passwordMessage"
          class="alert alert-success flex items-center justify-between [gap:16px] [margin:0_0_20px] [padding:12px_15px] rounded-action text-label [&_button]:[color:inherit] [&_button]:[background:transparent] [&_button]:border-0 [&_button]:font-bold [&_button]:underline [color:#235c2d] bg-brand-pale [border:1px_solid_#bce6bc]"
          role="status"
        >
          {{ passwordMessage }}
        </div>
        <button
          class="button button-secondary inline-flex [gap:8px] items-center justify-center [min-height:38px] [padding:0_15px] border border-[#a9bbb4] rounded-action text-label font-bold no-underline [transition:0.16s_ease] [color:#33433e] bg-surface"
          type="submit"
          :disabled="savingPassword"
        >
          <KeyRound :size="17" />
          {{ savingPassword ? "Updating…" : "Update password" }}
        </button>
      </form>
    </div>
  </section>
</template>
