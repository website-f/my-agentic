import { describe, expect, it } from "vitest";

import { attachmentUrl, frameDoc, listPath, prefixed, splitAddresses } from "./inbox";
import { byDay, numberOf, type WaMessage } from "./wa";

describe("the inbox's helpers", () => {
  it("reads typed address lists, with or without names", () => {
    expect(splitAddresses("hana@x.com, Ali Abu <ali@y.com>; not-an-address\nsiti@z.my")).toEqual(["hana@x.com", "ali@y.com", "siti@z.my"]);
    expect(splitAddresses("")).toEqual([]);
  });

  it("starts a reply or forward subject once", () => {
    expect(prefixed("Re", "Invoice")).toBe("Re: Invoice");
    expect(prefixed("Re", "RE: Invoice")).toBe("RE: Invoice");
    expect(prefixed("Fwd", "Re: Invoice")).toBe("Fwd: Re: Invoice");
  });

  it("asks for one page with only the filters in use, and encodes ids", () => {
    expect(listPath({ account: "all", folder: "inbox", q: " ", unread: false })).toBe("/api/inbox/messages?account=all&folder=inbox&top=25");
    expect(listPath({ account: "g:1", folder: "sentitems", q: "march", unread: true }, "abc")).toBe(
      "/api/inbox/messages?account=g%3A1&folder=sentitems&top=25&q=march&unread=true&cursor=abc",
    );
    expect(attachmentUrl("ms:1", "AAM/k=", "a b")).toBe("/api/inbox/messages/AAM%2Fk%3D/attachments/a%20b?account=ms%3A1");
  });

  it("puts plain-text mail in a page of its own, escaped, with links opening outside", () => {
    const doc = frameDoc("", "<b>hi</b>");
    expect(doc).toContain("&lt;b&gt;hi&lt;/b&gt;");
    expect(doc).toContain('<base target="_blank">');
    expect(doc).not.toContain("<script");
  });
});

describe("WhatsApp helpers", () => {
  const msg = (id: string, at: string): WaMessage => ({ id, from_me: false, sender: "601@c.us", sender_name: null, text: id, at, ack: null, media: null, reply_to: null, ai: false });

  it("groups messages by day, oldest first", () => {
    const groups = byDay([msg("a", "2026-11-20T09:00:00"), msg("b", "2026-11-20T18:00:00"), msg("c", "2026-11-21T08:00:00")]);
    expect(groups.map((g) => g.items.map((m) => m.id))).toEqual([["a", "b"], ["c"]]);
  });

  it("reads the number out of a chat id", () => {
    expect(numberOf("60123456789@c.us")).toBe("60123456789");
  });
});
