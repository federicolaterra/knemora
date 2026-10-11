import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import PasswordInput from "./PasswordInput.vue";

describe("PasswordInput", () => {
  it("shows and hides a password without changing its value", async () => {
    const wrapper = mount(PasswordInput, {
      props: { modelValue: "local-password" },
    });

    expect(wrapper.get("input").attributes("type")).toBe("password");
    await wrapper.get('button[aria-label="Show password"]').trigger("click");
    expect(wrapper.get("input").attributes("type")).toBe("text");
    expect(wrapper.get("input").element.value).toBe("local-password");
    await wrapper.get('button[aria-label="Hide password"]').trigger("click");
    expect(wrapper.get("input").attributes("type")).toBe("password");
  });
});
