/** Add an email account: Microsoft 365 or Gmail by signing in, or any other account by IMAP
 * (with an app password for Gmail and Yahoo). */
import { ArrowLeftIcon, EnvelopeSimpleIcon, GoogleLogoIcon, MicrosoftOutlookLogoIcon } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState, type FormEvent, type ReactNode } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ResponsiveDialog } from "@/components/ui/dialog";
import { Field, FormError } from "@/components/ui/field";
import { Select } from "@/components/ui/select";
import { useT } from "@/i18n";
import { ApiError, errorMessage } from "@/lib/api";
import {
  addImapAccount,
  connectGoogle,
  connectMicrosoft,
  inboxKeys,
  mailAccountsQuery,
  type ImapProvider,
  type InboxAccounts,
} from "@/lib/inbox";

const PROVIDERS: { value: ImapProvider; label: string }[] = [
  { value: "gmail", label: "Gmail" },
  { value: "yahoo", label: "Yahoo Mail" },
  { value: "outlook", label: "Outlook.com / Hotmail" },
  { value: "cpanel", label: "cPanel / company hosting" },
  { value: "other", label: "Other" },
];

export function AddAccountDialog({ open, onOpenChange, connect }: { open: boolean; onOpenChange: (o: boolean) => void; connect: InboxAccounts["connect"] | undefined }) {
  const t = useT();
  const [imap, setImap] = useState(false);
  const go = useMutation({
    mutationFn: (which: "microsoft" | "google") => (which === "microsoft" ? connectMicrosoft() : connectGoogle()),
    onSuccess: (r) => {
      window.location.href = r.url;
    },
    onError: (e, which) => {
      if (e instanceof ApiError && (e.status === 409 || e.code === "not_configured")) {
        toast.error(which === "microsoft"
          ? t("Microsoft 365 is not set up yet. Set it up in Settings > Channels > Microsoft 365 first.")
          : t("Google sign-in is not set up yet. Add the Google app in Settings > Channels first."));
      } else toast.error(errorMessage(e));
    },
  });
  const close = (o: boolean) => {
    onOpenChange(o);
    if (!o) setImap(false);
  };
  return (
    <ResponsiveDialog open={open} onOpenChange={close} title={imap ? t("Add an account by IMAP") : t("Add an email account")}
      description={imap ? undefined : t("Sign in with Microsoft or Google, or add any other account with its IMAP settings.")}>
      {imap ? (
        <ImapForm onBack={() => setImap(false)} onDone={() => close(false)} />
      ) : (
        <div className="grid gap-2">
          <Choice icon={<MicrosoftOutlookLogoIcon size={22} className="text-[#0a64ad]" />} title={t("Microsoft 365 or Outlook")} hint={connect?.microsoft ? t("Sign in with Microsoft. Mail, calendar and Teams.") : t("Set up Microsoft 365 in Settings > Channels first.")}
            busy={go.isPending && go.variables === "microsoft"} onClick={() => go.mutate("microsoft")} />
          <Choice icon={<GoogleLogoIcon size={22} className="text-[#ea4335]" />} title={t("Gmail (sign in with Google)")} hint={connect?.google ? t("Sign in with Google.") : t("Google sign-in is not set up yet: use IMAP with an app password below.")}
            busy={go.isPending && go.variables === "google"} onClick={() => go.mutate("google")} />
          <Choice icon={<EnvelopeSimpleIcon size={22} className="text-accent" />} title={t("Any other account (IMAP)")} hint={t("Yahoo, company mail, cPanel, or Gmail with an app password.")} onClick={() => setImap(true)} />
          {!connect?.microsoft ? (
            <p className="text-[12.5px] text-muted">{t("Microsoft and Google sign-in need their apps set up once.")} <Link to="/channels" className="font-medium text-accent hover:underline">{t("Open Channels")}</Link></p>
          ) : null}
        </div>
      )}
    </ResponsiveDialog>
  );
}

function Choice({ icon, title, hint, onClick, busy }: { icon: ReactNode; title: string; hint: string; onClick: () => void; busy?: boolean }) {
  return (
    <button type="button" onClick={onClick} disabled={busy}
      className="flex min-h-16 w-full min-w-0 items-center gap-3 rounded-[var(--radius-md)] border border-border bg-surface px-3.5 py-3 text-left transition-colors hover:border-accent/40 hover:bg-surface-2/50 disabled:opacity-60">
      <span className="grid size-10 shrink-0 place-items-center rounded-full bg-surface-2">{icon}</span>
      <span className="grid min-w-0 flex-1 gap-0.5">
        <span className="text-[14px] font-medium">{title}</span>
        <span className="text-[12.5px] text-muted">{hint}</span>
      </span>
      {busy ? <span className="size-4 shrink-0 animate-spin rounded-full border-2 border-accent border-t-transparent" /> : null}
    </button>
  );
}

function ImapForm({ onBack, onDone }: { onBack: () => void; onDone: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const { data: home } = useQuery(mailAccountsQuery);
  const [provider, setProvider] = useState<ImapProvider>("gmail");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [label, setLabel] = useState("");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("");
  const [username, setUsername] = useState("");
  const [smtpHost, setSmtpHost] = useState("");
  const [smtpPort, setSmtpPort] = useState("");
  const [more, setMore] = useState(false);
  const preset = home?.presets[provider];
  const smtpPreset = home?.smtp_presets[provider];
  const needsServer = provider === "cpanel" || provider === "other";
  const add = useMutation({
    mutationFn: () =>
      addImapAccount({
        email: email.trim(),
        provider,
        host: host.trim() || preset?.host || "",
        port: Number(port) || preset?.port || 993,
        security: preset?.security ?? "ssl",
        username: username.trim() || email.trim(),
        password,
        smtp_host: smtpHost.trim() || smtpPreset?.host || "",
        smtp_port: Number(smtpPort) || smtpPreset?.port || null,
        smtp_security: smtpPreset?.security ?? null,
        label: label.trim(),
      }),
    onSuccess: () => {
      toast.success(t("Account added."));
      void qc.invalidateQueries({ queryKey: inboxKeys.all });
      void qc.invalidateQueries({ queryKey: mailAccountsQuery.queryKey });
      onDone();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    add.mutate();
  };
  const appPassword = provider === "gmail" || provider === "yahoo";
  return (
    <form className="grid gap-3" onSubmit={submit}>
      <Button type="button" variant="ghost" size="sm" className="justify-self-start" onClick={onBack}><ArrowLeftIcon size={14} /> {t("Back")}</Button>
      <Select label={t("Provider")} value={provider} onValueChange={(v) => setProvider(v as ImapProvider)} options={PROVIDERS.map((p) => ({ value: p.value, label: t(p.label) }))} />
      <Field label={t("Email address")} type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" />
      <Field label={appPassword ? t("App password") : t("Password")} type="password" required value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password"
        hint={appPassword
          ? t("Use an app password, not your normal password: turn on 2-step verification in your Google or Yahoo account, then create an app password there and paste it here.")
          : t("Stored encrypted. Used only to read and send your mail.")} />
      <Field label={t("Name in the list (optional)")} value={label} onChange={(e) => setLabel(e.target.value)} maxLength={40} placeholder={t("e.g. Work, Personal")} />
      {needsServer || more ? (
        <div className="grid gap-3 rounded-[var(--radius-md)] border border-border p-3">
          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_7rem]">
            <Field label={t("IMAP server")} value={host} onChange={(e) => setHost(e.target.value)} placeholder={preset?.host || "mail.example.com"} required={needsServer && !preset?.host} />
            <Field label={t("Port")} value={port} onChange={(e) => setPort(e.target.value.replace(/\D/g, ""))} placeholder={String(preset?.port ?? 993)} inputMode="numeric" />
          </div>
          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_7rem]">
            <Field label={t("SMTP server (sending)")} value={smtpHost} onChange={(e) => setSmtpHost(e.target.value)} placeholder={smtpPreset?.host || t("Same as IMAP")} />
            <Field label={t("Port")} value={smtpPort} onChange={(e) => setSmtpPort(e.target.value.replace(/\D/g, ""))} placeholder={String(smtpPreset?.port ?? 465)} inputMode="numeric" />
          </div>
          <Field label={t("Username (if not the email address)")} value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" />
        </div>
      ) : (
        <button type="button" onClick={() => setMore(true)} className="justify-self-start text-[12.5px] font-medium text-accent hover:underline">{t("Server settings")}</button>
      )}
      <FormError message={add.error ? errorMessage(add.error) : null} />
      <Button type="submit" loading={add.isPending} disabled={!email.trim() || !password}>{t("Add account")}</Button>
    </form>
  );
}
