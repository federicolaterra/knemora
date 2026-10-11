import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";

import ConversationsView from "./ConversationsView.vue";

beforeEach(() => {
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      getItem: () => null,
      setItem: () => undefined,
      removeItem: () => undefined,
    },
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("ConversationsView", () => {
  it("renames a conversation from the complete history table", async () => {
    vi.useFakeTimers();
    const conversation = {
      id: "conversation-1",
      user_id: "user-1",
      title: "Original title",
      message_count: 4,
      created_at: "2026-10-08T10:00:00+00:00",
      last_activity_at: "2026-10-08T11:00:00+00:00",
      updated_at: "2026-10-08T11:00:00+00:00",
    };
    const fetchMock = vi.fn(
      (input: string | URL | Request, init?: RequestInit) => {
        const url = new URL(String(input));
        if (
          url.pathname === "/api/v1/conversations/conversation-1" &&
          init?.method === "PATCH"
        ) {
          const body = JSON.parse(String(init.body)) as { title: string };
          return Promise.resolve(
            new Response(
              JSON.stringify({ ...conversation, title: body.title }),
              { status: 200, headers: { "Content-Type": "application/json" } },
            ),
          );
        }
        return Promise.resolve(
          new Response(
            JSON.stringify({
              items: [conversation],
              page: 1,
              page_limit: 15,
              total: 1,
              total_pages: 1,
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        {
          path: "/chat/conversations",
          component: ConversationsView,
        },
        {
          path: "/chat/:id?",
          component: { template: "<div />" },
        },
      ],
    });
    await router.push("/chat/conversations");
    await router.isReady();
    const wrapper = mount(ConversationsView, {
      global: { plugins: [createPinia(), router] },
    });
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();

    await wrapper.get("button[title='Rename conversation']").trigger("click");
    await wrapper
      .get("input[aria-label='Conversation title']")
      .setValue("Renamed title");
    await wrapper.get("button[title='Save title']").trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("Renamed title");
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) =>
          new URL(String(input)).pathname ===
            "/api/v1/conversations/conversation-1" && init?.method === "PATCH",
      ),
    ).toBe(true);
  });
});
