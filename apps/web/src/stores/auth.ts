import { defineStore } from "pinia";

import { ApiError, api, getAccessToken, setAccessToken } from "../api/client";
import type { CurrentUser } from "../types";

export const useAuthStore = defineStore("auth", {
  state: () => ({
    user: null as CurrentUser | null,
    initialized: false,
    loading: false,
    error: "",
  }),
  getters: {
    authenticated: (state) => state.user !== null,
    can: (state) => (permission: string) =>
      state.user?.permissions.includes(permission) ?? false,
  },
  actions: {
    async initialize() {
      if (!getAccessToken()) {
        this.initialized = true;
        return;
      }
      try {
        this.user = await api.me();
      } catch (error) {
        if (error instanceof ApiError && error.status === 401)
          setAccessToken(null);
      } finally {
        this.initialized = true;
      }
    },
    async login(email: string, password: string) {
      this.loading = true;
      this.error = "";
      try {
        const session = await api.login(email, password);
        setAccessToken(session.access_token);
        this.user = session.user;
      } catch (error) {
        this.error = error instanceof Error ? error.message : "Sign-in failed.";
      } finally {
        this.loading = false;
      }
    },
    async logout() {
      try {
        await api.logout();
      } finally {
        setAccessToken(null);
        this.user = null;
      }
    },
  },
});
