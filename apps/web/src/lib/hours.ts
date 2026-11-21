/** An agent's working hours (agents.work_hours) and its duty right now, on the client. */
import { msg, t } from "@/i18n";

export interface Break {
  start: string;
  end: string;
}

/** Days are ISO weekdays, Mon=1 .. Sun=7. */
export interface WorkHours {
  tz: string;
  days: number[];
  start: string;
  end: string;
  breaks: Break[];
  urgent_anytime: boolean;
  /** P47: a short summary when its working day ends. */
  day_report?: boolean;
}

export interface Duty {
  state: "working" | "break" | "off" | "always";
  on: boolean;
  until: string | null;
  label: string;
}

/** English keys (they also match Intl's en-US weekday names): render with t(). */
export const DAY_SHORT = [msg("Mon"), msg("Tue"), msg("Wed"), msg("Thu"), msg("Fri"), msg("Sat"), msg("Sun")] as const;

export const mins = (hhmm: string) => {
  const [h, m] = hhmm.split(":").map(Number);
  return (h ?? 0) * 60 + (m ?? 0);
};

/** "Mon–Fri", "Mon, Wed, Fri", "Every day". */
export function daysLabel(days: number[]): string {
  const d = [...days].sort((a, b) => a - b);
  if (d.length === 7) return t("Every day");
  if (!d.length) return t("No days");
  const run = d.length >= 3 && d.every((x, i) => i === 0 || x === d[i - 1]! + 1);
  if (run) return `${t(DAY_SHORT[d[0]! - 1]!)}–${t(DAY_SHORT[d[d.length - 1]! - 1]!)}`;
  return d.map((x) => t(DAY_SHORT[x - 1]!)).join(", ");
}

/** The same one-liner the server writes: "Mon–Fri 09:00–18:00, lunch 13:00–14:00". */
export function describeHours(wh: WorkHours): string {
  let out = `${daysLabel(wh.days)} ${wh.start}–${wh.end}`;
  wh.breaks.forEach((b, i) => {
    const lunch = i === 0 && mins(b.start) >= 660 && mins(b.start) <= 900;
    out += `, ${lunch ? t("lunch {start}–{end}", { start: b.start, end: b.end }) : t("break {start}–{end}", { start: b.start, end: b.end })}`;
  });
  return out;
}
