/**
 * P97: how a task moves by hand, and due dates. A task given to a person (not an AI agent) may
 * still exist from before; the board treats it like the server does so it only offers moves
 * that work.
 */
import { msg } from "@/i18n";

import type { Task, TaskStatus } from "./work";

export const isPersonTask = (t: Pick<Task, "assignee_user_id">) => !!t.assignee_user_id;

/** A person's task moves by hand (server: PERSON_MOVES). */
export const PERSON_MOVES: Partial<Record<TaskStatus, TaskStatus[]>> = {
  triage: ["ready", "running", "done", "cancelled"],
  ready: ["triage", "running", "done", "cancelled"],
  running: ["ready", "blocked", "review", "done", "cancelled"],
  blocked: ["running", "ready", "done", "cancelled"],
  review: ["done", "running", "cancelled"],
  done: ["running"],
  cancelled: ["triage"],
};

/** An agent's task moves by hand (server: MANUAL_MOVES). Running and blocked are agent-driven. */
export const AGENT_MOVES: Partial<Record<TaskStatus, TaskStatus[]>> = {
  triage: ["ready", "cancelled"],
  ready: ["triage", "cancelled"],
  review: ["done", "cancelled"],
  failed: ["triage", "cancelled"],
  done: ["triage"],
  cancelled: ["triage"],
};

export const movesFor = (t: Task) => (isPersonTask(t) ? PERSON_MOVES : AGENT_MOVES)[t.status] ?? [];
export const canMoveTask = (t: Task | null | undefined, to: TaskStatus) => !!t && movesFor(t).includes(to);

/** What a person's task is called in each state (people take, start and finish work). */
export const PERSON_STATUS: Partial<Record<TaskStatus, string>> = {
  triage: msg("New"),
  ready: msg("To do"),
  running: msg("In progress"),
  blocked: msg("Waiting"),
  review: msg("In review"),
  done: msg("Done"),
  cancelled: msg("Cancelled"),
};

/** The next step a person takes on their own task, as one button. */
export function nextStep(t: Task): { to: TaskStatus; label: string } | null {
  if (t.status === "triage") return { to: "ready", label: msg("Accept") };
  if (t.status === "ready") return { to: "running", label: msg("Start") };
  if (t.status === "running" || t.status === "blocked") return { to: "done", label: msg("Mark done") };
  return null;
}

export type DueTone = "overdue" | "today" | "soon" | "later";

/** How soon a task is due: overdue, today, within 3 days, or later (null: no date or finished). */
export function dueTone(t: Pick<Task, "due_at" | "status">, now = Date.now()): DueTone | null {
  if (!t.due_at || t.status === "done" || t.status === "cancelled") return null;
  const due = new Date(t.due_at);
  const end = new Date(now);
  end.setHours(23, 59, 59, 999);
  if (due.getTime() < now) return "overdue";
  if (due.getTime() <= end.getTime()) return "today";
  if (due.getTime() - now <= 3 * 86_400_000) return "soon";
  return "later";
}

/** A short due label: "Today 17:00", "Fri 14 Nov", "14 Nov 2027". */
export function dueLabel(iso: string, locale?: string, now = Date.now()): string {
  const d = new Date(iso);
  const today = new Date(now);
  const sameDay = d.toDateString() === today.toDateString();
  const time = d.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  if (sameDay) return time;
  const sameYear = d.getFullYear() === today.getFullYear();
  return d.toLocaleDateString(locale, sameYear ? { weekday: "short", day: "numeric", month: "short" } : { day: "numeric", month: "short", year: "numeric" });
}

/** Group tasks for the "Due" view: overdue, today, this week, later, no date. */
export type DueGroup = "overdue" | "today" | "week" | "later" | "none";
export function dueGroup(t: Pick<Task, "due_at" | "status">, now = Date.now()): DueGroup {
  if (!t.due_at) return "none";
  const tone = dueTone(t, now);
  if (tone === "overdue") return "overdue";
  if (tone === "today") return "today";
  return new Date(t.due_at).getTime() - now <= 7 * 86_400_000 ? "week" : "later";
}

/** The end of a day `days` from today at 17:00 local time, as ISO (quick due picks). */
export function dueIn(days: number, now = new Date()): string {
  const d = new Date(now);
  d.setDate(d.getDate() + days);
  d.setHours(17, 0, 0, 0);
  return d.toISOString();
}

/** A board filter value for one assignee: "user:<id>" or "agent:<id>". */
export type AssigneeRef = `user:${string}` | `agent:${string}`;
export const assigneeOf = (t: Task): AssigneeRef | null =>
  t.assignee_user_id ? `user:${t.assignee_user_id}` : t.assignee_agent_id ? `agent:${t.assignee_agent_id}` : null;

