import { setBadge, syncPush } from "@/lib/push";
import {
  CaretDownIcon,
  CommandIcon,
  DotsThreeIcon,
  KeyIcon,
  ListIcon,
  MagnifyingGlassIcon,
  MonitorIcon,
  MoonIcon,
  PlusIcon,
  SidebarSimpleIcon,
  SignOutIcon,
  SquaresFourIcon,
  SunIcon,
} from "@phosphor-icons/react";
import { useQuery, useSuspenseQuery } from "@tanstack/react-query";
import { Link, Outlet, useNavigate, useRouterState } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { Drawer } from "vaul";
import { create } from "zustand";

import { AiFab } from "@/components/ai-fab";
import { useBackClose } from "@/lib/back-close";
import { useLiveEvents } from "@/lib/live";
import { meQuery, systemStatusQuery } from "@/lib/queries";
import { useBranch, usePalette, useTheme, type ThemePref } from "@/lib/stores";
import { LanguageSwitch, useProfileLanguage } from "@/components/language-switch";
import { useT } from "@/i18n";
import { useMedia } from "@/lib/use-media";
import { useSignOut } from "@/lib/use-sign-out";
import { ROLE_INFO } from "@/lib/types";
import { cn, initials } from "@/lib/utils";
import { ALL_NAV, hubOf, moreItems, NAV, sidebarItems, tabBarFor, type NavItem, type NavSection } from "@/nav";

import { openTaskComposer } from "./task-composer/store";
import { HeaderSearch } from "./search-box";
import { LogoMark, Wordmark } from "./logo";
import { LazyCommandPalette, LazyTaskComposerHost } from "./lazy-hosts";
import { InstallApp } from "./install-app";
import { NeedsBell } from "./needs-bell";
import { NavProgress } from "./nav-progress";
import { OfflineBanner } from "./offline-banner";
import { Button } from "./ui/button";
import {
  Menu,
  MenuContent,
  MenuItem,
  MenuLabel,
  MenuRadioGroup,
  MenuRadioItem,
  MenuSeparator,
  MenuTrigger,
} from "./ui/menu";

const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

/** P49: "Show all pages": advanced pages (few people need them) are listed only when on. */
const SHOW_ALL_KEY = "agentic.nav.all";
const useShowAll = create<{ on: boolean; toggle: () => void }>((set, get) => ({
  on: (() => {
    try {
      return localStorage.getItem(SHOW_ALL_KEY) === "1";
    } catch {
      return false;
    }
  })(),
  toggle: () => {
    const on = !get().on;
    try {
      localStorage.setItem(SHOW_ALL_KEY, on ? "1" : "0");
    } catch {
      /* private mode: it lasts until the page reloads */
    }
    set({ on });
  },
}));

/** P116: the sidebar folds to icons or opens with names, each person's choice on this device
 * (until they choose, it follows the screen: names from 1280px). Phones open it as a drawer. */
const NAV_WIDE_KEY = "agentic.nav.wide";
function readWide(): boolean | null {
  try {
    const v = localStorage.getItem(NAV_WIDE_KEY);
    return v === "1" ? true : v === "0" ? false : null;
  } catch {
    return null;
  }
}
const useNavWide = create<{ chosen: boolean | null; choose: (wide: boolean) => void }>((set) => ({
  chosen: readWide(),
  choose: (wide) => {
    try {
      localStorage.setItem(NAV_WIDE_KEY, wide ? "1" : "0");
    } catch {
      /* private mode: it lasts until the page reloads */
    }
    set({ chosen: wide });
  },
}));
export const useNavDrawer = create<{ open: boolean; setOpen: (open: boolean) => void }>((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
}));

const allowedItem = (i: NavItem, perms: string[]) => !i.perm || [i.perm].flat().some((p) => perms.includes(p));

function useVisibleNav() {
  const { data: me } = useSuspenseQuery(meQuery);
  const showAll = useShowAll((s) => s.on);
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  return useMemo(
    () =>
      NAV.map((s) => ({
        ...s,
        // P52: a hub's pages are one entry (its tabs); hidden pages of a hub can lead it.
        items: sidebarItems(s.items.filter((i) => (!i.hidden || hubOf(i.to)) && allowedItem(i, me.permissions)), me.permissions)
          .filter((i) => showAll || !i.advanced || isActive(pathname, i.to)),
      })).filter((s) => s.items.length),
    [me.permissions, showAll, pathname],
  );
}

/** How many advanced pages this person could also open ("Show all pages (6 more)"). */
function useHiddenCount() {
  const { data: me } = useSuspenseQuery(meQuery);
  return ALL_NAV.filter((i) => i.advanced && !i.hidden && !hubOf(i.to) && allowedItem(i, me.permissions)).length;
}

/** P49: find a page by name or what it is for. */
function NavSearch() {
  const t = useT();
  const navigate = useNavigate();
  const { data: me } = useSuspenseQuery(meQuery);
  const [q, setQ] = useState("");
  const needle = q.trim().toLowerCase();
  const hits = needle.length < 2 ? [] : ALL_NAV.filter((i) => allowedItem(i, me.permissions))
    .map((i) => ({ i, label: t(i.label), about: t(i.blurb) }))
    .filter((x) => x.label.toLowerCase().includes(needle) || x.about.toLowerCase().includes(needle) || x.i.to.includes(needle))
    .sort((a, b) => Number(b.label.toLowerCase().includes(needle)) - Number(a.label.toLowerCase().includes(needle)))
    .slice(0, 7);
  const open = (to: string) => { setQ(""); useNavDrawer.getState().setOpen(false); void navigate({ to }); };
  return (
    <div className="relative mx-3 mb-2 hidden wide:block">
      <MagnifyingGlassIcon size={15} className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-muted" />
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("Find a page…")} aria-label={t("Find a page")}
        onKeyDown={(e) => {
          if (e.key === "Escape") setQ("");
          if (e.key === "Enter") {
            if (hits[0]) open(hits[0].i.to);
          }
        }}
        className="h-9 w-full rounded-sm border border-border bg-bg pr-2 pl-8 text-[13px] focus-visible:border-accent focus-visible:outline-none" />
      {needle.length >= 2 && hits.length ? (
        <div className="absolute inset-x-0 top-10 z-40 grid gap-0.5 rounded-[var(--radius-md)] border border-border bg-surface p-1 shadow-[var(--shadow-pop)]">
          {hits.map(({ i, label, about }) => {
            const Ico = i.icon;
            return (
              <button key={i.to} type="button" onClick={() => open(i.to)}
                className="flex min-w-0 items-start gap-2 rounded-sm px-2 py-1.5 text-left hover:bg-surface-2">
                <Ico size={16} className="mt-0.5 shrink-0 text-accent" />
                <span className="grid min-w-0">
                  <span className="truncate text-[13px] font-medium">{label}</span>
                  <span className="line-clamp-1 text-[11.5px] text-muted">{about}</span>
                </span>
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

/** Which sidebar groups are open: each person's own choice (kept on this device), else the
 * group's default (everyday groups open; the AI team and how-we-work groups open for people
 * who manage; setup folded). The group of the page you are on is always open. */
const OPEN_KEY = "agentic.nav.open";

function readOpen(): Record<string, boolean> {
  try {
    return JSON.parse(localStorage.getItem(OPEN_KEY) ?? "{}") as Record<string, boolean>;
  } catch {
    return {};
  }
}

function useOpenGroups() {
  const { data: me } = useSuspenseQuery(meQuery);
  const manages = ["agents.manage", "org.manage", "team.manage"].some((p) => me.permissions.includes(p));
  const [chosen, setChosen] = useState<Record<string, boolean>>(readOpen);
  const isOpen = (s: NavSection) => chosen[s.title] ?? (s.open === "all" || (s.open === "managers" && manages));
  const toggle = (s: NavSection) => {
    const next = { ...chosen, [s.title]: !isOpen(s) };
    setChosen(next);
    try {
      localStorage.setItem(OPEN_KEY, JSON.stringify(next));
    } catch {
      // private mode: the choice lasts until the page reloads
    }
  };
  return { isOpen, toggle };
}

function matches(pathname: string, to: string) {
  return to === "/" ? pathname === "/" : pathname === to || pathname.startsWith(`${to}/`);
}

function isActive(pathname: string, to: string) {
  const item = ALL_NAV.find((n) => n.to === to);
  const tabs = hubOf(to)?.tabs ?? [];
  return matches(pathname, to) || !!item?.also?.some((a) => matches(pathname, a)) || tabs.some((a) => a !== "/" && matches(pathname, a));
}

function PhaseTag({ phase }: { phase: string }) {
  return (
    <span className="ml-auto rounded-full bg-surface-2 px-1.5 text-[10.5px] font-medium text-muted tabular">
      {phase}
    </span>
  );
}

function Sidebar({ drawer = false, onPick }: { drawer?: boolean; onPick?: () => void }) {
  const t = useT();
  const xl = useMedia("(min-width: 1280px)");
  const chosen = useNavWide((s) => s.chosen);
  const choose = useNavWide((s) => s.choose);
  const wide = drawer || (chosen ?? xl);
  const sections = useVisibleNav();
  const showAll = useShowAll();
  const more = useHiddenCount();
  const groups = useOpenGroups();
  const waiting = useWaiting();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  return (
    <aside
      data-nav={wide ? "wide" : "rail"}
      onClickCapture={onPick ? (e) => { if ((e.target as HTMLElement).closest("a[href]")) onPick(); } : undefined}
      className={cn(
        "flex-col bg-surface",
        drawer ? "flex h-full w-full" : "sticky top-0 hidden h-dvh w-[68px] shrink-0 border-r border-border transition-[width] duration-200 md:flex wide:w-[244px]",
      )}
    >
      <div className="flex h-14 shrink-0 items-center gap-1 px-[18px] wide:pr-2 wide:pl-4">
        <Link to="/" className="flex items-center" aria-label={t("My Agentic home")}>
          <span className="wide:hidden">
            <LogoMark />
          </span>
          <Wordmark className="hidden wide:flex" />
        </Link>
        {!drawer && wide ? (
          <button type="button" onClick={() => choose(false)} aria-label={t("Fold the menu")} title={t("Fold the menu")}
            className="ml-auto grid size-8 place-items-center rounded-sm text-muted transition-colors hover:bg-surface-2 hover:text-fg">
            <SidebarSimpleIcon size={18} />
          </button>
        ) : null}
      </div>
      {!drawer && !wide ? (
        <button type="button" onClick={() => choose(true)} aria-label={t("Open the menu with names")} title={t("Open the menu with names")}
          className="mx-3 mb-2 flex h-9 shrink-0 items-center justify-center rounded-sm text-muted transition-colors hover:bg-surface-2 hover:text-fg">
          <SidebarSimpleIcon size={19} weight="fill" />
        </button>
      ) : null}
      <NavSearch />
      <nav className="flex-1 overflow-y-auto overscroll-contain px-3 pb-4" aria-label={t("Main")}>
        {sections.map((section) => {
          const here = section.items.some((i) => isActive(pathname, i.to));
          const open = here || groups.isOpen(section);
          const waitingHere = section.items.reduce((n, i) => n + (waiting[i.to] ?? 0), 0);
          return (
            <div key={section.title} className="mt-3 border-t border-border/60 pt-2 first:mt-1 first:border-0 first:pt-0 wide:border-0 wide:pt-0">
              <button
                type="button"
                onClick={() => groups.toggle(section)}
                aria-expanded={open}
                disabled={here}
                title={t(section.hint)}
                className="hidden w-full items-center gap-1.5 rounded-sm px-2.5 py-1 text-left text-[10.5px] font-semibold tracking-[0.08em] text-muted/80 uppercase transition-colors hover:text-fg disabled:cursor-default disabled:hover:text-muted/80 wide:flex"
              >
                <span className="min-w-0 flex-1 truncate">{t(section.title)}</span>
                {!open && waitingHere ? <Badge count={waitingHere} className="normal-case" /> : null}
                {here ? null : <CaretDownIcon size={11} weight="bold" className={cn("shrink-0 transition-transform", !open && "-rotate-90")} />}
              </button>
              {open ? (
                <p className="hidden px-2.5 pb-1.5 text-[11.5px] leading-snug text-muted wide:block">{t(section.hint)}</p>
              ) : null}
              <ul className={cn("grid gap-0.5", !open && "wide:hidden")}>
                {section.items.map((item) => {
                  const active = isActive(pathname, item.to);
                  const IconCmp = item.icon;
                  return (
                    <li key={item.to}>
                      <Link
                        to={item.to}
                        title={`${t(item.label)}: ${t(item.blurb)}`}
                        className={cn(
                          "relative flex h-9 items-center gap-2.5 rounded-sm px-2.5 text-[13.5px] transition-colors",
                          "justify-center wide:justify-start",
                          active
                            ? "bg-accent-soft font-medium text-accent before:absolute before:top-2 before:bottom-2 before:-left-3 before:w-[3px] before:rounded-r-full before:bg-accent"
                            : "text-muted hover:bg-surface-2 hover:text-fg",
                        )}
                      >
                        <span className="relative">
                          <IconCmp size={19} weight={active ? "fill" : "regular"} />
                          {waiting[item.to] ? <span className="absolute -top-1 -right-1 size-2 rounded-full bg-warn wide:hidden" /> : null}
                        </span>
                        <span className="hidden truncate wide:inline">{t(item.label)}</span>
                        <Badge count={waiting[item.to] ?? 0} className="ml-auto hidden wide:grid" />
                        {item.phase ? (
                          <span className="hidden wide:contents">
                            <PhaseTag phase={item.phase} />
                          </span>
                        ) : null}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
        {more ? (
          <button type="button" onClick={showAll.toggle}
            className="mt-3 hidden w-full items-center gap-2 rounded-sm px-2.5 py-1.5 text-left text-[12.5px] text-muted hover:bg-surface-2 hover:text-fg wide:flex">
            <SquaresFourIcon size={15} />
            {showAll.on ? t("Show fewer pages") : t("Show all pages ({n} more)", { n: more })}
          </button>
        ) : null}
      </nav>
    </aside>
  );
}

const THEME_ICON = { light: SunIcon, dark: MoonIcon, system: MonitorIcon } as const;

function ThemeMenu() {
  const t = useT();
  const { pref, setPref } = useTheme();
  const IconCmp = THEME_ICON[pref];
  return (
    <Menu>
      <MenuTrigger asChild>
        {/* P96: on phones the theme is in the account menu, so the header has room. */}
        <Button variant="ghost" size="icon-sm" className="max-sm:hidden" aria-label={t("Theme")}>
          <IconCmp size={18} />
        </Button>
      </MenuTrigger>
      <MenuContent className="w-44">
        <MenuLabel>{t("Theme")}</MenuLabel>
        <MenuRadioGroup value={pref} onValueChange={(v) => setPref(v as ThemePref)}>
          <MenuRadioItem value="light">{t("Light")}</MenuRadioItem>
          <MenuRadioItem value="dark">{t("Dark")}</MenuRadioItem>
          <MenuRadioItem value="system">{t("Match system")}</MenuRadioItem>
        </MenuRadioGroup>
      </MenuContent>
    </Menu>
  );
}

export function UserMenu() {
  const { data: me } = useSuspenseQuery(meQuery);
  const t = useT();
  const { pref, setPref } = useTheme();
  useProfileLanguage();
  const signOut = useSignOut();
  const navigate = useNavigate();
  return (
    <Menu>
      <MenuTrigger asChild>
        <button
          className="grid size-8 place-items-center rounded-full bg-accent-soft text-[12px] font-semibold text-accent"
          aria-label={t("Account")}
        >
          {initials(me.user.name)}
        </button>
      </MenuTrigger>
      <MenuContent className="w-60">
        <div className="px-2.5 py-2">
          <p className="truncate text-[13.5px] font-medium">{me.user.name}</p>
          <p className="truncate text-[12.5px] text-muted">{me.user.email}</p>
          <p className="mt-1 text-[12px] text-muted">
            {me.workspace.name} · <span className={ROLE_INFO[me.role] ? undefined : "capitalize"}>{ROLE_INFO[me.role] ? t(ROLE_INFO[me.role].label) : me.role}</span>
          </p>
        </div>
        <MenuSeparator />
        <div className="flex items-center justify-between gap-3 px-2.5 py-1.5">
          <span className="text-[12.5px] text-muted">{t("Language")}</span>
          <LanguageSwitch />
        </div>
        <MenuSeparator />
        {/* P96: phones have no theme button in the header; the choice lives here. */}
        <div className="sm:hidden">
          <MenuLabel>{t("Theme")}</MenuLabel>
          <MenuRadioGroup value={pref} onValueChange={(v) => setPref(v as ThemePref)}>
            <MenuRadioItem value="light">{t("Light")}</MenuRadioItem>
            <MenuRadioItem value="dark">{t("Dark")}</MenuRadioItem>
            <MenuRadioItem value="system">{t("Match system")}</MenuRadioItem>
          </MenuRadioGroup>
          <MenuSeparator />
        </div>
        <MenuItem icon={<KeyIcon />} onSelect={() => navigate({ to: "/change-password" })}>
          {t("Change password")}
        </MenuItem>
        <MenuItem icon={<SignOutIcon />} onSelect={signOut}>
          {t("Sign out")}
        </MenuItem>
      </MenuContent>
    </Menu>
  );
}

function useApprovalCount() {
  const { data } = useQuery(systemStatusQuery);
  return data?.counts.approvals_pending ?? 0;
}

/** Things waiting for a person, per nav item: decisions and skill proposals. */
function useWaiting(): Partial<Record<string, number>> {
  const { data } = useQuery(systemStatusQuery);
  return {
    "/approvals": data?.counts.approvals_pending ?? 0,
    "/skills": data?.counts.skill_proposals_pending ?? 0,
    "/documents": data?.counts.documents_review ?? 0, // P25: what AI made, waiting for review
    "/files": data?.counts.documents_review ?? 0, // the file store's "Needs review" view
  };
}

function Badge({ count, className }: { count: number; className?: string }) {
  const t = useT();
  if (!count) return null;
  return (
    <span className={cn("grid h-[18px] min-w-[18px] place-items-center rounded-full bg-warn px-1 text-[10.5px] font-semibold text-white tabular", className)} aria-label={t("{n} waiting", { n: count })}>
      {count > 99 ? "99+" : count}
    </span>
  );
}

function Header() {
  const t = useT();
  const setOpen = usePalette((s) => s.setOpen);
  const { data: me } = useSuspenseQuery(meQuery);
  const canWrite = me.permissions.includes("work.write");
  return (
    <header
      // P96: the header grows by the status bar / notch (a wrapped app draws under it) instead
      // of the notch eating its 3.5rem; the sides keep clear of a landscape notch.
      className="sticky top-0 z-30 flex h-[calc(3.5rem+env(safe-area-inset-top))] items-center gap-2 border-b border-border bg-bg/85 pt-[env(safe-area-inset-top)] pr-[max(0.75rem,env(safe-area-inset-right))] pl-[max(0.75rem,env(safe-area-inset-left))] backdrop-blur-md sm:pr-[max(1rem,env(safe-area-inset-right))] sm:pl-[max(1rem,env(safe-area-inset-left))] md:px-4"
    >
      <Button variant="ghost" size="icon-sm" className="-ml-1 md:hidden" aria-label={t("Menu")} title={t("Menu")}
        onClick={() => useNavDrawer.getState().setOpen(true)}>
        <ListIcon size={21} />
      </Button>
      <Link to="/" className="-m-1.5 p-1.5 md:hidden" aria-label={t("Home")}>
        <LogoMark className="size-7" />
      </Link>
      <div className="min-w-0 flex-1" />
      {/* P25: search inside every document; the command palette stays on Ctrl K. */}
      <HeaderSearch />
      {/* One obvious place to hand out work, on every page. */}
      {canWrite ? (
        <Button size="sm" className="max-sm:size-9 max-sm:rounded-full max-sm:px-0" aria-label={t("New task")} title={t("New task")} onClick={() => openTaskComposer()}>
          <PlusIcon size={16} weight="bold" /><span className="max-sm:hidden">{t("New task")}</span>
        </Button>
      ) : null}
      <Button
        variant="ghost"
        size="icon-sm"
        className="hidden md:inline-flex"
        aria-label={t("Jump to a page or run an action…")}
        title={IS_MAC ? "⌘K" : "Ctrl K"}
        onClick={() => setOpen(true)}
      >
        <CommandIcon size={18} />
      </Button>
      {/* P48: everything waiting on this person, one click away. */}
      <NeedsBell />
      <ThemeMenu />
      <UserMenu />
    </header>
  );
}

function TabLink({ item, active, badge = 0 }: { item: NavItem; active: boolean; badge?: number }) {
  const t = useT();
  const IconCmp = item.icon;
  return (
    <Link
      to={item.to}
      className={cn(
        "flex min-h-12 flex-1 flex-col items-center gap-0.5 py-2 text-[11px] font-medium",
        active ? "text-accent" : "text-muted",
      )}
    >
      <span className="relative">
        <IconCmp size={22} weight={active ? "fill" : "regular"} />
        <Badge count={badge} className="absolute -top-1.5 -right-2.5" />
      </span>
      <span className="max-w-full truncate px-0.5">{t(item.short ?? item.label)}</span>
    </Link>
  );
}

function MobileTabBar() {
  const t = useT();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const approvals = useApprovalCount();
  const sections = useVisibleNav();
  const [more, setMore] = useState(false);
  useBackClose(more, () => setMore(false)); // P96: the phone's Back closes the page list
  const bar = tabBarFor();
  const tabs = bar.map((to) => ALL_NAV.find((n) => n.to === to)).filter(Boolean) as NavItem[];
  const moreActive = !tabs.some((tab) => isActive(pathname, tab.to));
  const moreSections = sections
    .map((s) => ({ ...s, items: moreItems(s.items, bar) }))
    .filter((s) => s.items.length);
  // When Approvals is under More, More carries its count.
  const moreBadge = bar.includes("/approvals") ? 0 : approvals;

  return (
    <>
      <nav
        aria-label={t("Main")}
        className="fixed inset-x-0 bottom-0 z-30 flex border-t border-border bg-surface/95 pr-[env(safe-area-inset-right)] pb-[env(safe-area-inset-bottom)] pl-[env(safe-area-inset-left)] backdrop-blur-md md:hidden"
      >
        {tabs.map((tab) => (
          <TabLink key={tab.to} item={tab} active={isActive(pathname, tab.to)} badge={tab.to === "/approvals" ? approvals : 0} />
        ))}
        <button
          type="button"
          onClick={() => setMore(true)}
          aria-expanded={more}
          className={cn(
            "flex min-h-12 flex-1 flex-col items-center gap-0.5 py-2 text-[11px] font-medium",
            moreActive ? "text-accent" : "text-muted",
          )}
        >
          <span className="relative">
            <DotsThreeIcon size={22} weight="bold" />
            <Badge count={moreBadge} className="absolute -top-1.5 -right-2.5" />
          </span>
          {t("More")}
        </button>
      </nav>
      <Drawer.Root open={more} onOpenChange={setMore}>
        <Drawer.Portal>
          <Drawer.Overlay className="fixed inset-0 z-40 bg-black/40" />
          {/* The sheet itself only drags; the list scrolls inside it (vaul treats a drag on the
              sheet as "move the sheet", so a scrolling sheet could never scroll on a phone). */}
          <Drawer.Content
            aria-describedby={undefined}
            className="fixed inset-x-0 bottom-0 z-50 flex max-h-[88dvh] flex-col rounded-t-[var(--radius-lg)] border-t border-border bg-surface outline-none"
          >
            <div aria-hidden className="mx-auto mt-2.5 mb-2 h-1.5 w-10 shrink-0 rounded-full bg-border" />
            <Drawer.Title className="sr-only">{t("All pages")}</Drawer.Title>
            <div
              data-vaul-no-drag
              className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pt-1 [-webkit-overflow-scrolling:touch]"
              style={{ paddingBottom: "calc(env(safe-area-inset-bottom) + 1.25rem)" }}
            >
            {moreSections.map((s) => (
              <div key={s.title} className="mb-3">
                <p className="px-1 text-[12.5px] font-semibold">{t(s.title)}</p>
                <p className="mb-2 px-1 text-[12px] leading-snug text-muted">{t(s.hint)}</p>
                <div className="grid grid-cols-3 gap-2">
                  {s.items.map((item) => {
                    const IconCmp = item.icon;
                    const active = isActive(pathname, item.to);
                    return (
                      <Link
                        key={item.to}
                        to={item.to}
                        onClick={() => setMore(false)}
                        className={cn(
                          "flex flex-col items-center gap-1 rounded-[var(--radius-md)] border px-2 py-2.5 text-center text-[12px]",
                          active ? "border-accent/40 bg-accent-soft text-accent" : "border-border text-fg",
                        )}
                      >
                        <span className="relative">
                          <IconCmp size={22} weight={active ? "fill" : "regular"} />
                          <Badge count={item.to === "/approvals" ? moreBadge : 0} className="absolute -top-1.5 -right-2.5" />
                        </span>
                        <span className="leading-tight">{t(item.label)}</span>
                      </Link>
                    );
                  })}
                </div>
              </div>
            ))}
            </div>
          </Drawer.Content>
        </Drawer.Portal>
      </Drawer.Root>
    </>
  );
}

/** P116: the whole sidebar on a phone, from the menu button in the header. */
function NavDrawer() {
  const t = useT();
  const open = useNavDrawer((s) => s.open);
  const setOpen = useNavDrawer((s) => s.setOpen);
  const phone = useMedia("(max-width: 767px)");
  useBackClose(open, () => setOpen(false));
  useEffect(() => {
    if (!phone && open) setOpen(false);
  }, [phone, open, setOpen]);
  return (
    <Drawer.Root direction="left" open={open && phone} onOpenChange={setOpen}>
      <Drawer.Portal>
        <Drawer.Overlay className="fixed inset-0 z-40 bg-black/40" />
        <Drawer.Content
          aria-describedby={undefined}
          className="fixed inset-y-0 left-0 z-50 flex w-[min(86vw,20rem)] flex-col border-r border-border bg-surface pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)] outline-none"
        >
          <Drawer.Title className="sr-only">{t("Menu")}</Drawer.Title>
          <div data-vaul-no-drag className="flex min-h-0 flex-1 flex-col">
            <Sidebar drawer onPick={() => setOpen(false)} />
          </div>
        </Drawer.Content>
      </Drawer.Portal>
    </Drawer.Root>
  );
}

let pushSynced = false;

/** The installed app's badge and this device's push subscription; the full-screen Library uses it too. */
export function useDeviceSync() {
  const { data } = useQuery(systemStatusQuery);
  const waiting = data?.counts.approvals_pending ?? 0;
  // The number on the installed app's icon follows the approvals waiting.
  useEffect(() => setBadge(waiting), [waiting]);
  // The browser may have rotated this device's push subscription: re-send it once per start.
  useEffect(() => {
    if (pushSynced) return;
    pushSynced = true;
    void syncPush();
  }, []);
}

export function AppShell() {
  const setOpen = usePalette((s) => s.setOpen);
  const { data: me } = useSuspenseQuery(meQuery);
  // The company switcher remembers each person's choice on this device.
  const bindUser = useBranch((s) => s.bindUser);
  useEffect(() => bindUser(me.user.id), [bindUser, me.user.id]);
  useLiveEvents();
  useDeviceSync();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setOpen]);

  return (
    <div className="flex min-h-dvh md:pr-[env(safe-area-inset-right)] md:pl-[env(safe-area-inset-left)]">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header />
        <main className="flex-1 pb-[calc(4.5rem+env(safe-area-inset-bottom))] md:pb-0">
          <Outlet />
        </main>
      </div>
      <MobileTabBar />
      <NavDrawer />
      <AiFab />
      <LazyCommandPalette />
      <LazyTaskComposerHost />
      <OfflineBanner />
      <NavProgress />
      <InstallApp />
    </div>
  );
}
