import { describe, expect, it } from "vitest";
import type { ShareLinkInfo } from "@/lib/api";
import {
  canGrant,
  findActiveLinkForEmail,
  validateExpiresDays,
} from "./share-dialog-helpers";

describe("canGrant", () => {
  // 2026-07-01 admin only 化: base は non-admin member 想定
  const base = {
    isSuperAdmin: false,
    ownerTeam: "konishi-lab",
    isOwnerTeamAdmin: false,
  };

  it("returns true for super admin", () => {
    expect(canGrant({ ...base, isSuperAdmin: true })).toBe(true);
  });

  it("returns true when current user is owner-team admin", () => {
    expect(canGrant({ ...base, isOwnerTeamAdmin: true })).toBe(true);
  });

  it("returns false when owner-team admin flag set but ownerTeam is null", () => {
    expect(
      canGrant({ ...base, ownerTeam: null, isOwnerTeamAdmin: true }),
    ).toBe(false);
  });

  it("returns false for a non-admin member (creator 本人でも grant 不可)", () => {
    expect(canGrant(base)).toBe(false);
  });
});

describe("validateExpiresDays", () => {
  it("accepts 0 as infinite", () => {
    expect(validateExpiresDays("0")).toEqual({ ok: true, days: 0 });
  });

  it("accepts 30", () => {
    expect(validateExpiresDays("30")).toEqual({ ok: true, days: 30 });
  });

  it("accepts 365 (upper bound)", () => {
    expect(validateExpiresDays("365")).toEqual({ ok: true, days: 365 });
  });

  it("trims whitespace before parsing", () => {
    expect(validateExpiresDays("  7  ")).toEqual({ ok: true, days: 7 });
  });

  it("rejects empty string (UX10 regression)", () => {
    const r = validateExpiresDays("");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toMatch(/有効期限を入力/);
  });

  it("rejects whitespace-only string", () => {
    expect(validateExpiresDays("   ").ok).toBe(false);
  });

  it("rejects negative numbers", () => {
    expect(validateExpiresDays("-1").ok).toBe(false);
  });

  it("rejects > 365", () => {
    expect(validateExpiresDays("400").ok).toBe(false);
  });

  it("rejects non-integer", () => {
    expect(validateExpiresDays("7.5").ok).toBe(false);
  });

  it("rejects non-numeric", () => {
    expect(validateExpiresDays("abc").ok).toBe(false);
  });
});

function makeLink(
  overrides: Partial<ShareLinkInfo> & { pseudo_email: string },
): ShareLinkInfo {
  return {
    token_hash_prefix: "abc1234567890def",
    record_id: "AB3F7K",
    team: "konishi-lab",
    role: "viewer",
    pseudo_display_name: "Alice",
    created_by: "owner@example.com",
    created_at: "2026-06-01T00:00:00Z",
    expires_at: "2026-07-01T00:00:00Z",
    revoked_at: null,
    last_used_at: null,
    label: "",
    is_active: true,
    ...overrides,
  };
}

describe("findActiveLinkForEmail", () => {
  it("returns the matching active link (case-insensitive)", () => {
    const links = [
      makeLink({ pseudo_email: "alice@example.com" }),
      makeLink({ pseudo_email: "bob@example.com" }),
    ];
    const found = findActiveLinkForEmail(links, "Alice@Example.COM");
    expect(found?.pseudo_email).toBe("alice@example.com");
  });

  it("ignores revoked / inactive links", () => {
    const links = [
      makeLink({ pseudo_email: "alice@example.com", is_active: false }),
      makeLink({ pseudo_email: "alice@example.com", is_active: true }),
    ];
    const found = findActiveLinkForEmail(links, "alice@example.com");
    expect(found?.is_active).toBe(true);
  });

  it("returns undefined when no match", () => {
    const links = [makeLink({ pseudo_email: "bob@example.com" })];
    expect(findActiveLinkForEmail(links, "alice@example.com")).toBeUndefined();
  });

  it("returns undefined for empty/blank query (no false positives)", () => {
    const links = [makeLink({ pseudo_email: "alice@example.com" })];
    expect(findActiveLinkForEmail(links, "")).toBeUndefined();
    expect(findActiveLinkForEmail(links, "   ")).toBeUndefined();
  });
});
