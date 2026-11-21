/** WhatsApp from the connected number, WhatsApp-web-like: chats on the left, the conversation on
 * the right (on a phone: one at a time), and per chat where the AI answers when mentioned. */
import {
  ArrowBendUpLeftIcon,
  ArrowLeftIcon,
  CheckIcon,
  ChecksIcon,
  FileIcon,
  ListBulletsIcon,
  PaperPlaneRightIcon,
  RobotIcon,
  SparkleIcon,
  UsersThreeIcon,
  WarningIcon,
  WhatsappLogoIcon,
  XIcon,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Markdown } from "@/components/markdown";
import { EmptyState } from "@/components/page";
import { Button } from "@/components/ui/button";
import { ResponsiveDialog } from "@/components/ui/dialog";
import { SearchInput } from "@/components/ui/search-input";
import { Segmented } from "@/components/ui/segmented";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { locale, useT } from "@/i18n";
import { errorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  byDay,
  chatAi,
  chatsQuery,
  linkCode,
  markSeen,
  messagesQuery,
  numberOf,
  prettyNumber,
  ruleQuery,
  saveRule,
  sendWa,
  waKeys,
  waStatusQuery,
  type AiMode,
  type WaChat,
  type WaMessage,
  type WaStatus,
} from "@/lib/wa";
import { agentsQuery } from "@/lib/work";

const FULL_H = "h-[calc(100dvh-3.5rem-env(safe-area-inset-top)-4.5rem-env(safe-area-inset-bottom))] md:h-[calc(100dvh-3.5rem-env(safe-area-inset-top))]";

const time = (iso: string) => new Date(iso).toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });

function whenShort(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return time(iso);
  return d.toLocaleDateString(locale(), { day: "numeric", month: "short" });
}

export function WhatsAppPage() {
  const t = useT();
  const navigate = useNavigate();
  const search = useSearch({ strict: false }) as { chat?: string };
  const status = useQuery(waStatusQuery);
  const connected = !!status.data?.connected;
  const chats = useQuery(chatsQuery(connected));
  const [q, setQ] = useState("");
  const open = search.chat;
  const list = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const all = chats.data?.chats ?? [];
    return needle ? all.filter((c) => `${c.name} ${numberOf(c.id)}`.toLowerCase().includes(needle)) : all;
  }, [chats.data, q]);
  const openChat = open ? (chats.data?.chats.find((c) => c.id === open) ?? { id: open, name: numberOf(open), group: open.endsWith("@g.us"), picture: null, unread: 0, last: null, ai: "me" as AiMode }) : null;

  if (status.isLoading) return <div className="p-4 sm:p-6"><Skeleton className="h-[70dvh] rounded-[var(--radius-md)]" /></div>;
  if (status.error) return <p role="alert" className="p-6 text-danger">{errorMessage(status.error)}</p>;
  if (!connected || !status.data) return <NotConnected status={status.data} />;

  return (
    <div className={cn("flex min-h-[26rem] min-w-0", FULL_H)}>
      <section aria-label={t("Chats")} className={cn("min-w-0 flex-col border-r border-border bg-surface md:flex md:w-[22rem] md:shrink-0", open ? "hidden" : "flex w-full")}>
        <div className="grid shrink-0 gap-2 border-b border-border p-3">
          <div className="flex items-center gap-2">
            <WhatsappLogoIcon size={20} weight="fill" className="text-[#25d366]" />
            <p className="min-w-0 flex-1 truncate text-[14px] font-semibold">{status.data.me?.pushName || prettyNumber(numberOf(status.data.me?.id ?? ""))}</p>
          </div>
          <SearchInput value={q} onChange={setQ} placeholder={t("Search chats")} className="basis-0" />
        </div>
        {!status.data.links.length ? <LinkHint status={status.data} /> : null}
        <div className="min-h-0 flex-1 overflow-y-auto">
          {chats.isLoading ? (
            <div className="grid">{[0, 1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="m-2 h-12" />)}</div>
          ) : chats.error ? (
            <p role="alert" className="p-4 text-[13px] text-danger">{errorMessage(chats.error)}</p>
          ) : !list.length ? (
            <p className="p-6 text-center text-[13px] text-muted">{q ? t("No chat matches.") : t("No chats yet.")}</p>
          ) : (
            <ul>
              {list.map((c) => (
                <li key={c.id}><ChatRow chat={c} active={c.id === open} onOpen={() => void navigate({ to: "/whatsapp", search: { chat: c.id } })} /></li>
              ))}
            </ul>
          )}
        </div>
      </section>
      <section aria-label={t("Conversation")} className={cn("min-w-0 flex-1 flex-col bg-bg", open ? "flex" : "hidden md:flex")}>
        {openChat ? (
          <Conversation key={openChat.id} chat={openChat} onBack={() => void navigate({ to: "/whatsapp", search: {} })} />
        ) : (
          <div className="grid flex-1 place-items-center p-6 text-center text-[13px] text-muted">
            <span className="grid max-w-xs justify-items-center gap-2">
              <WhatsappLogoIcon size={36} weight="duotone" className="text-border" />
              {t("Pick a chat. In each chat you choose whether your AI answers, and for whom.")}
            </span>
          </div>
        )}
      </section>
    </div>
  );
}

function NotConnected({ status }: { status: WaStatus | undefined }) {
  const t = useT();
  return (
    <div className="grid place-items-center p-6">
      <EmptyState icon={WhatsappLogoIcon} title={t("Connect WhatsApp")}
        body={status?.status === "SCAN_QR_CODE"
          ? t("WhatsApp is waiting for its QR code to be scanned. Open Settings > Channels > WhatsApp and scan it with the phone.")
          : t("Connect a WhatsApp number first: Settings > Channels > WhatsApp, then scan the QR code with the phone.")}
        action={<Button asChild><Link to="/channels">{t("Open Channels")}</Link></Button>} />
    </div>
  );
}

/** No phone of the owner's is linked yet: one code, sent from their phone, links it. */
function LinkHint({ status }: { status: WaStatus }) {
  const t = useT();
  const qc = useQueryClient();
  const [code, setCode] = useState<{ code: string; url: string | null } | null>(null);
  const get = useMutation({
    mutationFn: () => linkCode(status.channel_id ?? ""),
    onSuccess: setCode,
    onError: (e) => toast.error(errorMessage(e)),
  });
  useEffect(() => {
    if (!code) return;
    const poll = setInterval(() => void qc.invalidateQueries({ queryKey: waKeys.status }), 5000);
    const stop = setTimeout(() => clearInterval(poll), 10 * 60_000);
    return () => { clearInterval(poll); clearTimeout(stop); };
  }, [code, qc]);
  const number = prettyNumber(numberOf(status.me?.id ?? ""));
  return (
    <div className="m-3 grid gap-2 rounded-[var(--radius-md)] border border-accent/30 bg-accent-soft/40 p-3 text-[12.5px]">
      <p className="font-medium">{t("Link your own phone number so the AI knows it's you.")}</p>
      {code ? (
        <>
          <p>{t("From your phone, send this to {number}:", { number })}</p>
          <p className="rounded-sm bg-surface px-3 py-2 text-center font-mono text-[16px] font-semibold tracking-[0.15em] select-all">LINK {code.code}</p>
          {code.url ? <Button size="sm" asChild><a href={code.url} target="_blank" rel="noreferrer"><WhatsappLogoIcon size={15} /> {t("Open WhatsApp")}</a></Button> : null}
          <p className="flex items-center gap-1.5 text-[11.5px] text-muted"><span className="size-1.5 animate-pulse rounded-full bg-accent" /> {t("Waiting for your message… (code valid 10 minutes)")}</p>
        </>
      ) : (
        <Button size="sm" variant="outline" className="justify-self-start" loading={get.isPending} disabled={!status.channel_id} onClick={() => get.mutate()}>{t("Get a link code")}</Button>
      )}
    </div>
  );
}

function Avatar({ chat, size = 40 }: { chat: Pick<WaChat, "name" | "picture" | "group">; size?: number }) {
  const [broken, setBroken] = useState(false);
  if (chat.picture && !broken) {
    return <img src={chat.picture} alt="" width={size} height={size} onError={() => setBroken(true)} className="shrink-0 rounded-full object-cover" style={{ width: size, height: size }} />;
  }
  return (
    <span aria-hidden className="grid shrink-0 place-items-center rounded-full bg-[#25d366]/15 text-[13px] font-semibold text-[#128c4a]" style={{ width: size, height: size }}>
      {chat.group ? <UsersThreeIcon size={size / 2} /> : (chat.name.trim()[0] ?? "?").toUpperCase()}
    </span>
  );
}

const AI_LABEL: Record<AiMode, string> = { off: "AI off", me: "AI: only me", everyone: "AI: everyone" };

function ChatRow({ chat, active, onOpen }: { chat: WaChat; active: boolean; onOpen: () => void }) {
  const t = useT();
  return (
    <button type="button" onClick={onOpen} aria-current={active ? "true" : undefined}
      className={cn("flex w-full min-w-0 items-center gap-3 px-3 py-2.5 text-left transition-colors", active ? "bg-accent-soft/60" : "hover:bg-surface-2/60")}>
      <Avatar chat={chat} />
      <span className="grid min-w-0 flex-1 gap-0.5">
        <span className="flex min-w-0 items-center gap-2">
          <span className={cn("min-w-0 flex-1 truncate text-[14px]", chat.unread ? "font-semibold" : "font-medium")}>{chat.name || numberOf(chat.id)}</span>
          {chat.last ? <time className={cn("shrink-0 text-[11px] tabular", chat.unread ? "text-[#128c4a]" : "text-muted")}>{whenShort(chat.last.at)}</time> : null}
        </span>
        <span className="flex min-w-0 items-center gap-1.5">
          <span className="min-w-0 flex-1 truncate text-[12.5px] text-muted">
            {chat.last ? `${chat.last.from_me ? `${t("You")}: ` : ""}${chat.last.text || (chat.last.media ? t("Media") : "")}` : ""}
          </span>
          {chat.ai !== "off" ? <span title={t(AI_LABEL[chat.ai])} className="shrink-0"><RobotIcon size={13} className={chat.ai === "everyone" ? "text-warn" : "text-accent"} /></span> : null}
          {chat.unread ? <span className="grid h-[18px] min-w-[18px] shrink-0 place-items-center rounded-full bg-[#25d366] px-1 text-[10.5px] font-semibold text-white tabular">{chat.unread}</span> : null}
        </span>
      </span>
    </button>
  );
}

function Conversation({ chat, onBack }: { chat: WaChat; onBack: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery(messagesQuery(chat.id));
  const [text, setText] = useState("");
  const [replyTo, setReplyTo] = useState<WaMessage | null>(null);
  const [summary, setSummary] = useState<string | null>(null);
  const [ruleOpen, setRuleOpen] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const messages = useMemo(() => data?.messages ?? [], [data]);
  const lastId = messages[messages.length - 1]?.id;

  // Opening a chat marks it read.
  useEffect(() => {
    markSeen(chat.id).then(() => qc.invalidateQueries({ queryKey: waKeys.chats })).catch(() => {});
  }, [chat.id, qc]);
  // Keep the newest message in view.
  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lastId]);

  const send = useMutation({
    mutationFn: () => sendWa(chat.id, text.trim(), replyTo?.id),
    onSuccess: () => {
      setText("");
      setReplyTo(null);
      void qc.invalidateQueries({ queryKey: waKeys.messages(chat.id) });
      void qc.invalidateQueries({ queryKey: waKeys.chats });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const ai = useMutation({
    mutationFn: (action: "draft" | "summarize") => chatAi(chat.id, action, action === "draft" ? text.trim() : "", chat.name),
    onSuccess: (r, action) => {
      if (action === "draft") {
        setText(r.text);
        box.current?.focus();
      } else setSummary(r.text);
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 items-center gap-2.5 border-b border-border bg-surface px-3 py-2">
        <Button variant="ghost" size="icon-sm" className="-ml-1 md:hidden" aria-label={t("Back")} onClick={onBack}><ArrowLeftIcon size={17} /></Button>
        <Avatar chat={chat} size={34} />
        <div className="grid min-w-0 flex-1">
          <p className="truncate text-[14px] font-semibold">{chat.name || numberOf(chat.id)}</p>
          <p className="truncate text-[11.5px] text-muted">{chat.group ? t("Group") : prettyNumber(numberOf(chat.id))}</p>
        </div>
        <Button size="sm" variant="ghost" onClick={() => ai.mutate("summarize")} loading={ai.isPending && ai.variables === "summarize"} title={t("Summarize chat")}>
          <ListBulletsIcon size={15} /> <span className="max-sm:sr-only">{t("Summarize")}</span>
        </Button>
        <Button size="sm" variant="outline" onClick={() => setRuleOpen(true)} title={t("AI in this chat")}>
          <RobotIcon size={15} className={chat.ai === "everyone" ? "text-warn" : chat.ai === "me" ? "text-accent" : "text-muted"} />
          <span className="max-sm:sr-only">{t(AI_LABEL[chat.ai])}</span>
        </Button>
      </header>

      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto bg-surface-2/40 px-3 py-3 sm:px-6">
        {isLoading ? (
          <div className="grid gap-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className={cn("h-10 w-2/3 rounded-lg", i % 2 && "justify-self-end")} />)}</div>
        ) : error ? (
          <p role="alert" className="text-[13px] text-danger">{errorMessage(error)}</p>
        ) : !messages.length ? (
          <p className="pt-10 text-center text-[13px] text-muted">{t("No messages yet.")}</p>
        ) : (
          byDay(messages).map((g) => (
            <div key={g.day} className="grid gap-1.5">
              <p className="sticky top-0 z-10 my-2 justify-self-center rounded-full bg-surface px-3 py-0.5 text-[11.5px] text-muted shadow-sm">
                {new Date(g.items[0]!.at).toLocaleDateString(locale(), { weekday: "short", day: "numeric", month: "short" })}
              </p>
              {g.items.map((m) => <Bubble key={m.id} m={m} group={chat.group} onReply={() => { setReplyTo(m); box.current?.focus(); }} />)}
            </div>
          ))
        )}
      </div>

      <form className="grid shrink-0 gap-2 border-t border-border bg-surface px-3 py-2.5" onSubmit={(e) => { e.preventDefault(); if (text.trim()) send.mutate(); }}>
        {replyTo ? (
          <div className="flex min-w-0 items-start gap-2 rounded-sm border-l-2 border-accent bg-surface-2 px-2.5 py-1.5 text-[12.5px]">
            <span className="min-w-0 flex-1">
              <span className="block font-medium text-accent">{replyTo.from_me ? t("You") : replyTo.sender_name || numberOf(replyTo.sender)}</span>
              <span className="line-clamp-2 text-muted">{replyTo.text || t("Media")}</span>
            </span>
            <button type="button" onClick={() => setReplyTo(null)} aria-label={t("Cancel reply")} className="grid size-6 place-items-center rounded-sm text-muted hover:bg-surface"><XIcon size={13} /></button>
          </div>
        ) : null}
        <div className="flex min-w-0 items-end gap-2">
          <textarea ref={box} value={text} onChange={(e) => setText(e.target.value)} rows={1}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                if (text.trim() && !send.isPending) send.mutate();
              }
            }}
            placeholder={t("Type a message")} aria-label={t("Message")}
            className="max-h-40 min-h-10 min-w-0 flex-1 resize-none rounded-[var(--radius-md)] border border-border bg-bg px-3 py-2 text-[14px] [field-sizing:content] focus-visible:border-accent focus-visible:outline-none" />
          <Button type="button" variant="ghost" size="icon" title={t("Draft reply with AI")} aria-label={t("Draft reply with AI")} loading={ai.isPending && ai.variables === "draft"} onClick={() => ai.mutate("draft")}>
            <SparkleIcon size={18} />
          </Button>
          <Button type="submit" size="icon" className="rounded-full" aria-label={t("Send")} loading={send.isPending} disabled={!text.trim()}>
            <PaperPlaneRightIcon size={18} weight="fill" />
          </Button>
        </div>
        <p className="text-[11px] text-muted">{t("Enter sends, Shift+Enter starts a new line. The AI button drafts a reply (type what you want to say first, if you like).")}</p>
      </form>

      <ResponsiveDialog open={summary !== null} onOpenChange={(o) => !o && setSummary(null)} title={t("Chat summary")}>
        <div className="text-[13.5px]"><Markdown>{summary ?? ""}</Markdown></div>
      </ResponsiveDialog>
      {ruleOpen ? <RuleDialog chat={chat} onClose={() => setRuleOpen(false)} /> : null}
    </div>
  );
}

function Bubble({ m, group, onReply }: { m: WaMessage; group: boolean; onReply: () => void }) {
  const t = useT();
  const mine = m.from_me;
  return (
    <div className={cn("group flex min-w-0", mine ? "justify-end" : "justify-start")}>
      <div className={cn("relative max-w-[min(85%,36rem)] min-w-0 rounded-lg px-2.5 py-1.5 text-[13.5px] shadow-[0_1px_1px_hsl(var(--shadow)/0.08)]",
        mine ? "rounded-tr-sm bg-[#d9fdd3] text-[#111b21] dark:bg-[#005c4b] dark:text-[#e9edef]" : "rounded-tl-sm bg-surface")}>
        {group && !mine ? <p className="mb-0.5 truncate text-[12px] font-semibold text-accent">{m.sender_name || prettyNumber(numberOf(m.sender))}</p> : null}
        {m.reply_to ? (
          <p className="mb-1 line-clamp-2 rounded-sm border-l-2 border-accent bg-black/5 px-2 py-1 text-[12px] opacity-80">{m.reply_to.text || t("Media")}</p>
        ) : null}
        {m.media ? (
          <p className="mb-1 flex items-center gap-1.5 text-[12.5px]">
            <FileIcon size={14} className="shrink-0" />
            {m.media.url ? <a href={m.media.url} target="_blank" rel="noreferrer" className="truncate underline">{m.media.filename || m.media.mimetype}</a> : <span className="truncate">{m.media.filename || m.media.mimetype}</span>}
          </p>
        ) : null}
        {m.text ? <p className="break-words whitespace-pre-wrap">{m.text}</p> : null}
        <p className="mt-0.5 flex items-center justify-end gap-1 text-[10.5px] opacity-60">
          {m.ai ? <span className="rounded-full bg-accent/15 px-1.5 font-semibold text-accent opacity-100">AI</span> : null}
          {time(m.at)}
          {mine ? (m.ack !== null && m.ack >= 3 ? <ChecksIcon size={13} className="text-[#53bdeb]" /> : m.ack !== null && m.ack >= 2 ? <ChecksIcon size={13} /> : <CheckIcon size={12} />) : null}
        </p>
        <button type="button" onClick={onReply} aria-label={t("Reply to this message")} title={t("Reply")}
          className={cn("absolute top-1 grid size-6 place-items-center rounded-full bg-surface text-muted opacity-0 shadow-sm transition-opacity group-hover:opacity-100 focus-visible:opacity-100 pointer-coarse:opacity-70",
            mine ? "-left-8" : "-right-8")}>
          <ArrowBendUpLeftIcon size={13} />
        </button>
      </div>
    </div>
  );
}

const NO_AGENT = "default";

function RuleDialog({ chat, onClose }: { chat: WaChat; onClose: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const { data: rule, isLoading } = useQuery(ruleQuery(chat.id));
  const { data: agents = [] } = useQuery(agentsQuery);
  const [mode, setMode] = useState<AiMode | null>(null);
  const [agent, setAgent] = useState<string | null>(null);
  const [instructions, setInstructions] = useState<string | null>(null);
  const cur = { mode: mode ?? rule?.mode ?? "me", agent: agent ?? rule?.agent_id ?? NO_AGENT, instructions: instructions ?? rule?.instructions ?? "" };
  const active = agents.filter((a) => a.status === "active" && !a.clone_of);
  const save = useMutation({
    mutationFn: () => saveRule(chat.id, { mode: cur.mode, agent_id: cur.agent === NO_AGENT ? null : cur.agent, instructions: cur.instructions, name: chat.name }),
    onSuccess: (r) => {
      qc.setQueryData(waKeys.rule(chat.id), r);
      void qc.invalidateQueries({ queryKey: waKeys.chats });
      toast.success(t("Saved."));
      onClose();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <ResponsiveDialog open onOpenChange={(o) => !o && onClose()} title={t("AI in this chat")}
      description={chat.group ? t("In groups the AI only answers when your number is @mentioned or someone replies to it.") : t("Choose whether your AI answers in this chat, and for whom.")}
      footer={<><Button variant="ghost" onClick={onClose}>{t("Cancel")}</Button><Button loading={save.isPending} disabled={isLoading} onClick={() => save.mutate()}>{t("Save")}</Button></>}>
      {isLoading ? <Skeleton className="h-32" /> : (
        <div className="grid gap-4">
          <Segmented label={t("Who the AI answers")} value={cur.mode} onChange={setMode} className="w-full [&>button]:flex-1 [&>button]:justify-center"
            options={[{ value: "off", label: t("Off") }, { value: "me", label: t("Only me") }, { value: "everyone", label: t("Everyone") }]} />
          <p className="text-[12.5px] text-muted">
            {cur.mode === "off" ? t("The AI stays quiet here.")
              : cur.mode === "me" ? t("The AI answers only you (from your linked number), with everything it may use for you.")
              : t("The AI also answers other people here.")}
          </p>
          {cur.mode === "everyone" ? (
            <p className="flex items-start gap-2 rounded-sm border border-warn/30 bg-warn/8 px-3 py-2 text-[12.5px] text-warn">
              <WarningIcon size={15} className="mt-px shrink-0" />
              {t("Other people get a limited answer: the AI has no access to your private data, files or tools when it answers them.")}
            </p>
          ) : null}
          {cur.mode !== "off" ? (
            <>
              <Select label={t("Which AI answers")} value={cur.agent} onValueChange={setAgent}
                options={[{ value: NO_AGENT, label: t("My default AI") }, ...active.map((a) => ({ value: a.id, label: a.name }))]} />
              <label className="grid gap-1.5">
                <span className="text-[13px] font-medium">{t("Instructions for this chat (optional)")}</span>
                <textarea value={cur.instructions} onChange={(e) => setInstructions(e.target.value)} rows={3} maxLength={2000}
                  placeholder={t("e.g. Answer in Malay, keep it short, never promise prices.")}
                  className="w-full rounded-sm border border-border bg-surface px-3 py-2 text-[13.5px] focus-visible:border-accent focus-visible:outline-none" />
              </label>
            </>
          ) : null}
        </div>
      )}
    </ResponsiveDialog>
  );
}
