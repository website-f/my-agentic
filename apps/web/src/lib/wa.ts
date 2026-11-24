/** WhatsApp chats of the connected number (api/routers/wa_chats.py), and where the AI answers. */
import { queryOptions } from "@tanstack/react-query";

import { api } from "./api";

export interface WaStatus {
  connected: boolean;
  channel_id: string | null;
  status: "WORKING" | "SCAN_QR_CODE" | "STOPPED" | "FAILED" | "MISSING" | "UNREACHABLE" | string;
  me: { id: string; pushName: string } | null;
  /** Phone numbers linked to the owner (so the AI knows it is them). */
  links: { id: string; number: string }[];
}

/** Who the AI answers in a chat: nobody, only the owner, or everyone. */
export type AiMode = "off" | "me" | "everyone";

export interface WaChat {
  id: string;
  name: string;
  group: boolean;
  picture: string | null;
  unread: number;
  last: { text: string; from_me: boolean; at: string; media: boolean } | null;
  ai: AiMode;
}

export interface WaMessage {
  id: string;
  from_me: boolean;
  sender: string;
  sender_name: string | null;
  text: string;
  at: string;
  ack: number | null;
  media: { mimetype: string; filename: string | null; url: string | null } | null;
  reply_to: { id: string; text: string } | null;
  /** Written by the AI. */
  ai: boolean;
}

export interface WaRule {
  mode: AiMode;
  agent_id: string | null;
  instructions: string;
  saved?: boolean;
}

const cid = (id: string) => encodeURIComponent(id);

export const waKeys = {
  all: ["wa"] as const,
  status: ["wa", "status"] as const,
  chats: ["wa", "chats"] as const,
  messages: (id: string) => ["wa", "messages", id] as const,
  rule: (id: string) => ["wa", "rule", id] as const,
  members: ["wa", "members"] as const,
  pickChats: ["wa", "chats", "pick"] as const,
};

export const waStatusQuery = queryOptions({
  queryKey: waKeys.status,
  queryFn: () => api<WaStatus>("/api/wa/status"),
  staleTime: 30_000,
});

export const chatsQuery = (enabled: boolean) =>
  queryOptions({
    queryKey: waKeys.chats,
    queryFn: () => api<{ chats: WaChat[]; next: number | string | null }>("/api/wa/chats?limit=50&offset=0"),
    refetchInterval: 10_000,
    enabled,
  });

export const messagesQuery = (id: string) =>
  queryOptions({
    queryKey: waKeys.messages(id),
    queryFn: () => api<{ messages: WaMessage[] }>(`/api/wa/chats/${cid(id)}/messages?limit=60`),
    refetchInterval: 4000,
  });

export const ruleQuery = (id: string) =>
  queryOptions({ queryKey: waKeys.rule(id), queryFn: () => api<WaRule>(`/api/wa/chats/${cid(id)}/rule`) });

export const sendWa = (id: string, text: string, replyTo?: string | null) =>
  api<{ id: string }>(`/api/wa/chats/${cid(id)}/messages`, "POST", { text, ...(replyTo ? { reply_to: replyTo } : {}) });

export const markSeen = (id: string) => api<{ seen: boolean }>(`/api/wa/chats/${cid(id)}/seen`, "POST");

export const saveRule = (id: string, rule: WaRule & { name: string }) =>
  api<WaRule>(`/api/wa/chats/${cid(id)}/rule`, "PUT", { mode: rule.mode, agent_id: rule.agent_id, instructions: rule.instructions, name: rule.name });

export const chatAi = (id: string, action: "draft" | "summarize", instructions: string, name: string) =>
  api<{ text: string }>(`/api/wa/chats/${cid(id)}/ai`, "POST", { action, instructions, name });

export const linkCode = (channelId: string) =>
  api<{ code: string; url: string | null; expires_in?: number }>(`/api/channels/${channelId}/link-code`, "POST");

// ---------------------------------------------------------------- people with access

/** What the AI may do for someone else: just talk, use its tools, or everything (like the owner). */
export type WaLevel = "chat" | "assistant" | "full";

/** Another WhatsApp number the owner lets instruct the AI, with its level and daily limits. */
export interface WaMember {
  id: string;
  /** Digits only, with the country code ("60123456789"). */
  number: string;
  name: string;
  level: WaLevel;
  /** 0 = no limit. */
  daily_messages: number;
  /** 0 = no limit. */
  daily_tokens: number;
  /** Chat ids where they may use the AI; empty = every chat. */
  chats: string[];
  enabled: boolean;
  expires_at: string | null;
  notes: string;
  /** They have messaged the number at least once (so they are recognised in groups too). */
  seen_lid: boolean;
  used_today: { messages: number; tokens: number };
  created_at: string | null;
}

export interface WaMemberInput {
  number: string;
  name: string;
  level: WaLevel;
  daily_messages: number;
  daily_tokens: number;
  chats: string[];
  enabled: boolean;
  expires_at: string | null;
  notes: string;
}

export type WaMemberPatch = Partial<Omit<WaMemberInput, "number">> & { clear_expiry?: boolean };

export const membersQuery = queryOptions({
  queryKey: waKeys.members,
  queryFn: () => api<{ members: WaMember[] }>("/api/wa/members"),
});

/** Chats to pick from when limiting someone to some chats. */
export const pickChatsQuery = queryOptions({
  queryKey: waKeys.pickChats,
  queryFn: () => api<{ chats: WaChat[] }>("/api/wa/chats?limit=100"),
  staleTime: 60_000,
});

export const addMember = (body: WaMemberInput) => api<WaMember>("/api/wa/members", "POST", body);
export const updateMember = (id: string, body: WaMemberPatch) => api<WaMember>(`/api/wa/members/${cid(id)}`, "PATCH", body);
export const removeMember = (id: string) => api<void>(`/api/wa/members/${cid(id)}`, "DELETE");

/** The number as the server will keep it: digits only, a local "012…" read as Malaysian (6012…). */
export function cleanNumber(raw: string): string {
  const s = raw.trim();
  const digits = s.replace(/\D/g, "");
  return s.startsWith("0") && !s.startsWith("00") ? `6${digits}` : digits;
}

/** "45k", "1.5k", "2M": a token count short enough for a list row. */
export function shortCount(n: number): string {
  const fmt = (v: number) => (v < 10 ? String(Math.round(v * 10) / 10) : String(Math.round(v)));
  if (n < 1000) return String(Math.round(n));
  if (n < 1_000_000) return `${fmt(n / 1000)}k`;
  return `${fmt(n / 1_000_000)}M`;
}

/** How full today's allowance is, 0-100 (0 when there is no limit). */
export const usedPct = (used: number, limit: number) => (limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0);

/** A rough "20-40" normal answers for a daily token allowance (5k-10k tokens an answer). */
export function answersFor(tokens: number): string {
  const lo = Math.max(1, Math.floor(tokens / 10_000));
  const hi = Math.max(1, Math.floor(tokens / 5_000));
  return lo === hi ? String(lo) : `${lo}-${hi}`;
}

/** Access that ran out (its end date has passed). */
export const isExpired = (m: Pick<WaMember, "expires_at">, now = Date.now()) => !!m.expires_at && new Date(m.expires_at).getTime() < now;

/** "2026-12-31" (a date input's value) -> the end of that day, local time, as ISO. */
export const endOfDayIso = (day: string) => new Date(`${day}T23:59:59`).toISOString();

/** ISO -> "2026-12-31" in local time, for a date input. */
export function dayOf(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** "+60 12-345 6789" from "60123456789" (as the Channels page shows numbers). */
export const prettyNumber = (n: string | null | undefined) => (n ? `+${n.replace(/^(\d{2})(\d{2})(\d{3,4})(\d{4})$/, "$1 $2-$3 $4")}` : "");

/** The phone number part of a WhatsApp id ("60123456789@c.us" -> "60123456789"). */
export const numberOf = (id: string) => id.split("@")[0] ?? id;

/** Messages grouped by day, for the date chips between them. */
export function byDay(messages: WaMessage[]): { day: string; items: WaMessage[] }[] {
  const out: { day: string; items: WaMessage[] }[] = [];
  for (const m of messages) {
    const day = new Date(m.at).toDateString();
    const last = out[out.length - 1];
    if (last && last.day === day) last.items.push(m);
    else out.push({ day, items: [m] });
  }
  return out;
}
