/** Write, reply or forward: To, Cc, Subject and the text, with the AI to write or polish it. */
import { FloppyDiskIcon, MagicWandIcon, PaperPlaneTiltIcon, SparkleIcon } from "@phosphor-icons/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ResponsiveDialog } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/field";
import { Select } from "@/components/ui/select";
import { useT } from "@/i18n";
import { errorMessage } from "@/lib/api";
import { askAi, inboxKeys, sendMail, splitAddresses, type InboxAccount, type Tone } from "@/lib/inbox";

export interface ComposeInit {
  account: string;
  to: string;
  cc: string;
  subject: string;
  body: string;
  replyToId?: string | null;
  replyAll?: boolean;
  forwardId?: string | null;
  /** The message being answered, for the AI to read. */
  aboutId?: string | null;
}

export const TONES: { value: Tone; label: string }[] = [
  { value: "", label: "Natural" },
  { value: "friendly", label: "Friendly" },
  { value: "formal", label: "Formal" },
  { value: "short", label: "Short" },
  { value: "firm", label: "Firm" },
  { value: "apologetic", label: "Apologetic" },
];

export function Composer({ init, accounts, onClose }: { init: ComposeInit; accounts: InboxAccount[]; onClose: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const senders = accounts.filter((a) => a.can_send);
  const [account, setAccount] = useState(init.account);
  const [to, setTo] = useState(init.to);
  const [cc, setCc] = useState(init.cc);
  const [showCc, setShowCc] = useState(!!init.cc);
  const [subject, setSubject] = useState(init.subject);
  const [body, setBody] = useState(init.body);
  const [ask, setAsk] = useState("");
  const [tone, setTone] = useState<Tone>("");
  const kind = init.forwardId ? "forward" : init.replyToId ? "reply" : "new";

  const send = useMutation({
    mutationFn: (draft: boolean) =>
      sendMail({
        account,
        to: splitAddresses(to),
        cc: splitAddresses(cc),
        subject,
        body,
        reply_to_id: init.replyToId ?? null,
        reply_all: !!init.replyAll,
        forward_id: init.forwardId ?? null,
        draft,
      }),
    onSuccess: (r, draft) => {
      toast.success(draft || !r.sent ? t("Saved to Drafts.") : t("Sent."));
      void qc.invalidateQueries({ queryKey: inboxKeys.all });
      onClose();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const ai = useMutation({
    mutationFn: (action: "compose" | "improve" | "reply") =>
      askAi({ account, message_id: init.aboutId ?? undefined, action, instructions: ask.trim(), draft: body, tone }),
    onSuccess: (r) => {
      setBody(r.text);
      if (r.subject && !subject.trim()) setSubject(r.subject);
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const canSend = splitAddresses(to).length > 0 && (subject.trim() || body.trim()) && !!account;
  const title = kind === "forward" ? t("Forward") : kind === "reply" ? t("Reply") : t("New email");
  return (
    <ResponsiveDialog open onOpenChange={(o) => !o && onClose()} title={title} className="w-[min(94vw,44rem)]"
      footer={
        <>
          <Button variant="ghost" onClick={() => send.mutate(true)} loading={send.isPending && send.variables === true} disabled={!account}>
            <FloppyDiskIcon size={16} /> {t("Save draft")}
          </Button>
          <Button onClick={() => send.mutate(false)} loading={send.isPending && send.variables === false} disabled={!canSend}>
            <PaperPlaneTiltIcon size={16} weight="fill" /> {t("Send")}
          </Button>
        </>
      }>
      <div className="grid min-w-0 gap-3">
        {senders.length > 1 ? (
          <Select label={t("From")} value={account} onValueChange={setAccount}
            options={senders.map((a) => ({ value: a.key, label: a.label && a.label !== a.email ? `${a.label} (${a.email})` : a.email }))} />
        ) : null}
        <div className="grid gap-1">
          <Field label={t("To")} value={to} onChange={(e) => setTo(e.target.value)} placeholder={t("name@example.com, another@example.com")} autoComplete="off" inputMode="email" />
          {!showCc ? (
            <button type="button" onClick={() => setShowCc(true)} className="justify-self-start text-[12.5px] font-medium text-accent hover:underline">{t("Add Cc")}</button>
          ) : null}
        </div>
        {showCc ? <Field label={t("Cc")} value={cc} onChange={(e) => setCc(e.target.value)} autoComplete="off" inputMode="email" /> : null}
        <Field label={t("Subject")} value={subject} onChange={(e) => setSubject(e.target.value)} />
        <label className="grid gap-1.5">
          <span className="text-[13px] font-medium">{t("Message")}</span>
          <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={12}
            className="min-h-48 w-full rounded-sm border border-border bg-surface px-3 py-2 text-[14px] leading-relaxed focus-visible:border-accent focus-visible:outline-none" />
        </label>
        <div className="grid gap-2 rounded-[var(--radius-md)] border border-accent/25 bg-accent-soft/30 p-3">
          <p className="flex items-center gap-1.5 text-[13px] font-medium text-accent"><SparkleIcon size={15} weight="fill" /> {t("Write with AI")}</p>
          <div className="flex min-w-0 flex-wrap gap-2">
            <Input value={ask} onChange={(e) => setAsk(e.target.value)} className="min-w-0 flex-1 basis-56"
              placeholder={kind === "reply" ? t("What should the reply say? (optional)") : t("What should it say? e.g. ask for the March invoice")} aria-label={t("Instructions for the AI")} />
            <Select size="sm" label={t("Tone")} value={tone || "natural"} onValueChange={(v) => setTone(v === "natural" ? "" : (v as Tone))}
              options={TONES.map((o) => ({ value: o.value || "natural", label: t(o.label) }))} className="w-36" />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" loading={ai.isPending && ai.variables !== "improve"} disabled={!account || (kind === "new" && !ask.trim())}
              onClick={() => ai.mutate(kind === "reply" ? "reply" : "compose")}>
              <SparkleIcon size={14} /> {kind === "reply" ? t("Draft the reply") : t("Write it")}
            </Button>
            <Button size="sm" variant="outline" loading={ai.isPending && ai.variables === "improve"} disabled={!account || !body.trim()} onClick={() => ai.mutate("improve")}>
              <MagicWandIcon size={14} /> {t("Improve with AI")}
            </Button>
          </div>
          <p className="text-[11.5px] text-muted">{t("The AI only writes into this box. Nothing is sent until you press Send.")}</p>
        </div>
      </div>
    </ResponsiveDialog>
  );
}
