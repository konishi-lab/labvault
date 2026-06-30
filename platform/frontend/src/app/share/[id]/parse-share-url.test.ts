import { describe, expect, it } from "vitest";
import { buildShareUrl, parseShareUrl } from "./parse-share-url";

describe("parseShareUrl", () => {
  describe("kind=new (token in fragment)", () => {
    it("treats path as record_id and hash as token", () => {
      const r = parseShareUrl({ pathId: "AB3F7K", hash: "ls_abc123" });
      expect(r).toEqual({ kind: "new", recordId: "AB3F7K", token: "ls_abc123" });
    });

    it("works when path also looks like a token (fragment wins)", () => {
      // 理論的には起き得ない (record_id は Crockford Base32) が、
      // hash が ls_ で始まれば常に new 形式として扱うのが安全側。
      const r = parseShareUrl({ pathId: "ls_old", hash: "ls_new" });
      expect(r).toEqual({ kind: "new", recordId: "ls_old", token: "ls_new" });
    });
  });

  describe("kind=migrate (legacy /share/<token>)", () => {
    it("treats path as token when no hash", () => {
      const r = parseShareUrl({ pathId: "ls_legacy", hash: "" });
      expect(r).toEqual({ kind: "migrate", token: "ls_legacy" });
    });

    it("ignores hash whitespace", () => {
      const r = parseShareUrl({ pathId: "ls_legacy", hash: "   " });
      expect(r).toEqual({ kind: "migrate", token: "ls_legacy" });
    });
  });

  describe("kind=invalid", () => {
    it("rejects empty path", () => {
      const r = parseShareUrl({ pathId: "", hash: "ls_foo" });
      expect(r.kind).toBe("invalid");
    });

    it("rejects hash that isn't ls_ prefixed", () => {
      const r = parseShareUrl({ pathId: "AB3F7K", hash: "not-a-token" });
      expect(r.kind).toBe("invalid");
      if (r.kind === "invalid") {
        expect(r.reason).toMatch(/token \(# 以降\) の形式が不正/);
      }
    });

    it("rejects record-id-only path (no hash, not a token)", () => {
      const r = parseShareUrl({ pathId: "AB3F7K", hash: "" });
      expect(r.kind).toBe("invalid");
      if (r.kind === "invalid") {
        expect(r.reason).toMatch(/token が含まれていません/);
      }
    });
  });
});

describe("buildShareUrl", () => {
  it("composes origin + path + fragment", () => {
    expect(
      buildShareUrl({
        origin: "https://labvault.example",
        recordId: "AB3F7K",
        token: "ls_secret",
      }),
    ).toBe("https://labvault.example/share/AB3F7K#ls_secret");
  });

  it("does not URL-encode token in the fragment (ls_<hex> is safe ASCII)", () => {
    // ls_ + url-safe base64 → '-' '_' は安全 (RFC 3986 unreserved)
    expect(
      buildShareUrl({
        origin: "http://localhost:3000",
        recordId: "QQ1234",
        token: "ls_aB-cD_Ef",
      }),
    ).toBe("http://localhost:3000/share/QQ1234#ls_aB-cD_Ef");
  });

  it("roundtrips through parseShareUrl (new form)", () => {
    // buildShareUrl が吐く URL は parseShareUrl が ``new`` として解釈する。
    const url = buildShareUrl({
      origin: "https://x.example",
      recordId: "AB3F7K",
      token: "ls_secret",
    });
    const u = new URL(url);
    const parsed = parseShareUrl({
      pathId: u.pathname.replace(/^\/share\//, ""),
      hash: u.hash.replace(/^#/, ""),
    });
    expect(parsed).toEqual({
      kind: "new",
      recordId: "AB3F7K",
      token: "ls_secret",
    });
  });
});
