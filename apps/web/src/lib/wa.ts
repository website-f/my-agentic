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
