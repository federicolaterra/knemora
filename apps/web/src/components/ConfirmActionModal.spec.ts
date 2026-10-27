import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import ConfirmActionModal from "./ConfirmActionModal.vue";

describe("ConfirmActionModal", () => {
  it("uses the warning treatment and emits confirmation", async () => {
    const wrapper = mount(ConfirmActionModal, {
      props: {
        title: "Reprocess source?",
        description: "Rebuild the compiled knowledge.",
        confirmLabel: "Reprocess",
        tone: "warning",
      },
    });

    const dialog = wrapper.get("[role='dialog']");
    expect(dialog.attributes("aria-labelledby")).toBeTruthy();
    expect(dialog.find("span").classes()).toContain("text-[#F4A440]");

    await dialog.get("button[autofocus]").trigger("click");
    expect(wrapper.emitted("confirm")).toHaveLength(1);
  });

  it("does not close while an action is busy", async () => {
    const wrapper = mount(ConfirmActionModal, {
      props: {
        title: "Delete source?",
        description: "Delete the immutable source.",
        busy: true,
        busyLabel: "Deleting…",
      },
    });

    expect(wrapper.text()).toContain("Deleting…");
    await wrapper.get("[role='presentation']").trigger("click");
    expect(wrapper.emitted("close")).toBeUndefined();
  });
});
