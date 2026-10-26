import type { Message } from "../types";

export interface MessageDayGroup {
  key: string;
  label: string | null;
  messages: Message[];
}

function validDate(value?: string | null): Date | null {
  if (!value) return null;
  const normalized =
    /^\d{4}-\d{2}-\d{2}T/.test(value) && !/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value)
      ? `${value}Z`
      : value;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

function calendarKey(date: Date, timeZone?: string): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone,
  }).formatToParts(date);
  const value = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? "";
  return `${value("year")}-${value("month")}-${value("day")}`;
}

function calendarSerial(date: Date, timeZone?: string): number {
  const [year, month, day] = calendarKey(date, timeZone).split("-").map(Number);
  return Date.UTC(year, month - 1, day);
}

function timeLabel(date: Date, timeZone?: string): string {
  return new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZone,
  }).format(date);
}

export function dayLabel(
  value: string | null | undefined,
  now = new Date(),
  timeZone?: string,
): string {
  const date = validDate(value);
  if (!date) return "Date unavailable";
  const difference = Math.round(
    (calendarSerial(now, timeZone) - calendarSerial(date, timeZone)) /
      86_400_000,
  );
  if (difference === 0) return "Today";
  if (difference === 1) return "Yesterday";
  const weekday = new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    timeZone,
  }).format(date);
  const month = new Intl.DateTimeFormat("en-US", {
    month: "short",
    timeZone,
  }).format(date);
  const [year, , day] = calendarKey(date, timeZone).split("-");
  return `${weekday}, ${day} ${month} ${year}`;
}

export function promptTimeLabel(
  value: string | null | undefined,
  now = new Date(),
  timeZone?: string,
): string {
  const date = validDate(value);
  if (!date) return "Time unavailable";
  const sameDay = calendarKey(date, timeZone) === calendarKey(now, timeZone);
  const minutes = Math.floor((now.getTime() - date.getTime()) / 60_000);
  if (sameDay && minutes < 1 && minutes >= 0) return "Just now";
  if (sameDay && minutes < 60 && minutes >= 1) return `${minutes} min ago`;
  const day = dayLabel(value, now, timeZone);
  if (day === "Today" || day === "Yesterday")
    return `${day} at ${timeLabel(date, timeZone)}`;
  return `${day} at ${timeLabel(date, timeZone)}`;
}

export function localDateTimeTitle(
  value: string | null | undefined,
  timeZone?: string,
): string | undefined {
  const date = validDate(value);
  if (!date) return undefined;
  return new Intl.DateTimeFormat("en", {
    dateStyle: "full",
    timeStyle: "long",
    timeZone,
  }).format(date);
}

export function groupMessagesByPromptDay(
  messages: Message[],
  now = new Date(),
  timeZone?: string,
): MessageDayGroup[] {
  const groups: MessageDayGroup[] = [];
  let pending: Message[] = [];
  const appendWithoutBanner = (items: Message[]) => {
    if (!items.length) return;
    groups.push({
      key: `pending-${groups.length}`,
      label: null,
      messages: [...items],
    });
  };
  for (const message of messages) {
    pending.push(message);
    if (message.role !== "assistant") continue;
    const date = validDate(message.created_at);
    if (!date) {
      if (message.content) {
        appendWithoutBanner(pending);
        pending = [];
      }
      continue;
    }
    const key = calendarKey(date, timeZone);
    let group = groups.at(-1);
    if (!group || group.key !== key) {
      group = {
        key,
        label: dayLabel(message.created_at, now, timeZone),
        messages: [],
      };
      groups.push(group);
    }
    group.messages.push(...pending);
    pending = [];
  }
  appendWithoutBanner(pending);
  return groups;
}
