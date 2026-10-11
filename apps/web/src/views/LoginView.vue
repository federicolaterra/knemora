<script setup lang="ts">
import { LockKeyhole, ShieldCheck } from "@lucide/vue";
import { ref, watch } from "vue";
import { useRouter } from "vue-router";

import PasswordInput from "../components/PasswordInput.vue";
import { useAuthStore } from "../stores/auth";
import { useSystemStore } from "../stores/system";

const auth = useAuthStore();
const system = useSystemStore();
const router = useRouter();
const email = ref("");
const password = ref("");

watch(
  () => system.defaultLoginEmail,
  (defaultEmail) => {
    if (!email.value) email.value = defaultEmail;
  },
  { immediate: true },
);

async function submit() {
  await auth.login(email.value, password.value);
  if (auth.authenticated) await router.replace({ name: "overview" });
}
</script>

<template>
  <main
    class="relative [min-height:100vh] grid place-items-center [padding:24px_24px_64px] [background:radial-gradient(_circle_at_20%_20%,_rgba(27,_94,_79,_0.12),_transparent_30rem_),_#f5f7f6]"
  >
    <section
      class="[width:min(100%,_448px)] [padding:40px] [border:1px_solid_#dce3df] [border-radius:20px] bg-white [box-shadow:0_24px_64px_rgba(17,_42,_34,_0.12)] [&_form]:grid [&_form]:[gap:10px] [&_label]:grid [&_label]:[gap:10px] [&_form]:[margin:24px_0] [&_form]:[gap:16px] [&_form_input]:text-body [&_input]:w-full [&_input]:[padding:13px_14px] [&_input]:[border:1px_solid_#cfd9d4] [&_input]:rounded-field [&_.password-input]:[height:auto] [&_.password-input]:[border-color:#cfd9d4] [&_.password-input]:rounded-field [&_.password-input_input]:w-full [&_.password-input_input]:h-full [&_.password-input_input]:[padding-right:42px] [&_.password-input_input]:[background:transparent] [&_.password-input_input]:border [&_.password-input_input]:border-line [&_.password-input_input]:rounded-control [&_.password-input_input]:outline-none [&_.password-input_input]:[border-color:#cfd9d4] [&_.password-input_input]:rounded-field [&_button]:justify-center [&>small]:flex [&>small]:items-center [&>small]:[gap:6px]"
    >
      <img
        class="block [width:190px] [height:auto] [margin-bottom:28px]"
        src="/knemora-logo.svg"
        alt="Knemora"
      />
      <form @submit.prevent="submit">
        <label>
          Email
          <input
            v-model="email"
            type="email"
            autocomplete="username"
            required
          />
        </label>
        <label>
          Password
          <PasswordInput
            v-model="password"
            autocomplete="current-password"
            minlength="12"
            required
          />
        </label>
        <div
          v-if="auth.error"
          class="alert alert-danger flex items-center justify-between [gap:16px] [margin:0_0_20px] [padding:12px_15px] rounded-action text-label [&_button]:[color:inherit] [&_button]:[background:transparent] [&_button]:border-0 [&_button]:font-bold [&_button]:underline [color:#7b3525] [background:#fbece6] [border:1px_solid_#efc8bc]"
          role="alert"
        >
          {{ auth.error }}
        </div>
        <button
          class="button button-primary inline-flex [gap:8px] items-center justify-center [min-height:38px] [padding:0_15px] [border:1px_solid_transparent] rounded-action text-label font-bold no-underline [transition:0.16s_ease] text-white bg-brand [box-shadow:0_2px_7px_rgb(51_209_51_/_18%)] hover:text-white hover:bg-brand hover:[opacity:0.82] hover:[transform:translateY(-1px)]"
          type="submit"
          :disabled="auth.loading"
        >
          <LockKeyhole :size="17" />
          {{ auth.loading ? "Signing in…" : "Sign in" }}
        </button>
      </form>
      <p class="[margin:8px_0_14px] text-muted text-label [line-height:1.5]">
        Your session stays on this workstation and expires automatically.
      </p>
      <small
        ><ShieldCheck :size="14" /> Backend-enforced RBAC · Local
        inference</small
      >
    </section>
    <p
      class="absolute [bottom:20px] [left:50%] [width:calc(100%_-_32px)] [transform:translateX(-50%)] m-0 text-muted text-label text-center"
    >
      © 2026 Knemora - MIT-licensed application
    </p>
  </main>
</template>
