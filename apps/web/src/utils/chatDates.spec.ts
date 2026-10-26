import { describe, expect, it } from "vitest";

import {
  dayLabel,
  groupMessagesByPromptDay,
  promptTimeLabel,
} from "./chatDates";

describe("chat date presentation", () => {
  const zone = "Europe/Malta";
  const now = new Date("2026-09-13T10:00:00Z");

  it("formats recent, today, yesterday, and older prompt times", () => {
    expect(promptTimeLabel("2026-09-13T09:59:40Z", now, zone)).toBe("Just now");
    expect(promptTimeLabel("2026-09-13T09:50:00Z", now, zone)).toBe(
      "10 min ago",
    );
    expect(promptTimeLabel("2026-09-13T07:06:00Z", now, zone)).toBe(
      "Today at 9:06 AM",
    );
    expect(promptTimeLabel("2026-09-12T21:06:00Z", now, zone)).toBe(
      "Yesterday at 11:06 PM",
    );
    expect(dayLabel("2026-09-11T21:06:00Z", now, zone)).toBe(
      "Fri, 11 Sep 2026",
    );
  });

  it("uses the assistant response day when a request crosses local midnight", () => {
    const groups = groupMessagesByPromptDay(
      [
        {
          role: "user",
          content: "Question",
          created_at: "2026-09-12T21:59:00Z",
        },
        {
          role: "assistant",
          content: "Answer",
          created_at: "2026-09-12T22:01:00Z",
        },
      ],
      now,
      zone,
    );
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe("Today");
    expect(groups[0].messages).toHaveLength(2);
  });

  it("does not create a banner until an assistant timestamp is available", () => {
    const pending = groupMessagesByPromptDay(
      [
        { role: "user", content: "Question" },
        { role: "assistant", content: "" },
      ],
      now,
      zone,
    );
    expect(pending).toHaveLength(1);
    expect(pending[0].label).toBeNull();

    const invalid = groupMessagesByPromptDay(
      [
        { role: "user", content: "Question", created_at: "not-a-date" },
        { role: "assistant", content: "Answer", created_at: null },
      ],
      now,
      zone,
    );
    expect(invalid[0].label).toBeNull();

    const afterEstablishedDay = groupMessagesByPromptDay(
      [
        {
          role: "user",
          content: "Earlier question",
          created_at: "2026-09-12T20:00:00Z",
        },
        {
          role: "assistant",
          content: "Earlier answer",
          created_at: "2026-09-12T20:01:00Z",
        },
        { role: "user", content: "Optimistic next-day question" },
        { role: "assistant", content: "" },
      ],
      now,
      zone,
    );
    expect(afterEstablishedDay.map((group) => group.label)).toEqual([
      "Yesterday",
      null,
    ]);
    expect(afterEstablishedDay.map((group) => group.messages.length)).toEqual([
      2, 2,
    ]);
  });

  it("converts UTC and legacy naive UTC through summer, winter, and DST", () => {
    expect(
      promptTimeLabel(
        "2026-07-01T15:00:00+00:00",
        new Date("2026-07-01T18:00:00Z"),
        zone,
      ),
    ).toBe("Today at 5:00 PM");
    expect(
      promptTimeLabel(
        "2026-01-15T16:00:00",
        new Date("2026-01-15T18:00:00Z"),
        zone,
      ),
    ).toBe("Today at 5:00 PM");
    expect(
      promptTimeLabel(
        "2026-03-29T01:30:00Z",
        new Date("2026-03-29T03:00:00Z"),
        zone,
      ),
    ).toBe("Today at 3:30 AM");
  });

  it("uses one banner for same-day responses and a new banner after midnight", () => {
    const groups = groupMessagesByPromptDay(
      [
        { role: "user", content: "One", created_at: "2026-09-12T20:00:00Z" },
        {
          role: "assistant",
          content: "First",
          created_at: "2026-09-12T20:01:00Z",
        },
        { role: "user", content: "Two", created_at: "2026-09-12T20:02:00Z" },
        {
          role: "assistant",
          content: "Second",
          created_at: "2026-09-12T20:03:00Z",
        },
        { role: "user", content: "Three", created_at: "2026-09-12T21:59:00Z" },
        {
          role: "assistant",
          content: "Third",
          created_at: "2026-09-12T22:01:00Z",
        },
      ],
      now,
      zone,
    );
    expect(groups.map((group) => group.label)).toEqual(["Yesterday", "Today"]);
    expect(groups.map((group) => group.messages.length)).toEqual([4, 2]);
  });
});
