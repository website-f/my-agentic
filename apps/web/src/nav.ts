import {
  BellRingingIcon,
  BlueprintIcon,
  BooksIcon,
  BrainIcon,
  BuildingsIcon,
  CalendarCheckIcon,
  CalendarDotsIcon,
  ChartLineUpIcon,
  ChatsCircleIcon,
  ClipboardTextIcon,
  ClockCounterClockwiseIcon,
  CpuIcon,
  DeskIcon,
  DesktopTowerIcon,
  EnvelopeSimpleIcon,
  EyeIcon,
  FileMagnifyingGlassIcon,
  FilesIcon,
  FileTextIcon,
  FlowArrowIcon,
  FolderOpenIcon,
  GaugeIcon,
  GearSixIcon,
  GlobeIcon,
  GraduationCapIcon,
  HardDrivesIcon,
  IdentificationCardIcon,
  KanbanIcon,
  LightningIcon,
  LockKeyIcon,
  MicrosoftOutlookLogoIcon,
  NotepadIcon,
  PackageIcon,
  PlugsConnectedIcon,
  PuzzlePieceIcon,
  SealCheckIcon,
  SparkleIcon,
  StackIcon,
  TargetIcon,
  UsersIcon,
  UsersThreeIcon,
  WhatsappLogoIcon,
  type Icon,
} from "@phosphor-icons/react";

import { msg } from "@/i18n";

export type AppPath =
  | "/"
  | "/workspace"
  | "/impact"
  | "/inbox"
  | "/whatsapp"
  | "/tasks"
  | "/approvals"
  | "/chat"
  | "/assistants"
  | "/computers"
  | "/mail"
  | "/files"
  | "/documents"
  | "/sops"
  | "/library"
  | "/templates"
  | "/packs"
  | "/company-kit"
  | "/search"
  | "/forms"
  | "/reports"
  | "/workflows"
  | "/objectives"
  | "/agents"
  | "/timetable"
  | "/monitor"
  | "/meetings"
  | "/learning"
  | "/skills"
  | "/brain"
  | "/blueprints"
  | "/office"
  | "/settings"
  | "/notifications"
  | "/channels"
  | "/ai-engine"
  | "/settings/storage"
  | "/logins"
  | "/web-connections"
  | "/schedules"
  | "/mcp-servers"
  | "/activity";

export interface NavItem {
  to: AppPath;
  label: string;
  icon: Icon;
  /** A small tag beside the name (e.g. NEW); absent = none. */
  phase?: string;
  blurb: string;
  /** Permission needed to see it in navigation (any of them, when a list). */
  perm?: string | string[];
  /** Other addresses that count as this entry (a page's second tab). */
  also?: AppPath[];
  /** Reached from another entry (a tab of it): known to page headers, not listed. */
  hidden?: boolean;
  /** A shorter name for the phone's bottom bar. */
  short?: string;
  /** A page few people need: listed only when "Show all pages" is on (still searchable and
   * reachable by its address). */
  advanced?: boolean;
}

export interface NavSection {
  title: string;
  /** One plain sentence: what this group is for. */
  hint: string;
  items: NavItem[];
  /** Open in the sidebar at first: for everyone, only for people who manage, or folded. */
  open: "all" | "managers" | "none";
}

// Titles, labels, hints and blurbs are English keys (msg); render them with t().
// One owner, four groups: Today (the desk and everything daily), Work (the Library, forms and
// reports, workflows), the AI team, and Settings folded away.
export const NAV: NavSection[] = [
  {
    title: msg("Today"),
    hint: msg("Your desk and what needs you today: mail, chat, tasks, approvals and your AI."),
    open: "all",
    items: [
      { to: "/workspace", label: msg("My workspace"), short: msg("My desk"), icon: DeskIcon, blurb: msg("Your own desk: ask or search anything, your pinned SOPs and workflows, your AI workers, the work you gave and every file it produced.") },
      { to: "/", label: msg("Command center"), icon: GaugeIcon, blurb: msg("Today at a glance: system health and what to do next.") },
      { to: "/impact", label: msg("Impact"), icon: ChartLineUpIcon, blurb: msg("What the AI team measurably did, the time it freed against what it cost, and what it can do next.") },
      { to: "/inbox", label: msg("Inbox"), icon: EnvelopeSimpleIcon, phase: msg("NEW"), blurb: msg("All your email accounts in one place: switch accounts, read, reply and let your AI draft.") },
      { to: "/whatsapp", label: msg("WhatsApp"), icon: WhatsappLogoIcon, phase: msg("NEW"), blurb: msg("Chat from your connected WhatsApp number and choose where your AI answers when mentioned.") },
      { to: "/tasks", label: msg("Tasks"), icon: KanbanIcon, blurb: msg("A board of everything your agents are working on, from triage to done. Drag a card between columns to move it along.") },
      { to: "/approvals", label: msg("Approvals"), icon: SealCheckIcon, blurb: msg("Decisions agents are waiting on. Approve once, always, or deny, from here or from a phone notification.") },
      { to: "/chat", label: msg("Chat"), icon: ChatsCircleIcon, blurb: msg("Talk to any agent directly, by typing or with your voice, and pick up past conversations.") },
      { to: "/assistants", label: msg("My assistants"), icon: SparkleIcon, blurb: msg("Your own private AI assistants: your Gmail with drafts you approve, and chasing people on WhatsApp.") },
      { to: "/computers", label: msg("My computers"), icon: DesktopTowerIcon, blurb: msg("Let your own AI find files on your computer and browse on your screen. Only your AI can use it, only in the folders you choose.") },
      { to: "/mail", label: msg("Calendar & Teams"), icon: MicrosoftOutlookLogoIcon, blurb: msg("Your Outlook mail, calendar and Teams chats from your Microsoft 365 connection: what reached you and what your AI did with each.") },
    ],
  },
  {
    title: msg("Work"),
    hint: msg("Files and documents, forms and reports, and the steps work follows."),
    open: "all",
    items: [
      { to: "/files", label: msg("Library"), icon: FolderOpenIcon, also: ["/documents", "/sops", "/library", "/templates", "/packs", "/company-kit", "/search"], blurb: msg("Every file, document, SOP and guideline in one place: browse your folders, or open Documents, SOPs, Guidelines, Templates, Packs, the Company kit and Search as tabs.") },
      // The Library's tabs: reached from its tab row, found by the command palette.
      { to: "/documents", label: msg("Documents"), icon: FilesIcon, hidden: true, blurb: msg("Documents drafted by you or agents, checked automatically, approved, and exported to PDF, Word or Excel.") },
      { to: "/sops", label: msg("SOPs"), icon: FileTextIcon, hidden: true, blurb: msg("Written procedures agents follow, for everything or attached to specific agents.") },
      { to: "/library", label: msg("Guidelines"), icon: BooksIcon, hidden: true, blurb: msg("Guidelines, manuals and policies you upload. Agents search them when the work needs it and cite the page.") },
      { to: "/templates", label: msg("Templates"), icon: StackIcon, hidden: true, blurb: msg("Quotations, invoices, letters, proposals and your own Word files, with {{placeholders}} agents and you fill.") },
      { to: "/packs", label: msg("Packs"), icon: PackageIcon, hidden: true, blurb: msg("Submission packs: a checklist matched to real files and documents, compiled into one PDF with a cover and contents.") },
      { to: "/company-kit", label: msg("Company kit"), icon: IdentificationCardIcon, hidden: true, blurb: msg("Your facts every document reuses: legal name, registration, address, bank, signatory, logo.") },
      { to: "/search", label: msg("Search inside files"), icon: FileMagnifyingGlassIcon, hidden: true, blurb: msg("Search inside every document: a phrase on page 23 of a handbook, an amount, a form or a job title. Opens the file at the page.") },
      { to: "/forms", label: msg("Forms"), icon: NotepadIcon, blurb: msg("Claims, monthly records and requests: download the blank, hand it in before the deadline, or let your AI fill it in.") },
      { to: "/reports", label: msg("Reports"), icon: ClipboardTextIcon, blurb: msg("What agents wrote up for you: summaries and tables you can sort and download.") },
      { to: "/workflows", label: msg("Workflows"), icon: FlowArrowIcon, blurb: msg("Draw how a job is done as connected steps, or let an analyst agent draft it. Attach it to agents as their procedure, or run a job through it: each step goes to its agent, and you take the decisions.") },
      { to: "/objectives", label: msg("Objectives"), icon: TargetIcon, blurb: msg("What your work is for: progress, due dates and what each goal cost, including everything its tasks handed out. Agents see why linked work matters.") },
    ],
  },
  {
    title: msg("AI team"),
    hint: msg("Your AI agents: who they are, their working day, and what they learned."),
    open: "all",
    items: [
      { to: "/agents", label: msg("Agents"), icon: UsersThreeIcon, blurb: msg("Create agents by hand, give them skills and SOPs, and see who reports to whom.") },
      { to: "/timetable", label: msg("Timetable"), icon: CalendarDotsIcon, blurb: msg("Each agent's working day, like a rota: its hours, its daily duties, and what waits for its next shift.") },
      { to: "/monitor", label: msg("Monitor"), icon: EyeIcon, blurb: msg("Watch any agent work live: its thinking, every tool it uses, questions to colleagues, and its browser screen.") },
      { to: "/meetings", label: msg("Meetings"), icon: UsersIcon, blurb: msg("Watch agents discuss a decision with each other, interject, and read the outcome they agree on.") },
      { to: "/learning", label: msg("Learning"), icon: GraduationCapIcon, blurb: msg("What your agents learned, how each change was tested, what went live by itself, and what learning cost.") },
      { to: "/skills", label: msg("Skills"), icon: LightningIcon, blurb: msg("Procedures agents have learned. Review what they propose before it becomes part of how they work.") },
      { to: "/brain", label: msg("Brain"), icon: BrainIcon, blurb: msg("What your office knows: facts agents learned, wiki pages, and a nightly tidy-up that keeps them correct.") },
      { to: "/blueprints", label: msg("Blueprints"), icon: BlueprintIcon, blurb: msg("Reusable role packages (instructions, model, tool scope, SOPs and skills) you apply to agents so they start as specialists.") },
      { to: "/office", label: msg("Office floor"), icon: BuildingsIcon, blurb: msg("A live pixel-art office. Every agent sits at a desk and walks to the podium when it needs you.") },
    ],
  },
  {
    title: msg("Settings"),
    hint: msg("Set up once: notifications, AI, connections and storage."),
    open: "none",
    items: [
      { to: "/settings", label: msg("Settings"), icon: GearSixIcon, blurb: msg("Appearance, two-step sign-in and your account.") },
      { to: "/notifications", label: msg("My notifications"), icon: BellRingingIcon, blurb: msg("How the office tells you (email, this app, Telegram, WhatsApp) when your AI needs you or finishes.") },
      { to: "/channels", label: msg("Channels"), icon: PlugsConnectedIcon, blurb: msg("Phone notifications, Telegram, API tokens, and which agent answers where.") },
      { to: "/ai-engine", label: msg("AI Engine"), icon: CpuIcon, blurb: msg("Add provider keys, test the connection, choose models and see what every agent spends.") },
      { to: "/settings/storage", label: msg("File storage"), icon: HardDrivesIcon, blurb: msg("Where your files are kept: the database, this server's disk, a Backblaze B2 or S3 bucket, or your own file server, and what feeds the Library.") },
      { to: "/logins", label: msg("Logins"), icon: LockKeyIcon, blurb: msg("Website logins agents may use without ever seeing them, each locked to its own sites.") },
      { to: "/web-connections", label: msg("Web connections"), icon: GlobeIcon, blurb: msg("How the AI's browsers reach websites: this server, your computer, or your own proxies.") },
      { to: "/schedules", label: msg("Schedules"), icon: CalendarCheckIcon, blurb: msg("Recurring work and every run's result, with retries and grouped incidents.") },
      { to: "/mcp-servers", label: msg("MCP tools"), icon: PuzzlePieceIcon, blurb: msg("Connect tools from other systems (MCP): a tracker, a CRM, or your own server. Agents ask before every call.") },
      { to: "/activity", label: msg("Activity"), icon: ClockCounterClockwiseIcon, blurb: msg("Every change made by you and agents, in a tamper-evident log.") },
    ],
  },
];

export const ALL_NAV: NavItem[] = NAV.flatMap((s) => s.items);

/** Pages that belong together share one sidebar entry and show as tabs on each other's page
 * (components/hub-tabs.tsx), so the menu stays short. Each page keeps its own address. The
 * sidebar shows the first tab, under the hub's name; a `listed` hub keeps every page in the
 * sidebar and only adds the tab row on its pages. (The Library is its own hub: pages/library-hub.) */
export interface Hub {
  label: string;
  tabs: AppPath[];
  listed?: boolean;
}

export const HUBS: Hub[] = [
  { label: msg("Command center"), tabs: ["/", "/impact"] },
  { label: msg("My assistants"), tabs: ["/assistants", "/computers"] },
  { label: msg("Forms & reports"), tabs: ["/forms", "/reports"] },
  { label: msg("Workflows & goals"), tabs: ["/workflows", "/objectives"] },
  { label: msg("Agents"), tabs: ["/agents", "/timetable", "/monitor", "/meetings"] },
  { label: msg("Knowledge & skills"), tabs: ["/learning", "/skills", "/brain", "/blueprints"] },
  { label: msg("Settings"), listed: true, tabs: ["/settings", "/notifications", "/channels", "/ai-engine", "/settings/storage", "/logins", "/web-connections", "/schedules", "/mcp-servers", "/activity"] },
];

/** The hub a nav entry is a tab of, if any. */
export function hubOf(to: string): Hub | undefined {
  return HUBS.find((h) => h.tabs.includes(to as AppPath));
}

const navAllowed = (i: NavItem, perms: string[]) => !i.perm || [i.perm].flat().some((p) => perms.includes(p));

/** The hub's tabs this person may open, in order. */
export function hubTabs(hub: Hub, perms: string[]): NavItem[] {
  return hub.tabs.map((to) => ALL_NAV.find((n) => n.to === to)).filter((i): i is NavItem => !!i && navAllowed(i, perms));
}

/** A section's items as the sidebar lists them: each hub once (its first tab the person may
 * open, named after the hub, active on any of its tabs), other items as they are. */
export function sidebarItems(items: NavItem[], perms: string[]): NavItem[] {
  const out: NavItem[] = [];
  for (const i of items) {
    const hub = hubOf(i.to);
    if (!hub || hub.listed) {
      out.push(i);
      continue;
    }
    const first = hubTabs(hub, perms)[0];
    if (!first || first.to !== i.to) continue;
    out.push({ ...i, label: hub.label, hidden: false, advanced: false, also: [...(i.also ?? []), ...hub.tabs.filter((t) => t !== i.to)] });
  }
  return out;
}

/** Phone bottom bar: the four things you reach for one-handed, plus More. */
export const TAB_BAR: AppPath[] = ["/workspace", "/inbox", "/tasks", "/chat"];

/** The phone bottom bar (one owner: always the same four). */
export function tabBarFor(): AppPath[] {
  return TAB_BAR;
}

/** The More sheet's entries: everything not already a tab. */
export function moreItems(items: NavItem[], tabs: AppPath[]): NavItem[] {
  return items.filter((i) => !tabs.includes(i.to));
}

/** The navigation entry a path belongs to (its own page, a tab of it, or a page under it). */
export function navItemFor(pathname: string): NavItem | undefined {
  const hit = (to: string) => (to === "/" ? pathname === "/" : pathname === to || pathname.startsWith(`${to}/`));
  // The longest match wins; at the same length a page's own entry beats a tab of another.
  let best: NavItem | undefined;
  let bestScore = -1;
  for (const item of ALL_NAV) {
    for (const to of [item.to, ...(item.also ?? [])]) {
      const score = to.length * 2 + (to === item.to ? 1 : 0);
      if (hit(to) && score > bestScore) {
        best = item;
        bestScore = score;
      }
    }
  }
  return best;
}

/** May someone with these permissions open this path? The same rule as the sidebar, so a
 * page that is not in someone's navigation cannot be reached by typing its address either. */
export function pathAllowed(pathname: string, permissions: string[]): boolean {
  const item = navItemFor(pathname);
  return !item?.perm || [item.perm].flat().some((p) => permissions.includes(p));
}
