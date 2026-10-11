import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import MarkdownContent from "./MarkdownContent.vue";

describe("MarkdownContent", () => {
  it("renders GFM tables and turns Wiki references into internal links", () => {
    const wrapper = mount(MarkdownContent, {
      props: {
        content:
          "| Site | Score |\n| --- | ---: |\n| Malta | 92 |\n\nSee [[Cold Chain]].",
      },
    });

    expect(wrapper.find("table").exists()).toBe(true);
    expect(wrapper.get("a").attributes("href")).toBe("/knowledge/Cold%20Chain");
  });

  it("sanitizes active content from untrusted model output", () => {
    const wrapper = mount(MarkdownContent, {
      props: {
        content: '<img src="x" onerror="alert(1)"><script>alert(2)</script>',
      },
    });

    expect(wrapper.html()).not.toContain("onerror");
    expect(wrapper.html()).not.toContain("script");
  });
});
