/** Every email account in one place, Gmail/Outlook-like: accounts and folders on the left, the
 * messages in the middle, the open email on the right (on a phone: one at a time). */
import {
  ArchiveIcon,
  CaretDownIcon,
  EnvelopeSimpleIcon,
  FileDashedIcon,
  FlagIcon,
  PaperclipIcon,
  PaperPlaneTiltIcon,
  PencilSimpleIcon,
  PlusIcon,
  ProhibitIcon,
  TrashIcon,
  TrayIcon,
  WarningCircleIcon,
  type Icon,
} from "@phosphor-icons/react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/page";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm";
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from "@/components/ui/menu";
import { SearchInput } from "@/components/ui/search-input";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { locale, useT } from "@/i18n";
import { api, errorMessage } from "@/lib/api";
import {
  accountsQuery,
  ALL,
  inboxKeys,
  listPath,
  removeAccount,
  shortWhen,
  showAddr,
  type InboxAccount,
  type InboxPage,
  type InboxRow,
  type ListArgs,
} from "@/lib/inbox";
import { useDebounced } from "@/lib/paged";
import { cn } from "@/lib/utils";

import { AddAccountDialog } from "./add-account";
import { Composer, type ComposeInit } from "./composer";
import { Reader } from "./reader";

interface InboxSearch {
  account?: string;
  folder?: string;
  msg?: string;
  ms?: string;
  google?: string;
}

const FOLDER_ICON: Record<string, Icon> = {
  inbox: TrayIcon,
  sentitems: PaperPlaneTiltIcon,
  drafts: FileDashedIcon,
  archive: ArchiveIcon,
  deleteditems: TrashIcon,
  junkemail: ProhibitIcon,
};

const PROVIDER_LABEL: Record<InboxAccount["provider"], string> = { microsoft: "Microsoft", google: "Gmail", imap: "IMAP" };

const accountName = (a: InboxAccount) => (a.label && a.label !== a.email ? a.label : a.email);

export function InboxPage() {
  const t = useT();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const search = useSearch({ strict: false }) as InboxSearch;
  const { data: home, isLoading, error } = useQuery(accountsQuery);
  const [adding, setAdding] = useState(false);
  const [compose, setCompose] = useState<ComposeInit | null>(null);
  const [removing, setRemoving] = useState<InboxAccount | null>(null);
  const [q, setQ] = useState("");
  const [unread, setUnread] = useState(false);
  const needle = useDebounced(q.trim());

  const accounts = useMemo(() => home?.accounts ?? [], [home]);
  const folders = home?.folders ?? [];
  const account = search.account && (search.account === ALL || accounts.some((a) => a.key === search.account)) ? search.account : ALL;
  // "All inboxes" is the inbox of every account; folders are per account.
  const folder = account === ALL ? "inbox" : (search.folder ?? "inbox");
  const go = (next: Partial<InboxSearch>, replace = false) =>
    void navigate({ to: "/inbox", search: { account: next.account ?? (account === ALL ? undefined : account), folder: next.folder, msg: next.msg }, replace });

  // Back from Microsoft or Google sign-in (?ms= / ?google= with msg as the detail).
  useEffect(() => {
    const result = search.ms ?? search.google;
    if (!result) return;
    const who = search.ms ? "Microsoft" : "Google";
    if (result === "connected") toast.success(t("{who} account connected.", { who }));
    else toast.error(search.msg || t("{who} sign-in did not finish.", { who }));
    void qc.invalidateQueries({ queryKey: inboxKeys.all });
    void navigate({ to: "/inbox", search: {}, replace: true });
  }, [search.ms, search.google, search.msg, navigate, qc, t]);

  const args: ListArgs = { account, folder, q: needle, unread };
  const list = useInfiniteQuery({
    queryKey: inboxKeys.list(args),
    queryFn: ({ pageParam }) => api<InboxPage>(listPath(args, pageParam)),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next,
    enabled: accounts.length > 0 && !search.ms && !search.google,
    refetchInterval: 60_000,
  });
  const rows = useMemo(() => list.data?.pages.flatMap((p) => p.items) ?? [], [list.data]);
  const problems = list.data?.pages[0]?.problems ?? [];

  // The open email: its account from its row (under "All inboxes"), else the chosen account.
  const openId = search.ms || search.google ? undefined : search.msg;
  const openRow = openId ? rows.find((r) => r.id === openId) : undefined;
  const openAccount = openRow?.account ?? (account === ALL ? accounts.find((a) => a.primary)?.key ?? accounts[0]?.key : account);
  const sendFrom = (account !== ALL ? accounts.find((a) => a.key === account && a.can_send) : undefined) ?? accounts.find((a) => a.primary && a.can_send) ?? accounts.find((a) => a.can_send);

  const remove = useMutation({
    mutationFn: (a: InboxAccount) => removeAccount(a.key),
    onSuccess: () => {
      toast.success(t("Account removed from the inbox."));
      void qc.invalidateQueries({ queryKey: inboxKeys.all });
      go({ account: ALL }, true);
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const newMail = () => {
    if (!sendFrom) {
      toast.error(t("None of your accounts can send yet. Add an account that can send."));
      return;
    }
    setCompose({ account: sendFrom.key, to: "", cc: "", subject: "", body: "" });
  };

  if (isLoading) {
    return <div className="p-4 sm:p-6"><Skeleton className="h-[70dvh] rounded-[var(--radius-md)]" /></div>;
  }
  if (error) return <p role="alert" className="p-6 text-danger">{errorMessage(error)}</p>;

  const current = accounts.find((a) => a.key === account);
  const accountOptions = [{ value: ALL, label: t("All inboxes") }, ...accounts.map((a) => ({ value: a.key, label: accountName(a) }))];

  return (
    <div className="flex h-[calc(100dvh-3.5rem-env(safe-area-inset-top)-4.5rem-env(safe-area-inset-bottom))] min-h-[26rem] min-w-0 md:h-[calc(100dvh-3.5rem-env(safe-area-inset-top))]">
      {/* Accounts and folders (wide screens) */}
      <aside aria-label={t("Accounts and folders")} className="hidden w-60 shrink-0 flex-col border-r border-border bg-surface lg:flex">
        <div className="p-3">
          <Button className="w-full" onClick={newMail} disabled={!accounts.length}><PencilSimpleIcon size={16} /> {t("New email")}</Button>
        </div>
        <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
          <p className="px-2 pt-1 pb-1 text-[11px] font-semibold tracking-wide text-muted uppercase">{t("Accounts")}</p>
          <SideRow active={account === ALL} icon={TrayIcon} label={t("All inboxes")} onClick={() => go({ account: ALL })} />
          {accounts.map((a) => (
            <div key={a.key} className="group relative">
              <SideRow active={account === a.key} icon={EnvelopeSimpleIcon} label={accountName(a)} sub={PROVIDER_LABEL[a.provider]} warn={a.status !== "ok" ? (a.error ?? t("Needs attention")) : undefined}
                onClick={() => go({ account: a.key, folder: "inbox" })} />
              <Menu>
                <MenuTrigger asChild>
                  <button type="button" aria-label={t("{name}: more", { name: accountName(a) })}
                    className="absolute top-1.5 right-1 grid size-7 place-items-center rounded-sm text-muted opacity-0 group-hover:opacity-100 hover:bg-surface-2 focus-visible:opacity-100">
                    <CaretDownIcon size={13} />
                  </button>
                </MenuTrigger>
                <MenuContent align="end" className="w-56">
                  <MenuLabel>{a.email}</MenuLabel>
                  <MenuSeparator />
                  <MenuItem icon={<TrashIcon />} onSelect={() => setRemoving(a)}>{t("Remove from the inbox")}</MenuItem>
                </MenuContent>
              </Menu>
            </div>
          ))}
          <button type="button" onClick={() => setAdding(true)} className="mt-1 flex h-9 w-full items-center gap-2 rounded-sm px-2.5 text-[13px] text-accent hover:bg-surface-2">
            <PlusIcon size={15} /> {t("Add account")}
          </button>
          {account !== ALL ? (
            <>
              <p className="px-2 pt-4 pb-1 text-[11px] font-semibold tracking-wide text-muted uppercase">{t("Folders")}</p>
              {folders.map((f) => (
                <SideRow key={f.id} active={folder === f.id} icon={FOLDER_ICON[f.id] ?? TrayIcon} label={t(f.name)} onClick={() => go({ folder: f.id })} />
              ))}
            </>
          ) : null}
        </nav>
      </aside>

      {!accounts.length ? (
        <div className="grid flex-1 place-items-center p-6">
          <EmptyState icon={EnvelopeSimpleIcon} title={t("No email accounts yet")}
            body={t("Add your Microsoft 365, Gmail or any other account. All of them show here in one inbox, and your AI can summarize and draft replies.")}
            action={<Button onClick={() => setAdding(true)}><PlusIcon size={16} /> {t("Add account")}</Button>} />
        </div>
      ) : (
        <>
          {/* Message list */}
          <section aria-label={t("Messages")}
            className={cn("relative min-w-0 flex-col border-r border-border md:flex md:w-[22rem] md:shrink-0 xl:w-[26rem]", openId ? "hidden" : "flex w-full")}>
            <div className="grid shrink-0 gap-2 border-b border-border p-3">
              <div className="flex min-w-0 items-center gap-2 lg:hidden">
                <Select size="sm" label={t("Account")} value={account} onValueChange={(v) => go({ account: v, folder: "inbox" })} options={accountOptions} className="min-w-0 flex-1" />
                {account !== ALL ? (
                  <Select size="sm" label={t("Folder")} value={folder} onValueChange={(v) => go({ folder: v })} options={folders.map((f) => ({ value: f.id, label: t(f.name) }))} className="w-32" />
                ) : null}
                <Button size="icon-sm" variant="outline" aria-label={t("Add account")} title={t("Add account")} onClick={() => setAdding(true)}><PlusIcon size={15} /></Button>
              </div>
              <div className="flex min-w-0 items-center gap-2">
                <SearchInput value={q} onChange={setQ} placeholder={account === ALL ? t("Search (pick an account to search)") : t("Search mail")} className="basis-0" />
                <button type="button" aria-pressed={unread} onClick={() => setUnread((u) => !u)}
                  className={cn("h-10 shrink-0 rounded-sm border px-2.5 text-[12.5px] font-medium", unread ? "border-accent/50 bg-accent-soft text-accent" : "border-border text-muted hover:text-fg")}>
                  {t("Unread")}
                </button>
              </div>
              {current && current.status !== "ok" ? (
                <p className="flex items-start gap-1.5 rounded-sm bg-warn/10 px-2.5 py-1.5 text-[12px] text-warn">
                  <WarningCircleIcon size={14} className="mt-px shrink-0" /> {current.error ?? t("This account needs to be connected again.")}
                </p>
              ) : null}
              {problems.length ? (
                <p className="flex items-start gap-1.5 rounded-sm bg-warn/10 px-2.5 py-1.5 text-[12px] text-warn">
                  <WarningCircleIcon size={14} className="mt-px shrink-0" />
                  {t("Could not read {list}.", { list: problems.map((p) => accounts.find((a) => a.key === p.account)?.email ?? p.account).join(", ") })}
                </p>
              ) : null}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">
              {list.isLoading ? (
                <div className="grid gap-px">{[0, 1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="m-2 h-14" />)}</div>
              ) : list.error ? (
                <p role="alert" className="p-4 text-[13px] text-danger">{errorMessage(list.error)}</p>
              ) : !rows.length ? (
                <p className="p-6 text-center text-[13px] text-muted">{needle || unread ? t("Nothing matches.") : t("No mail here.")}</p>
              ) : (
                <ul className="divide-y divide-border/70">
                  {rows.map((r) => (
                    <li key={`${r.account}:${r.id}`}>
                      <MessageRow row={r} active={r.id === openId} showAccount={account === ALL ? accounts.find((a) => a.key === r.account) : undefined}
                        onOpen={() => go({ msg: r.id, folder: account === ALL ? undefined : folder })} />
                    </li>
                  ))}
                </ul>
              )}
              {list.hasNextPage ? (
                <div className="p-3">
                  <Button variant="outline" size="sm" className="w-full" loading={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()}>{t("Load more")}</Button>
                </div>
              ) : null}
            </div>
            <Button className="absolute right-4 bottom-[calc(5.25rem+env(safe-area-inset-bottom))] z-20 size-13 rounded-full shadow-[var(--shadow-pop)] md:hidden" size="icon" aria-label={t("New email")} onClick={newMail}>
              <PencilSimpleIcon size={20} />
            </Button>
          </section>

          {/* Reader */}
          <section aria-label={t("Email")} className={cn("min-w-0 flex-1 flex-col bg-bg", openId ? "flex" : "hidden md:flex")}>
            {openId && openAccount ? (
              <Reader key={`${openAccount}:${openId}`} account={openAccount} id={openId} myEmail={accounts.find((a) => a.key === openAccount)?.email}
                onBack={() => go({ folder: account === ALL ? undefined : folder })}
                onCompose={(c) => {
                  const from = accounts.find((a) => a.key === c.account);
                  setCompose(from?.can_send || !sendFrom ? c : { ...c, account: sendFrom.key });
                }} />
            ) : (
              <div className="grid flex-1 place-items-center p-6 text-center text-[13px] text-muted">
                <span className="grid justify-items-center gap-2"><EnvelopeSimpleIcon size={32} weight="duotone" className="text-border" /> {t("Pick an email to read it.")}</span>
              </div>
            )}
          </section>
        </>
      )}

      <AddAccountDialog open={adding} onOpenChange={setAdding} connect={home?.connect} />
      {compose ? <Composer init={compose} accounts={accounts} onClose={() => setCompose(null)} /> : null}
      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} danger
        title={t("Remove {email}?", { email: removing?.email ?? "" })} confirmLabel={t("Remove")}
        body={t("Its mail stays with the provider; it is only taken out of this inbox. You can add it again later.")}
        onConfirm={() => { if (removing) remove.mutate(removing); }} />
    </div>
  );
}

function SideRow({ active, icon: IconCmp, label, sub, warn, onClick }: { active: boolean; icon: Icon; label: string; sub?: string; warn?: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} aria-current={active ? "true" : undefined} title={warn ?? label}
      className={cn("flex min-h-9 w-full min-w-0 items-center gap-2.5 rounded-sm py-1.5 pr-8 pl-2.5 text-left text-[13px] transition-colors",
        active ? "bg-accent-soft font-medium text-accent" : "text-fg hover:bg-surface-2")}>
      <IconCmp size={16} weight={active ? "fill" : "regular"} className="shrink-0" />
      <span className="grid min-w-0 flex-1">
        <span className="truncate">{label}</span>
        {sub ? <span className="truncate text-[11px] font-normal text-muted">{sub}</span> : null}
      </span>
      {warn ? <WarningCircleIcon size={14} weight="fill" className="shrink-0 text-warn" /> : null}
    </button>
  );
}

export function MessageRow({ row, active, showAccount, onOpen }: { row: InboxRow; active: boolean; showAccount?: InboxAccount; onOpen: () => void }) {
  const t = useT();
  const unread = !row.is_read;
  return (
    <button type="button" onClick={onOpen} aria-current={active ? "true" : undefined}
      className={cn("grid w-full min-w-0 gap-0.5 px-3.5 py-2.5 text-left transition-colors", active ? "bg-accent-soft/60" : "hover:bg-surface-2/60")}>
      <span className="flex min-w-0 items-center gap-2">
        {unread ? <span aria-label={t("Unread")} className="size-2 shrink-0 rounded-full bg-accent" /> : null}
        <span className={cn("min-w-0 flex-1 truncate text-[13.5px]", unread ? "font-semibold" : "text-fg/90")}>
          {row.is_draft ? <span className="text-danger">{t("Draft")} · </span> : null}
          {showAddr(row.from) || t("(unknown sender)")}
        </span>
        {row.flagged ? <FlagIcon size={12} weight="fill" className="shrink-0 text-danger" /> : null}
        {row.has_attachments ? <PaperclipIcon size={13} className="shrink-0 text-muted" aria-label={t("Has attachments")} /> : null}
        <time dateTime={row.received_at} className={cn("shrink-0 text-[11.5px] tabular", unread ? "font-medium text-fg" : "text-muted")}>{shortWhen(row.received_at, new Date(), locale())}</time>
      </span>
      <span className={cn("truncate text-[13px]", unread ? "font-medium" : "text-fg/80")}>{row.subject || t("(no subject)")}</span>
      <span className="line-clamp-1 text-[12px] text-muted">
        {showAccount ? <span className="mr-1 rounded-full bg-surface-2 px-1.5 text-[10.5px]">{accountName(showAccount)}</span> : null}
        {row.preview}
      </span>
    </button>
  );
}
