import { describe, expect, it } from "vitest";

import { ALL_NAV, hubOf, NAV, navItemFor, pathAllowed, sidebarItems, tabBarFor } from "./nav";

const OWNER = ["read", "office.view", "work.write", "approvals.decide", "agents.manage", "engine.manage", "engine.view", "assistants.use"];

describe("one owner, one compact menu", () => {
  it("has four groups and settings folded away", () => {
    expect(NAV.map((s) => s.title)).toEqual(["Today", "Work", "AI team", "Settings"]);
    expect(NAV.find((s) => s.title === "Settings")!.open).toBe("none");
  });

  it("lists Inbox and WhatsApp under Today, marked new", () => {
    const today = NAV[0]!.items.map((i) => i.to);
    expect(today).toContain("/inbox");
    expect(today).toContain("/whatsapp");
    expect(ALL_NAV.find((i) => i.to === "/inbox")!.phase).toBe("NEW");
  });

  it("has no organization, people, Prima, guide or feedback pages", () => {
    const paths = ALL_NAV.map((i) => i.to as string);
    for (const gone of ["/organization", "/settings/members", "/settings/roles", "/settings/ai-use", "/my-worker", "/twin", "/prima", "/guide", "/tutorial", "/feedbacks", "/handoffs", "/broadcasts", "/overview"]) {
      expect(paths, gone).not.toContain(gone);
    }
  });

  it("lets the owner open every page", () => {
    for (const path of ["/", "/workspace", "/inbox", "/whatsapp", "/agents/ag_1", "/brain", "/ai-engine", "/settings/storage", "/mcp-servers"]) {
      expect(pathAllowed(path, OWNER), path).toBe(true);
    }
  });

  it("matches a page to its own entry, not a shorter one", () => {
    expect(navItemFor("/settings/storage")?.to).toBe("/settings/storage");
    expect(navItemFor("/settings")?.to).toBe("/settings");
    expect(navItemFor("/sops")?.to).toBe("/sops");
    expect(navItemFor("/")?.to).toBe("/");
  });

  it("shows a hub once in the sidebar but keeps the Settings pages listed", () => {
    const today = sidebarItems(NAV[0]!.items, OWNER).map((i) => i.to);
    expect(today).toContain("/");
    expect(today).not.toContain("/impact"); // a tab of Command center
    expect(today).not.toContain("/computers"); // a tab of My assistants
    const settings = sidebarItems(NAV[3]!.items, OWNER).map((i) => i.to);
    expect(settings).toContain("/channels");
    expect(settings).toContain("/activity");
    expect(hubOf("/channels")?.label).toBe("Settings");
  });

  it("P102: has no Customers and money pages", () => {
    for (const path of ["/crm", "/contacts", "/contacts/pt_1", "/deals", "/money", "/settings/approval-limits"]) {
      expect(navItemFor(path)?.to ?? "", path).not.toMatch(/^\/(crm|contacts|deals|money|settings\/approval-limits)/);
    }
  });

  it("gives the phone four tabs that are all in the menu", () => {
    for (const to of tabBarFor()) expect(ALL_NAV.some((i) => i.to === to), to).toBe(true);
  });
});
