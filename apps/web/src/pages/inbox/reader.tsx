/** One email: who and when, the body in a sandboxed frame (no scripts), its attachments, the
 * actions (reply, reply all, forward, mark unread, delete) and an "Ask AI" bar. */
import {
  ArrowBendDoubleUpLeftIcon,
  ArrowBendUpLeftIcon,
  ArrowBendUpRightIcon,
  ArrowLeftIcon,
  ArrowSquareOutIcon,
  EnvelopeSimpleIcon,
  PaperclipIcon,
  SparkleIcon,
  TrashIcon,
  XIcon,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Markdown } from "@/components/markdown";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/field";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { locale, useT } from "@/i18n";
import { errorMessage } from "@/lib/api";
import {
  askAi,
  attachmentUrl,
  fileSizeShort,
  frameDoc,
  inboxKeys,
  markRead,
  messageQuery,
  prefixed,
  showAddr,
  trashMessage,
  type InboxMessage,
  type Tone,
} from "@/lib/inbox";

import { TONES, type ComposeInit } from "./composer";

const list = (xs: { name: string; address: string }[]) => xs.map((a) => a.address).join(", ");

/** The quoted original under a reply or forward. */
function quoted(m: InboxMessage, t: (s: string, v?: Record<string, string>) => string): string {
  const when = new Date(m.received_at).toLocaleString(locale());
  const text = (m.body_text || m.preview || "").trim().split("\n").map((l) => `> ${l}`).join("\n");
  return `\n\n${t("On {when}, {who} wrote:", { when, who: showAddr(m.from) })}\n${text}`;
}

export function Reader({ account, id, myEmail, onBack, onCompose }: {
  account: string;
  id: string;
  /** This account's own address: left out of Reply all. */
  myEmail?: string;
  onBack: () => void;
  onCompose: (c: ComposeInit) => void;
}) {
  const t = useT();
  const qc = useQueryClient();
  const { data: m, isLoading, error } = useQuery(messageQuery(account, id));
  const [answer, setAnswer] = useState<{ title: string; text: string } | null>(null);
  const [question, setQuestion] = useState("");
  const [tone, setTone] = useState<Tone>("");
  const marked = useRef<string | null>(null);

  // Opening an unread email marks it read (once per email).
  useEffect(() => {
    if (!m || m.is_read || marked.current === m.id) return;
    marked.current = m.id;
    markRead(account, m.id, true)
      .then(() => qc.invalidateQueries({ queryKey: ["inbox", "list"] }))
      .catch(() => {});
  }, [m, account, qc]);

  const unread = useMutation({
    mutationFn: () => markRead(account, id, false),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["inbox", "list"] });
      toast.success(t("Marked as unread."));
      onBack();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const trash = useMutation({
    mutationFn: () => trashMessage(account, id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: inboxKeys.all });
      toast.success(t("Moved to Deleted items."));
      onBack();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const ai = useMutation({
    mutationFn: (v: { action: "summarize" | "reply" | "ask"; instructions?: string }) =>
      askAi({ account, message_id: id, action: v.action, instructions: v.instructions ?? "", tone }),
    onSuccess: (r, v) => {
      if (v.action === "reply" && m) {
        onCompose({ account, to: list(m.reply_to.length ? m.reply_to : [m.from]), cc: "", subject: prefixed("Re", m.subject), body: r.text + quoted(m, t), replyToId: m.id, aboutId: m.id });
        return;
      }
      setAnswer({ title: v.action === "summarize" ? t("Summary") : t("Answer"), text: r.text });
      if (v.action === "ask") setQuestion("");
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  if (isLoading) {
    return (
      <div className="grid content-start gap-3 p-4">
        <Skeleton className="h-7 w-2/3" />
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="h-64" />
      </div>
    );
  }
  if (error || !m) {
    return (
      <div className="grid content-start gap-3 p-4">
        <Button variant="ghost" size="sm" className="justify-self-start md:hidden" onClick={onBack}><ArrowLeftIcon size={15} /> {t("Back")}</Button>
        <p role="alert" className="text-danger">{errorMessage(error)}</p>
      </div>
    );
  }

  const reply = (all: boolean) => {
    const me = (myEmail ?? "").toLowerCase();
    const to = list(m.reply_to.length ? m.reply_to : [m.from]);
    const cc = all ? [...m.to, ...m.cc].map((a) => a.address).filter((a) => a && !to.includes(a) && a.toLowerCase() !== me).join(", ") : "";
    onCompose({ account, to, cc, subject: prefixed("Re", m.subject), body: quoted(m, t), replyToId: m.id, replyAll: all, aboutId: m.id });
  };
  const forward = () => onCompose({ account, to: "", cc: "", subject: prefixed("Fwd", m.subject), body: quoted(m, t), forwardId: m.id, aboutId: m.id });
  const files = m.attachments.filter((a) => !a.inline);

  return (
    <article className="flex h-full min-h-0 min-w-0 flex-col">
      <header className="grid shrink-0 gap-2 border-b border-border px-4 py-3">
        <div className="flex min-w-0 items-start gap-2">
          <Button variant="ghost" size="icon-sm" className="-ml-1 shrink-0 md:hidden" aria-label={t("Back")} onClick={onBack}><ArrowLeftIcon size={17} /></Button>
          <h2 className="min-w-0 flex-1 text-[17px] leading-snug font-semibold break-words">{m.subject || t("(no subject)")}</h2>
          {m.web_link ? (
            <Button variant="ghost" size="icon-sm" asChild><a href={m.web_link} target="_blank" rel="noreferrer" aria-label={t("Open in the mail app")} title={t("Open in the mail app")}><ArrowSquareOutIcon size={16} /></a></Button>
          ) : null}
        </div>
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 text-[13px]">
          <span className="font-medium">{showAddr(m.from)}</span>
          {m.from.name ? <span className="truncate text-muted">&lt;{m.from.address}&gt;</span> : null}
          <time className="ml-auto shrink-0 text-[12px] text-muted" dateTime={m.received_at}>{new Date(m.received_at).toLocaleString(locale())}</time>
        </div>
        {m.to.length || m.cc.length ? (
          <p className="truncate text-[12px] text-muted">
            {t("To {list}", { list: m.to.map(showAddr).join(", ") })}{m.cc.length ? ` · ${t("Cc {list}", { list: m.cc.map(showAddr).join(", ") })}` : ""}
          </p>
        ) : null}
        <div className="flex flex-wrap gap-1.5">
          <Button size="sm" variant="outline" onClick={() => reply(false)}><ArrowBendUpLeftIcon size={15} /> {t("Reply")}</Button>
          <Button size="sm" variant="outline" onClick={() => reply(true)}><ArrowBendDoubleUpLeftIcon size={15} /> {t("Reply all")}</Button>
          <Button size="sm" variant="outline" onClick={forward}><ArrowBendUpRightIcon size={15} /> {t("Forward")}</Button>
          <Button size="sm" variant="ghost" loading={unread.isPending} onClick={() => unread.mutate()}><EnvelopeSimpleIcon size={15} /> {t("Mark unread")}</Button>
          <Button size="sm" variant="ghost" className="hover:text-danger" loading={trash.isPending} onClick={() => trash.mutate()}><TrashIcon size={15} /> {t("Delete")}</Button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {/* Ask AI about this email */}
        <section aria-label={t("Ask AI")} className="grid gap-2 border-b border-border bg-accent-soft/20 px-4 py-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 inline-flex items-center gap-1 text-[12.5px] font-medium text-accent"><SparkleIcon size={14} weight="fill" /> {t("Ask AI")}</span>
            <Button size="sm" variant="secondary" loading={ai.isPending && ai.variables?.action === "summarize"} onClick={() => ai.mutate({ action: "summarize" })}>{t("Summarize")}</Button>
            <Button size="sm" variant="secondary" loading={ai.isPending && ai.variables?.action === "reply"} onClick={() => ai.mutate({ action: "reply" })}>{t("Draft reply")}</Button>
            <Select size="sm" label={t("Tone")} value={tone || "natural"} onValueChange={(v) => setTone(v === "natural" ? "" : (v as Tone))}
              options={TONES.map((o) => ({ value: o.value || "natural", label: t(o.label) }))} className="w-32" />
          </div>
          <form className="flex min-w-0 gap-2" onSubmit={(e) => { e.preventDefault(); if (question.trim()) ai.mutate({ action: "ask", instructions: question.trim() }); }}>
            <Input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder={t("Ask anything about this email…")} aria-label={t("Ask about this email")} className="min-w-0 flex-1" />
            <Button size="sm" type="submit" className="h-10" disabled={!question.trim()} loading={ai.isPending && ai.variables?.action === "ask"}>{t("Ask")}</Button>
          </form>
          {answer ? (
            <div className="relative rounded-[var(--radius-md)] border border-border bg-surface px-3.5 py-3 text-[13.5px]">
              <button type="button" onClick={() => setAnswer(null)} aria-label={t("Close")} className="absolute top-2 right-2 grid size-7 place-items-center rounded-sm text-muted hover:bg-surface-2"><XIcon size={14} /></button>
              <p className="mb-1 text-[12px] font-semibold text-muted uppercase">{answer.title}</p>
              <Markdown>{answer.text}</Markdown>
            </div>
          ) : null}
        </section>

        {files.length ? (
          <ul className="flex flex-wrap gap-2 border-b border-border px-4 py-3" aria-label={t("Attachments")}>
            {files.map((a) => (
              <li key={a.id}>
                <a href={attachmentUrl(account, m.id, a.id)} download={a.name}
                  className="inline-flex max-w-[16rem] items-center gap-1.5 rounded-full border border-border bg-surface px-3 py-1.5 text-[12.5px] hover:border-accent/40 hover:text-accent">
                  <PaperclipIcon size={13} className="shrink-0" />
                  <span className="truncate">{a.name}</span>
                  <span className="shrink-0 text-muted">{fileSizeShort(a.size)}</span>
                </a>
              </li>
            ))}
          </ul>
        ) : null}

        {/* No scripts can run in the frame (sandbox without allow-scripts); links open in a new tab. */}
        <iframe
          title={m.subject || t("Email")}
          sandbox="allow-popups allow-popups-to-escape-sandbox"
          srcDoc={frameDoc(m.body_html, m.body_text)}
          className="block h-[70dvh] w-full border-0 bg-white"
        />
      </div>
    </article>
  );
}
