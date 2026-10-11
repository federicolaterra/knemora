import { describe, expect, it } from "vitest";

import {
  dayLabel,
  groupMessagesByPromptDay,
  promptTimeLabel,
} from "./chatDates";

describe("chat date presentation", () => {
  const now = new Date(2026, 8, 13, 12, 0);

  it("formats recent, today, yesterday, and older prompt times", () => {
    expect(
      promptTimeLabel(new Date(2026, 8, 13, 11, 59, 40).toISOString(), now),
    ).toBe("Just now");
    expect(
      promptTimeLabel(new Date(2026, 8, 13, 11, 50).toISOString(), now),
    ).toBe("10 min ago");
    expect(
      promptTimeLabel(new Date(2026, 8, 13, 9, 6).toISOString(), now),
    ).toBe("Today at 9:06 AM");
    expect(
      promptTimeLabel(new Date(2026, 8, 12, 23, 6).toISOString(), now),
    ).toBe("Yesterday at 11:06 PM");
    expect(dayLabel(new Date(2026, 8, 11, 23, 6).toISOString(), now)).toBe(
      "Fri, 11 Sep 2026",
    );
  });

  it("keeps an assistant response crossing midnight with its prompt", () => {
    const groups = groupMessagesByPromptDay(
      [
        {
          role: "user",
          content: "Question",
          created_at: new Date(2026, 8, 12, 23, 59).toISOString(),
        },
        {
          role: "assistant",
          content: "Answer",
          created_at: new Date(2026, 8, 13, 0, 1).toISOString(),
        },
      ],
      now,
    );
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe("Yesterday");
    expect(groups[0].messages).toHaveLength(2);
  });
});
