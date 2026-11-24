import { describe, expect, it } from "vitest";

import { answersFor, cleanNumber, dayOf, endOfDayIso, isExpired, prettyNumber, shortCount, usedPct } from "./wa";

describe("people with access helpers", () => {
  it("keeps numbers as the server does, a local 0 read as Malaysian", () => {
    expect(cleanNumber("+60 12-345 6789")).toBe("60123456789");
    expect(cleanNumber("012-345 6789")).toBe("60123456789");
    expect(cleanNumber("0065 9123 4567")).toBe("006591234567");
    expect(prettyNumber("60123456789")).toBe("+60 12-345 6789");
    expect(prettyNumber("6591234567")).toBe("+6591234567");
  });

  it("shortens token counts", () => {
    expect(shortCount(0)).toBe("0");
    expect(shortCount(950)).toBe("950");
    expect(shortCount(1500)).toBe("1.5k");
    expect(shortCount(45_200)).toBe("45k");
    expect(shortCount(200_000)).toBe("200k");
    expect(shortCount(2_000_000)).toBe("2M");
  });

  it("shows how full today's allowance is, never past 100, 0 without a limit", () => {
    expect(usedPct(12, 30)).toBe(40);
    expect(usedPct(45, 30)).toBe(100);
    expect(usedPct(500, 0)).toBe(0);
  });

  it("guesses normal answers for a token allowance", () => {
    expect(answersFor(200_000)).toBe("20-40");
    expect(answersFor(1000)).toBe("1");
  });

  it("reads end dates", () => {
    const now = new Date("2026-11-25T10:00:00").getTime();
    expect(isExpired({ expires_at: null }, now)).toBe(false);
    expect(isExpired({ expires_at: new Date("2026-11-24T23:59:59").toISOString() }, now)).toBe(true);
    expect(isExpired({ expires_at: endOfDayIso("2026-11-25") }, now)).toBe(false);
    expect(dayOf(endOfDayIso("2026-12-31"))).toBe("2026-12-31");
    expect(dayOf(null)).toBe("");
  });
});
