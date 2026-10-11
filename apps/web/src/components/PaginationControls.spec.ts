import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import PaginationControls from "./PaginationControls.vue";

describe("PaginationControls", () => {
  it("shows fixed groups of at most five pages with one-page arrows", async () => {
    const wrapper = mount(PaginationControls, {
      props: { page: 4, total: 112, totalPages: 8 },
    });

    expect(wrapper.find('button[aria-label="Go to page 1"]').exists()).toBe(
      true,
    );
    expect(wrapper.find('button[aria-label="Go to page 5"]').exists()).toBe(
      true,
    );
    expect(wrapper.find('button[aria-label="Go to page 6"]').exists()).toBe(
      false,
    );
    expect(wrapper.text()).toContain("46–60 of 112 records");
    expect(wrapper.find('[aria-current="page"]').text()).toBe("4");

    await wrapper.get('button[aria-label="Go to page 5"]').trigger("click");
    expect(wrapper.emitted("change")).toEqual([[5]]);

    await wrapper.setProps({ page: 6, totalPages: 20, total: 300 });
    expect(wrapper.find('button[aria-label="Go to page 5"]').exists()).toBe(
      false,
    );
    expect(wrapper.find('button[aria-label="Go to page 6"]').exists()).toBe(
      true,
    );
    expect(wrapper.find('button[aria-label="Go to page 10"]').exists()).toBe(
      true,
    );

    await wrapper
      .get('button[aria-label="Go to previous page"]')
      .trigger("click");
    expect(wrapper.emitted("change")?.at(-1)).toEqual([5]);
  });

  it("disables arrows at boundaries and truncates the final group", async () => {
    const wrapper = mount(PaginationControls, {
      props: { page: 18, total: 263, totalPages: 18 },
    });
    expect(
      wrapper
        .findAll('button[aria-label^="Go to page "]')
        .map((button) => button.text()),
    ).toEqual(["16", "17", "18"]);
    expect(
      wrapper
        .get('button[aria-label="Go to next page"]')
        .attributes("disabled"),
    ).toBeDefined();
    await wrapper.setProps({ page: 1 });
    expect(
      wrapper
        .get('button[aria-label="Go to previous page"]')
        .attributes("disabled"),
    ).toBeDefined();
  });
});
