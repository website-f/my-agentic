/** Every email account in one place (api/routers/inbox.py): Microsoft 365, Gmail and IMAP
 * accounts behind one shape, plus the AI helpers that read and write mail with you. */
import { queryOptions } from "@tanstack/react-query";

import { api } from "./api";

export type InboxProvider = "microsoft" | "google" | "imap";

export interface InboxAccount {
  /** "ms:<id>", "g:<id>" or "x:<id>". */
  key: string;
  provider: InboxProvider;
  email: string;
  label: string;
  status: "ok" | "error" | "needs_reconnect";
  primary: boolean;
  can_send: boolean;
  error: string | null;
}

export interface InboxFolder {
  id: string;
  name: string;
}

export interface InboxAccounts {
  accounts: InboxAccount[];
  folders: InboxFolder[];
  connect: { microsoft: boolean; google: boolean; imap: boolean };
}

export interface Addr {
  name: string;
  address: string;
}

export interface InboxRow {
  id: string;
  account: string;
  conversation_id: string | null;
  subject: string;
  from: Addr;
  to: Addr[];
  cc: Addr[];
  received_at: string;
  is_read: boolean;
  is_draft: boolean;
  has_attachments: boolean;
  flagged: boolean;
  preview: string;
  web_link: string | null;
}

export interface InboxAttachment {
  id: string;
  name: string;
  size: number;
  content_type: string;
  inline: boolean;
}

export interface InboxMessage extends InboxRow {
  body_html: string;
  body_text: string;
  reply_to: Addr[];
  attachments: InboxAttachment[];
}

export interface InboxPage {
  items: InboxRow[];
  next: string | null;
  problems?: { account: string; error: string }[];
}

/** "All inboxes": the newest mail of every account, merged (no paging). */
export const ALL = "all";

export interface ListArgs {
  account: string;
  folder: string;
  q: string;
  unread: boolean;
}

export const inboxKeys = {
  all: ["inbox"] as const,
  accounts: ["inbox", "accounts"] as const,
  list: (a: ListArgs) => ["inbox", "list", a] as const,
  message: (account: string, id: string) => ["inbox", "message", account, id] as const,
};

export const accountsQuery = queryOptions({
  queryKey: inboxKeys.accounts,
  queryFn: () => api<InboxAccounts>("/api/inbox/accounts"),
  staleTime: 60_000,
});

/** The query string for one page of a folder. */
export function listPath(a: ListArgs, cursor?: string | null, top = 25): string {
  const p = new URLSearchParams({ account: a.account, folder: a.folder, top: String(top) });
  if (a.q.trim()) p.set("q", a.q.trim());
  if (a.unread) p.set("unread", "true");
  if (cursor) p.set("cursor", cursor);
  return `/api/inbox/messages?${p.toString()}`;
}

const mid = (id: string) => encodeURIComponent(id);
const acc = (account: string) => `account=${encodeURIComponent(account)}`;

export const messageQuery = (account: string, id: string) =>
  queryOptions({
    queryKey: inboxKeys.message(account, id),
    queryFn: () => api<InboxMessage>(`/api/inbox/messages/${mid(id)}?${acc(account)}`),
    staleTime: 5 * 60_000,
  });

export const attachmentUrl = (account: string, id: string, aid: string) =>
  `/api/inbox/messages/${mid(id)}/attachments/${encodeURIComponent(aid)}?${acc(account)}`;

export const markRead = (account: string, id: string, read: boolean) =>
  api<unknown>(`/api/inbox/messages/${mid(id)}/read`, "POST", { account, read });

export const trashMessage = (account: string, id: string) => api<unknown>(`/api/inbox/messages/${mid(id)}/trash`, "POST", { account });

export interface SendIn {
  account: string;
  to: string[];
  cc: string[];
  subject: string;
  body: string;
  reply_to_id?: string | null;
  reply_all?: boolean;
  forward_id?: string | null;
  draft?: boolean;
}

export const sendMail = (body: SendIn) => api<{ sent: boolean; draft_id: string | null }>("/api/inbox/send", "POST", body);

export type AiAction = "summarize" | "reply" | "improve" | "compose" | "ask";
export type Tone = "" | "friendly" | "formal" | "short" | "firm" | "apologetic";

export interface AiIn {
  account: string;
  message_id?: string;
  action: AiAction;
  instructions?: string;
  draft?: string;
  tone?: Tone;
  lang?: "" | "en" | "ms";
}

export const askAi = (body: AiIn) => api<{ text: string; subject: string }>("/api/inbox/ai", "POST", body);

/** Remove an account from the inbox: Gmail and IMAP here, Microsoft through its own connection. */
export function removeAccount(key: string) {
  if (key.startsWith("ms:")) return api<unknown>(`/api/integrations/microsoft/accounts/${encodeURIComponent(key.slice(3))}`, "DELETE");
  return api<unknown>(`/api/inbox/accounts/${encodeURIComponent(key)}`, "DELETE");
}

export const connectMicrosoft = () => api<{ url: string }>("/api/integrations/microsoft/connect", "POST", { another: true });
export const connectGoogle = () => api<{ url: string }>("/api/integrations/google/connect", "POST");

export type ImapProvider = "gmail" | "yahoo" | "outlook" | "cpanel" | "other";

export interface ImapPreset {
  host: string;
  port: number;
  security: "ssl" | "starttls";
}

export interface MailAccountsHome {
  presets: Record<string, ImapPreset>;
  smtp_presets: Record<string, ImapPreset>;
}

export const mailAccountsQuery = queryOptions({
  queryKey: ["mail-accounts"] as const,
  queryFn: () => api<MailAccountsHome>("/api/mail-accounts"),
  staleTime: 5 * 60_000,
});

export interface ImapIn {
  email: string;
  provider: ImapProvider;
  host: string;
  port: number;
  security: "ssl" | "starttls";
  username: string;
  password: string;
  smtp_host: string;
  smtp_port: number | null;
  smtp_security: "ssl" | "starttls" | null;
  label: string;
}

export const addImapAccount = (body: ImapIn) => api<unknown>("/api/mail-accounts", "POST", body);

// ---------------------------------------------------------------- small helpers (pure)

/** "Hana Ismail <hana@x.com>" lists as typed into To/Cc: split on commas and semicolons. */
export function splitAddresses(text: string): string[] {
  return text
    .split(/[,;\n]/)
    .map((s) => s.trim())
    .map((s) => /<([^>]+)>/.exec(s)?.[1]?.trim() ?? s)
    .filter((s) => s.includes("@"));
}

export const showAddr = (a: Addr | null | undefined) => (a ? a.name || a.address : "");

/** The subject a reply or forward starts with ("Re: …", "Fwd: …"), without doubling it. */
export function prefixed(prefix: "Re" | "Fwd", subject: string): string {
  const s = subject.trim();
  return new RegExp(`^${prefix}:`, "i").test(s) ? s : `${prefix}: ${s}`;
}

/** Today: the time; this year: day and month; older: the date. */
export function shortWhen(iso: string, now = new Date(), locale?: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  if (d.getFullYear() === now.getFullYear()) return d.toLocaleDateString(locale, { day: "numeric", month: "short" });
  return d.toLocaleDateString(locale, { day: "numeric", month: "short", year: "numeric" });
}

/** A mail body for a sandboxed frame: no scripts can run there; links open in a new tab. Mail is
 * written for a white page, so it keeps one in the dark theme too. */
export function frameDoc(html: string, text: string): string {
  const body = html.trim() ? html : `<pre>${escapeHtml(text)}</pre>`;
  return `<!doctype html><html><head><meta charset="utf-8"><base target="_blank"><meta name="viewport" content="width=device-width, initial-scale=1"><style>html,body{margin:0;padding:0}body{color:#1a1a1a;background:#ffffff;font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;padding:16px;word-wrap:break-word;overflow-wrap:anywhere}img{max-width:100%;height:auto}pre{white-space:pre-wrap;font:inherit}table{max-width:100%}a{color:#13895f}blockquote{margin:0 0 0 8px;padding-left:8px;border-left:2px solid #ccc}</style></head><body>${body}</body></html>`;
}

export function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

export function fileSizeShort(n: number): string {
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}
