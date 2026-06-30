import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  authFetch,
  fetchShareLinkScope,
  fetchSharedWithMe,
  grantShare,
  issueShareLink,
  revokeShare,
  revokeShareLink,
  setTeamProvider,
  setTokenProvider,
  shareTokenFetch,
} from "./api";

// S1 TEST15 (2026-06-30): authFetch / shareTokenFetch / 各 share-link
// wrapper の headers / method / body / エラー時 throw を mock fetch で
// 検証。NEXT_PUBLIC_API_URL 未設定なら base="http://localhost:8000"。

const API = "http://localhost:8000";

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

function lastCall(): [string, RequestInit] {
  const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
  const last = calls[calls.length - 1] as [string, RequestInit];
  return last;
}

function headerVal(init: RequestInit, key: string): string | null {
  return new Headers(init.headers).get(key);
}

beforeEach(() => {
  globalThis.fetch = vi.fn() as unknown as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
  setTokenProvider(async () => null);
  setTeamProvider(() => null);
});

describe("authFetch", () => {
  it("attaches Authorization and X-Labvault-Team when both providers set", async () => {
    setTokenProvider(async () => "TOKEN123");
    setTeamProvider(() => "konishi-lab");
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({ ok: true }),
    );

    await authFetch("https://api.example/path");
    const [url, init] = lastCall();
    expect(url).toBe("https://api.example/path");
    expect(headerVal(init, "Authorization")).toBe("Bearer TOKEN123");
    expect(headerVal(init, "X-Labvault-Team")).toBe("konishi-lab");
  });

  it("omits Authorization when token provider returns null", async () => {
    setTokenProvider(async () => null);
    setTeamProvider(() => "konishi-lab");
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({}),
    );

    await authFetch("https://api.example/path");
    const [, init] = lastCall();
    expect(headerVal(init, "Authorization")).toBeNull();
    expect(headerVal(init, "X-Labvault-Team")).toBe("konishi-lab");
  });

  it("preserves caller-provided init.method and merges headers", async () => {
    setTokenProvider(async () => "T");
    setTeamProvider(() => null);
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({}),
    );

    await authFetch("https://x.example", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Custom": "1" },
      body: "{}",
    });
    const [, init] = lastCall();
    expect(init.method).toBe("POST");
    expect(headerVal(init, "Authorization")).toBe("Bearer T");
    expect(headerVal(init, "Content-Type")).toBe("application/json");
    expect(headerVal(init, "X-Custom")).toBe("1");
  });
});

describe("shareTokenFetch", () => {
  it("uses raw fetch and sets Authorization to the given token", async () => {
    // 重要: authFetch 経由ではないので setTokenProvider の影響を受けない。
    setTokenProvider(async () => "FIREBASE_TOKEN");
    setTeamProvider(() => "konishi-lab");
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({}),
    );

    await shareTokenFetch("ls_abc123", "https://x.example/r");
    const [, init] = lastCall();
    expect(headerVal(init, "Authorization")).toBe("Bearer ls_abc123");
    // X-Labvault-Team は付かない (share-link は team を含意するため backend が無視)
    expect(headerVal(init, "X-Labvault-Team")).toBeNull();
  });
});

describe("fetchShareLinkScope", () => {
  it("returns parsed scope on 200", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({
        record_id: "AB3F7K",
        team: "konishi-lab",
        role: "viewer",
        pseudo_email: "guest@external",
        pseudo_display_name: "Guest",
        expires_at: null,
        revoked_at: null,
      }),
    );

    const scope = await fetchShareLinkScope("ls_token");
    expect(scope.record_id).toBe("AB3F7K");
    const [url, init] = lastCall();
    expect(url).toBe(`${API}/api/share-links/me`);
    expect(headerVal(init, "Authorization")).toBe("Bearer ls_token");
  });

  it("throws on 401", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response("Unauthorized", { status: 401 }),
    );
    await expect(fetchShareLinkScope("bad")).rejects.toThrow(
      /Failed to verify share-link: 401/,
    );
  });
});

describe("grantShare / revokeShare", () => {
  beforeEach(() => {
    setTokenProvider(async () => "T");
    setTeamProvider(() => "konishi-lab");
  });

  it("POSTs JSON {email, role} to /shares", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({ shares: { "a@x": "viewer" } }),
    );
    await grantShare("AB3F7K", "a@x", "viewer");
    const [url, init] = lastCall();
    expect(url).toBe(`${API}/api/records/AB3F7K/shares`);
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ email: "a@x", role: "viewer" }));
    expect(headerVal(init, "Content-Type")).toBe("application/json");
  });

  it("throws including status text on grant failure", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response("self-share not allowed", { status: 400 }),
    );
    await expect(grantShare("AB3F7K", "a@x", "viewer")).rejects.toThrow(
      /Grant share failed: 400 self-share not allowed/,
    );
  });

  it("DELETEs /shares/{email} with URL-encoded email", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({ shares: {} }),
    );
    await revokeShare("AB3F7K", "alice+share@example.com");
    const [url, init] = lastCall();
    expect(init.method).toBe("DELETE");
    expect(url).toBe(
      `${API}/api/records/AB3F7K/shares/${encodeURIComponent("alice+share@example.com")}`,
    );
  });
});

describe("issueShareLink / revokeShareLink", () => {
  beforeEach(() => {
    setTokenProvider(async () => "T");
    setTeamProvider(() => "konishi-lab");
  });

  it("issues with full body", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({
        token: "ls_raw",
        token_hash_prefix: "abcd1234",
        record_id: "AB3F7K",
        team: "konishi-lab",
        role: "viewer",
        pseudo_email: "g@x",
        pseudo_display_name: "G",
        created_by: "owner@x",
        created_at: "2026-06-30T00:00:00Z",
        expires_at: null,
        revoked_at: null,
        last_used_at: null,
        label: "",
        is_active: true,
      }),
    );
    const created = await issueShareLink("AB3F7K", {
      role: "viewer",
      pseudo_email: "g@x",
      pseudo_display_name: "G",
      label: "intern",
      expires_days: 30,
    });
    expect(created.token).toBe("ls_raw");
    const [url, init] = lastCall();
    expect(url).toBe(`${API}/api/records/AB3F7K/share-links`);
    expect(init.method).toBe("POST");
    const sent = JSON.parse(String(init.body));
    expect(sent).toEqual({
      role: "viewer",
      pseudo_email: "g@x",
      pseudo_display_name: "G",
      label: "intern",
      expires_days: 30,
    });
  });

  it("revokes by encoded hash prefix", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(null, { status: 204 }),
    );
    await revokeShareLink("AB3F7K", "abcd/1234");
    const [url, init] = lastCall();
    expect(init.method).toBe("DELETE");
    expect(url).toBe(
      `${API}/api/records/AB3F7K/share-links/${encodeURIComponent("abcd/1234")}`,
    );
  });
});

describe("fetchSharedWithMe", () => {
  beforeEach(() => {
    setTokenProvider(async () => "T");
    setTeamProvider(() => "konishi-lab");
  });

  it("builds URL without query when no params", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({ items: [], total: 0 }),
    );
    await fetchSharedWithMe();
    const [url] = lastCall();
    expect(url).toBe(`${API}/api/records/shared-with-me`);
  });

  it("appends limit/offset query when given", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({ items: [], total: 0 }),
    );
    await fetchSharedWithMe({ limit: 50, offset: 100 });
    const [url] = lastCall();
    expect(url).toBe(`${API}/api/records/shared-with-me?limit=50&offset=100`);
  });
});
