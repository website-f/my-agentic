/** People with access: other WhatsApp numbers the owner lets message or mention the connected
 * number and get the AI's help, each with a level, daily limits, chats and an end date. */
import {
  ArrowLeftIcon,
  CaretRightIcon,
  ChatCircleIcon,
  PencilSimpleIcon,
  PlusIcon,
  TrashIcon,
  UserIcon,
  UsersThreeIcon,
  WarningIcon,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Switch } from "radix-ui";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/page";
import { Button } from "@/components/ui/button";
import { ChoiceCard } from "@/components/ui/choice-card";
import { ConfirmDialog } from "@/components/ui/confirm";
import { Field, FormError, TextareaField } from "@/components/ui/field";
import { Pill } from "@/components/ui/pill";
import { SearchInput } from "@/components/ui/search-input";
import { SideSheet } from "@/components/ui/side-sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { locale, useT } from "@/i18n";
import { ApiError, errorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  addMember,
  answersFor,
  cleanNumber,
  dayOf,
  endOfDayIso,
  isExpired,
  membersQuery,
  numberOf,
  pickChatsQuery,
  prettyNumber,
  removeMember,
  shortCount,
  updateMember,
  usedPct,
  waKeys,
  type WaLevel,
  type WaMember,
  type WaMemberPatch,
} from "@/lib/wa";

const LEVELS: { value: WaLevel; label: string; hint: string }[] = [
  { value: "chat", label: "Chat only", hint: "Answers their questions, no tools and no access to your private information." },
  { value: "assistant", label: "Assistant", hint: "Uses the AI's tools for them (research, documents, files shared in the chat) but never your email, inbox, computer, calendar or saved logins." },
  { value: "full", label: "Full", hint: "Like you. Only for people you trust completely." },
];
const LEVEL_TONE: Record<WaLevel, "neutral" | "accent" | "warn"> = { chat: "neutral", assistant: "accent", full: "warn" };
const levelLabel = (l: WaLevel) => LEVELS.find((x) => x.value === l)?.label ?? l;

/** The button on the WhatsApp page that opens the panel. */
export function MembersButton({ className }: { className?: string }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button size="sm" variant="outline" className={className} onClick={() => setOpen(true)} title={t("People with access")}>
        <UsersThreeIcon size={15} /> {t("People with access")}
      </Button>
      {open ? <MembersSheet onClose={() => setOpen(false)} /> : null}
    </>
  );
}

function MembersSheet({ onClose }: { onClose: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery(membersQuery);
  const members = data?.members ?? [];
  /** null = the list; "new" = adding someone; a member = editing them. */
  const [editing, setEditing] = useState<WaMember | "new" | null>(null);
  const [removing, setRemoving] = useState<WaMember | null>(null);

  const toggle = useMutation({
    mutationFn: (m: WaMember) => updateMember(m.id, { enabled: !m.enabled }),
    onSuccess: (r) => {
      toast.success(r.enabled ? t("Access turned on.") : t("Access turned off."));
      void qc.invalidateQueries({ queryKey: waKeys.members });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const title = editing === "new" ? t("Add person") : editing ? t("Edit {name}", { name: editing.name || prettyNumber(editing.number) }) : t("People with access");
  return (
    <SideSheet open onOpenChange={(o) => !o && onClose()} title={title}
      description={editing ? undefined : t("Other WhatsApp numbers that may use your AI.")}
      actions={editing ? undefined : <Button size="sm" onClick={() => setEditing("new")}><PlusIcon size={15} /> {t("Add person")}</Button>}>
      {editing ? (
        <MemberForm key={editing === "new" ? "new" : editing.id} member={editing === "new" ? null : editing} onDone={() => setEditing(null)} />
      ) : (
        <div className="grid gap-4">
          <div className="grid gap-1.5 rounded-[var(--radius-md)] border border-border bg-surface-2/50 px-3.5 py-3 text-[12.5px] text-muted">
            <p>{t("People here can message the connected number, or mention it in a group, and get your AI's help within their level and limits. Their conversations are kept separate from yours and do not teach your AI.")}</p>
            <p>{t("In groups, the AI answers only when the number is mentioned or replied to.")}</p>
          </div>
          {isLoading ? (
            <div className="grid gap-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-28 rounded-[var(--radius-md)]" />)}</div>
          ) : error ? (
            <p role="alert" className="text-[13px] text-danger">{errorMessage(error)}</p>
          ) : !members.length ? (
            <EmptyState icon={UsersThreeIcon} title={t("Nobody else has access yet")}
              body={t("Only you (from your linked number) can instruct the AI. Add a person to let them use it too.")}
              action={<Button onClick={() => setEditing("new")}><PlusIcon size={15} /> {t("Add person")}</Button>} />
          ) : (
            <ul className="grid gap-2.5">
              {members.map((m) => (
                <li key={m.id}>
                  <MemberRow m={m} busy={toggle.isPending && toggle.variables?.id === m.id}
                    onEdit={() => setEditing(m)} onToggle={() => toggle.mutate(m)} onRemove={() => setRemoving(m)} />
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} danger
        title={t("Remove access?")}
        body={t("{name} can no longer use your AI on WhatsApp. You can add them again later.", { name: removing ? removing.name || prettyNumber(removing.number) : "" })}
        confirmLabel={t("Remove")}
        onConfirm={async () => {
          if (!removing) return;
          await removeMember(removing.id);
          toast.success(t("Access removed."));
          await qc.invalidateQueries({ queryKey: waKeys.members });
        }} />
    </SideSheet>
  );
}

function Usage({ used, limit, label, noLimit }: { used: number; limit: number; label: string; noLimit: string }) {
  const pct = usedPct(used, limit);
  return (
    <div className="grid min-w-0 gap-1">
      <p className="truncate text-[12px] text-muted tabular">{limit > 0 ? label : noLimit}</p>
      {limit > 0 ? (
        <div className="h-1.5 overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={label}>
          <div className={cn("h-full rounded-full", pct >= 100 ? "bg-danger" : pct >= 80 ? "bg-warn" : "bg-accent")} style={{ width: `${pct}%` }} />
        </div>
      ) : null}
    </div>
  );
}

function MemberRow({ m, busy, onEdit, onToggle, onRemove }: { m: WaMember; busy: boolean; onEdit: () => void; onToggle: () => void; onRemove: () => void }) {
  const t = useT();
  const expired = isExpired(m);
  const { messages, tokens } = m.used_today;
  return (
    <div className={cn("grid gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-3.5", (!m.enabled || expired) && "bg-surface-2/40")}>
      <div className="flex min-w-0 items-start gap-3">
        <span aria-hidden className="grid size-9 shrink-0 place-items-center rounded-full bg-[#25d366]/15 text-[13px] font-semibold text-[#128c4a]">
          {(m.name.trim()[0] ?? "+").toUpperCase()}
        </span>
        <div className="grid min-w-0 flex-1 gap-1">
          <p className="truncate text-[14px] font-semibold">{m.name || prettyNumber(m.number)}</p>
          {m.name ? <p className="truncate text-[12px] text-muted tabular">{prettyNumber(m.number)}</p> : null}
          <div className="flex flex-wrap items-center gap-1.5">
            <Pill tone={LEVEL_TONE[m.level]}>{t(levelLabel(m.level))}</Pill>
            {!m.enabled ? <Pill>{t("Off")}</Pill> : expired ? <Pill tone="danger">{t("Expired")}</Pill> : null}
            <Pill>{m.chats.length ? t("{n} chats", { n: m.chats.length }) : t("All chats")}</Pill>
            {m.expires_at && !expired ? (
              <span className="text-[11.5px] text-muted">{t("Until {date}", { date: new Date(m.expires_at).toLocaleDateString(locale(), { day: "numeric", month: "short", year: "numeric" }) })}</span>
            ) : null}
            {!m.seen_lid ? <span className="text-[11.5px] text-muted" title={t("They have not messaged the number yet.")}>{t("Not heard from yet")}</span> : null}
          </div>
        </div>
        <Switch.Root checked={m.enabled} onCheckedChange={onToggle} disabled={busy}
          aria-label={t("Access on for {name}", { name: m.name || prettyNumber(m.number) })}
          className="relative mt-0.5 h-6 w-10 shrink-0 rounded-full bg-border transition-colors data-[state=checked]:bg-accent disabled:opacity-50">
          <Switch.Thumb className="block size-5 translate-x-0.5 rounded-full bg-white shadow-sm transition-transform duration-200 data-[state=checked]:translate-x-[18px]" />
        </Switch.Root>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Usage used={messages} limit={m.daily_messages}
          label={t("{used} / {limit} messages", { used: messages, limit: m.daily_messages })}
          noLimit={t("{used} messages today, no limit", { used: messages })} />
        <Usage used={tokens} limit={m.daily_tokens}
          label={t("{used} / {limit} AI tokens", { used: shortCount(tokens), limit: shortCount(m.daily_tokens) })}
          noLimit={t("{used} AI tokens today, no limit", { used: shortCount(tokens) })} />
      </div>
      {m.notes ? <p className="line-clamp-2 text-[12px] text-muted">{m.notes}</p> : null}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={onEdit}><PencilSimpleIcon size={14} /> {t("Edit")}</Button>
        <Button size="sm" variant="ghost" className="text-danger hover:text-danger" onClick={onRemove}><TrashIcon size={14} /> {t("Remove")}</Button>
      </div>
    </div>
  );
}

function MemberForm({ member, onDone }: { member: WaMember | null; onDone: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const [number, setNumber] = useState(member?.number ?? "");
  const [name, setName] = useState(member?.name ?? "");
  const [level, setLevel] = useState<WaLevel>(member?.level ?? "assistant");
  const [messages, setMessages] = useState(String(member?.daily_messages ?? 30));
  const [tokens, setTokens] = useState(String(member?.daily_tokens ?? 200_000));
  const [chats, setChats] = useState<string[]>(member?.chats ?? []);
  const [ends, setEnds] = useState(dayOf(member?.expires_at ?? null));
  const [notes, setNotes] = useState(member?.notes ?? "");
  const [numberError, setNumberError] = useState<string | undefined>();
  const [formError, setFormError] = useState<string | null>(null);
  // Editing someone whose advanced settings are in use opens them; after that the person decides.
  const [advancedOpen] = useState(!!member && (member.chats.length > 0 || !!member.expires_at || !!member.notes));

  const cleaned = cleanNumber(number);
  const count = (v: string) => Math.max(0, Math.floor(Number(v) || 0));

  const save = useMutation({
    mutationFn: async () => {
      const common = {
        name: name.trim(),
        level,
        daily_messages: count(messages),
        daily_tokens: count(tokens),
        chats,
        notes: notes.trim(),
      };
      if (!member) {
        return addMember({ ...common, number: number.trim(), enabled: true, expires_at: ends ? endOfDayIso(ends) : null });
      }
      const patch: WaMemberPatch = { ...common };
      if (ends) patch.expires_at = endOfDayIso(ends);
      else if (member.expires_at) patch.clear_expiry = true;
      return updateMember(member.id, patch);
    },
    onSuccess: () => {
      toast.success(member ? t("Saved.") : t("Access given."));
      void qc.invalidateQueries({ queryKey: waKeys.members });
      onDone();
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code === "bad_number") setNumberError(t("Type the number with its country code."));
      else if (e instanceof ApiError && e.code === "exists") setNumberError(t("That number has access already."));
      else setFormError(errorMessage(e));
    },
  });

  const submit = () => {
    setNumberError(undefined);
    setFormError(null);
    if (!member && (cleaned.length < 8 || cleaned.length > 15)) {
      setNumberError(t("Type the number with its country code."));
      return;
    }
    save.mutate();
  };

  return (
    <form className="grid gap-5" onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <button type="button" onClick={onDone} className="-mt-1 flex min-h-9 items-center gap-1.5 justify-self-start rounded-sm text-[13px] text-muted hover:text-fg">
        <ArrowLeftIcon size={14} /> {t("Back to the list")}
      </button>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("Phone number")} value={number} onChange={(e) => setNumber(e.target.value)} disabled={!!member}
          inputMode="tel" autoComplete="off" placeholder="60123456789" required error={numberError}
          hint={member ? t("To change the number, remove this person and add the new number.")
            : cleaned.length >= 8 ? t("Saved as {number}", { number: prettyNumber(cleaned) })
            : t("With country code, e.g. 60123456789; a number starting with 0 is read as Malaysian.")} />
        <Field label={t("Name")} value={name} onChange={(e) => setName(e.target.value)} maxLength={120} placeholder={t("e.g. Aina (sales)")} />
      </div>

      <div role="radiogroup" aria-label={t("Access level")} className="grid gap-2">
        <p className="text-[13px] font-medium">{t("Access level")}</p>
        {LEVELS.map((l) => (
          <ChoiceCard key={l.value} on={level === l.value} onToggle={() => setLevel(l.value)}
            title={<span className={cn(l.value === "full" && "text-warn")}>{t(l.label)}{l.value === "assistant" ? <span className="ml-1.5 text-[12px] font-normal text-muted">{t("(recommended)")}</span> : null}</span>}
            hint={t(l.hint)}
            leading={l.value === "full" ? <WarningIcon size={18} className="shrink-0 text-warn" /> : null} />
        ))}
      </div>

      <details className="group rounded-[var(--radius-md)] border border-border" open={advancedOpen}>
        <summary className="flex min-h-10 cursor-pointer list-none items-center gap-1.5 px-3 text-[13px] font-medium select-none pointer-coarse:min-h-11 [&::-webkit-details-marker]:hidden">
          <CaretRightIcon size={12} weight="bold" className="transition-transform group-open:rotate-90" /> {t("Advanced settings")}
        </summary>
        <div className="grid gap-4 border-t border-border px-3 py-3.5">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("Messages per day")} type="number" min={0} max={10000} inputMode="numeric" value={messages}
              onChange={(e) => setMessages(e.target.value)} hint={t("0 = no limit.")} />
            <Field label={t("AI tokens per day")} type="number" min={0} max={50000000} step={1000} inputMode="numeric" value={tokens}
              onChange={(e) => setTokens(e.target.value)}
              hint={count(tokens) ? t("About {n} normal answers. 0 = no limit.", { n: answersFor(count(tokens)) }) : t("0 = no limit.")} />
          </div>
          <ChatPicker value={chats} onChange={setChats} />
          <div className="grid gap-1.5">
            <div className="flex items-end gap-2">
              <Field className="min-w-0 flex-1" label={t("Access ends on")} type="date" value={ends} min={dayOf(new Date().toISOString())}
                onChange={(e) => setEnds(e.target.value)} hint={ends ? undefined : t("Empty = never.")} />
              {ends ? <Button type="button" variant="ghost" onClick={() => setEnds("")}>{t("Clear")}</Button> : null}
            </div>
          </div>
          <TextareaField label={t("Notes")} value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={500} rows={3}
            placeholder={t("e.g. Contractor for the March project")} hint={t("Only for you; the AI does not see these.")} />
        </div>
      </details>

      <FormError message={formError} />
      <div className="flex flex-wrap justify-end gap-2 max-sm:flex-col-reverse">
        <Button type="button" variant="ghost" onClick={onDone}>{t("Cancel")}</Button>
        <Button type="submit" loading={save.isPending}>{member ? t("Save") : t("Give access")}</Button>
      </div>
    </form>
  );
}

/** Tick the chats where the person may use the AI; none ticked = every chat. */
function ChatPicker({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const t = useT();
  const { data, isLoading, error } = useQuery(pickChatsQuery);
  const [q, setQ] = useState("");
  const rows = useMemo(() => {
    const all = data?.chats ?? [];
    const known = new Set(all.map((c) => c.id));
    // Chats picked earlier that are not in the recent list still show (and can be unticked).
    const extra = value.filter((id) => !known.has(id)).map((id) => ({ id, name: numberOf(id), group: id.endsWith("@g.us") }));
    const list = [...all.map((c) => ({ id: c.id, name: c.name || numberOf(c.id), group: c.group })), ...extra];
    const needle = q.trim().toLowerCase();
    const shown = needle ? list.filter((c) => `${c.name} ${numberOf(c.id)}`.toLowerCase().includes(needle)) : list;
    return [...shown.filter((c) => c.group), ...shown.filter((c) => !c.group)];
  }, [data, value, q]);
  const on = new Set(value);
  const flip = (id: string) => onChange(on.has(id) ? value.filter((x) => x !== id) : [...value, id]);
  return (
    <div className="grid gap-2">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-[13px] font-medium">{t("Allowed chats")}</p>
        <span className="text-[12px] text-muted">{value.length ? t("{n} chats", { n: value.length }) : t("All chats")}</span>
      </div>
      <p className="text-[12.5px] text-muted">{t("Tick the chats where they may use the AI. None ticked = all chats.")}</p>
      <SearchInput value={q} onChange={setQ} placeholder={t("Search chats")} className="basis-0" />
      <div className="max-h-64 overflow-y-auto rounded-sm border border-border">
        {isLoading ? (
          <div className="grid gap-1 p-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-8" />)}</div>
        ) : error ? (
          <p role="alert" className="p-3 text-[12.5px] text-danger">{errorMessage(error)}</p>
        ) : !rows.length ? (
          <p className="p-3 text-center text-[12.5px] text-muted">{q ? t("No chat matches.") : t("No chats yet.")}</p>
        ) : (
          <ul>
            {rows.map((c) => (
              <li key={c.id}>
                <label className="flex min-h-10 cursor-pointer items-center gap-2.5 px-3 py-1.5 text-[13px] hover:bg-surface-2/60 pointer-coarse:min-h-11">
                  <input type="checkbox" checked={on.has(c.id)} onChange={() => flip(c.id)} className="size-4 shrink-0 accent-[var(--accent)]" />
                  {c.group ? <UsersThreeIcon size={15} className="shrink-0 text-muted" aria-label={t("Group")} /> : c.id.endsWith("@c.us") ? <UserIcon size={15} className="shrink-0 text-muted" /> : <ChatCircleIcon size={15} className="shrink-0 text-muted" />}
                  <span className="min-w-0 flex-1 truncate">{c.name}</span>
                  {!c.group ? <span className="shrink-0 text-[11.5px] text-muted tabular">{prettyNumber(numberOf(c.id))}</span> : null}
                </label>
              </li>
            ))}
          </ul>
        )}
      </div>
      {value.length ? (
        <button type="button" onClick={() => onChange([])} className="min-h-9 justify-self-start rounded-sm text-[12.5px] text-muted underline-offset-2 hover:text-fg hover:underline">
          {t("Untick all (all chats)")}
        </button>
      ) : null}
    </div>
  );
}
