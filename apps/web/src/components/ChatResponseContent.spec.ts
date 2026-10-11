import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import ChatResponseContent from "./ChatResponseContent.vue";

describe("ChatResponseContent", () => {
  it("renders a bounded chart payload alongside Markdown", () => {
    const content = `Revenue by site:\n\n\`\`\`chart\n{"type":"bar","x_column":"site","x":["Malta","Rome"],"series":[{"name":"Revenue","values":[10,14]}]}\n\`\`\``;
    const wrapper = mount(ChatResponseContent, { props: { content } });

    expect(wrapper.text()).toContain("Revenue by site");
    expect(wrapper.get("svg").attributes("aria-label")).toBe(
      "bar chart of site",
    );
    expect(wrapper.findAll("rect")).toHaveLength(2);
  });

  it("falls back to sanitized Markdown for invalid chart data", () => {
    const wrapper = mount(ChatResponseContent, {
      props: { content: '```chart\n{"type":"pie"}\n```' },
    });

    expect(wrapper.find("svg").exists()).toBe(false);
    expect(wrapper.find("pre").exists()).toBe(true);
  });
});
