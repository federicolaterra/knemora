import type { Message } from "../types";

export interface MessageDayGroup {
  key: string;
  label: string;
  messages: Message[];
}

function validDate(value?: string | null): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function calendarKey(date: Date): string {
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

function calendarSerial(date: Date): number {
  return Date.UTC(date.getFullYear(), date.getMonth(), date.getDate());
}

function timeLabel(date: Date): string {
  return new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(date);
}

export function dayLabel(
  value: string | null | undefined,
  now = new Date(),
): string {
  const date = validDate(value);
  if (!date) return "Date unavailable";
  const difference = Math.round(
    (calendarSerial(now) - calendarSerial(date)) / 86_400_000,
  );
  if (difference === 0) return "Today";
  if (difference === 1) return "Yesterday";
  const weekday = new Intl.DateTimeFormat("en-US", { weekday: "short" }).format(
    date,
  );
  const month = new Intl.DateTimeFormat("en-US", { month: "short" }).format(
    date,
  );
  return `${weekday}, ${String(date.getDate()).padStart(2, "0")} ${month} ${date.getFullYear()}`;
}

export function promptTimeLabel(
  value: string | null | undefined,
  now = new Date(),
): string {
  const date = validDate(value);
  if (!date) return "Time unavailable";
  const sameDay = calendarKey(date) === calendarKey(now);
  const minutes = Math.floor((now.getTime() - date.getTime()) / 60_000);
  if (sameDay && minutes < 1 && minutes >= 0) return "Just now";
  if (sameDay && minutes < 60 && minutes >= 1) return `${minutes} min ago`;
  const day = dayLabel(value, now);
  if (day === "Today" || day === "Yesterday")
    return `${day} at ${timeLabel(date)}`;
  return `${day} at ${timeLabel(date)}`;
}

export function groupMessagesByPromptDay(
  messages: Message[],
  now = new Date(),
): MessageDayGroup[] {
  const groups: MessageDayGroup[] = [];
  let anchor: string | null | undefined;
  for (const message of messages) {
    if (message.role === "user" || anchor === undefined)
      anchor = message.created_at;
    const date = validDate(anchor);
    const key = date ? calendarKey(date) : "undated";
    let group = groups.at(-1);
    if (!group || group.key !== key) {
      group = { key, label: dayLabel(anchor, now), messages: [] };
      groups.push(group);
    }
    group.messages.push(message);
  }
  return groups;
}
