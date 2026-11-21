import { describe, expect, it } from "vitest";

import { ALL_NAV, NAV } from "@/nav";

import { canAssist, staffOnly } from "./my-ai";

const OWNER = ["agents.own", "agents.manage", "assistants.use", "office.view", "work.write"];

describe("one owner, one menu", () => {
  it("lists My assistants and no twin or worker pages", () => {
    const seen = NAV.flatMap((s) => s.items).map((i) => i.to as string);
    expect(seen).toContain("/assistants");
    expect(seen).not.toContain("/my-worker");
    expect(seen).not.toContain("/twin");
    expect(ALL_NAV.find((n) => n.to === "/assistants")!.label).toBe("My assistants");
  });

  it("gives the owner assistants and never the staff view", () => {
    expect(canAssist(OWNER)).toBe(true);
    expect(staffOnly(OWNER)).toBe(false);
  });
});
