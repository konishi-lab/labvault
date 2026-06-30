"use client";

// CQ7 (2026-06-30): share-dialog.tsx 829 行のうち 外部 token (ls_*) 管理
// 部分 (約 420 行) を分離。
//
// 親 ShareDialog から:
//   - recordId (どの record の token を発行 / 一覧するか)
//   - justIssued / setJustIssued (発行直後の raw token を持ち上げ — UX2
//     hot-fix で modal close 抑止のため親 state に保持)
//
// Phase 2B + D1 設計:
//   - issueShareLink → 1 回限り表示の raw token + 永続化される hash
//   - 共有 URL は /share/<record_id>#<token> (token は fragment)
//
// 本 component が触る backend:
//   - GET  /api/records/{id}/share-links → 一覧
//   - POST /api/records/{id}/share-links → 発行
//   - DELETE /api/records/{id}/share-links/{prefix} → 失効

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  fetchShareLinks,
  issueShareLink,
  revokeShareLink,
  type CreatedShareLink,
  type ShareLinkInfo,
  type ShareRole,
} from "@/lib/api";
import { ROLE_LABELS } from "@/lib/format";
import {
  findActiveLinkForEmail,
  validateExpiresDays,
} from "./share-dialog-helpers";
import { buildShareUrl } from "@/app/share/[id]/parse-share-url";

export function ShareLinksPanel({
  recordId,
  justIssued,
  setJustIssued,
}: {
  recordId: string;
  // S1-UX2: 親 ShareDialog 側で持つ state を passthrough。raw token 表示中
  // は親が close を抑止する。
  justIssued: CreatedShareLink | null;
  setJustIssued: (v: CreatedShareLink | null) => void;
}) {
  const [links, setLinks] = useState<ShareLinkInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [role, setRole] = useState<ShareRole>("viewer");
  const [pseudoEmail, setPseudoEmail] = useState("");
  const [pseudoName, setPseudoName] = useState("");
  const [label, setLabel] = useState("");
  const [expiresDays, setExpiresDays] = useState<string>("30");
  const [copied, setCopied] = useState(false);

  // 一覧 fetch
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchShareLinks(recordId)
      .then((items) => {
        if (cancelled) return;
        setLinks(items);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [recordId]);

  const handleIssue = async (e: React.FormEvent) => {
    e.preventDefault();
    const email = pseudoEmail.trim().toLowerCase();
    if (!email || !email.includes("@")) {
      setError("有効な pseudo email を入力してください (audit 用 identity)");
      return;
    }
    // S1-UX10 hot-fix (2026-06-29): 空欄を弾く / 範囲チェック。
    // S1 TEST15 (2026-06-30): pure logic は share-dialog-helpers 側に集約。
    const validated = validateExpiresDays(expiresDays);
    if (!validated.ok) {
      setError(validated.error);
      return;
    }
    const days = validated.days;
    // S1-UX4 hot-fix (2026-06-29): 同じ pseudo_email で active token が
    // 既に存在する → 確認ダイアログ。何度も発行すると相手側に複数 token
    // (古い方も active のまま) が残り、片方 revoke しても別経路が残る
    // 運用事故を防ぐ。
    const existing = findActiveLinkForEmail(links, email);
    if (existing) {
      const ok = confirm(
        `${email} には既に active な token が存在します ` +
          `(発行日: ${new Date(existing.created_at).toLocaleDateString("ja-JP")})。\n\n` +
          "OK = 古い方を revoke してから新しい token を発行する\n" +
          "キャンセル = 何もしない (相手側に古い token が残る運用上推奨)",
      );
      if (!ok) {
        return;
      }
      // 旧 token を revoke してから新 token 発行
      setSubmitting(true);
      setError(null);
      try {
        await revokeShareLink(recordId, existing.token_hash_prefix);
      } catch (err) {
        setError(`旧 token の revoke に失敗: ${(err as Error).message}`);
        setSubmitting(false);
        return;
      }
    }
    setSubmitting(true);
    setError(null);
    try {
      const issued = await issueShareLink(recordId, {
        role,
        pseudo_email: email,
        pseudo_display_name: pseudoName.trim() || undefined,
        label: label.trim() || undefined,
        expires_days: days,
      });
      setJustIssued(issued);
      setCopied(false);
      // 一覧を再 fetch (発行された token が is_active で出る)
      const next = await fetchShareLinks(recordId);
      setLinks(next);
      // フォーム reset
      setPseudoEmail("");
      setPseudoName("");
      setLabel("");
      setShowForm(false);
    } catch (err) {
      const msg = (err as Error).message;
      if (msg.includes("403")) {
        setError("token を発行する権限がありません");
      } else if (msg.includes("400")) {
        setError("入力内容が無効です (role / email / expires_days)");
      } else {
        setError(msg);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleRevoke = async (prefix: string) => {
    if (!confirm("この token を失効しますか？(取り消し不可)")) return;
    setSubmitting(true);
    setError(null);
    try {
      await revokeShareLink(recordId, prefix);
      const next = await fetchShareLinks(recordId);
      setLinks(next);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleCopy = async () => {
    if (!justIssued) return;
    try {
      await navigator.clipboard.writeText(justIssued.token);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // 古いブラウザ fallback
      const ta = document.createElement("textarea");
      ta.value = justIssued.token;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleCopyUrl = async () => {
    if (!justIssued) return;
    // S1 Phase D1 (2026-06-30): token を URL fragment (#) に配置することで
    // Cloud Run platform request log と Referer header への漏洩を絶つ。
    // share-link page は path id を record_id、fragment を token として
    // 解釈する。旧形式 ``/share/<token>`` も client-side で新形式に
    // redirect する後方互換あり。
    const url = buildShareUrl({
      origin: window.location.origin,
      recordId,
      token: justIssued.token,
    });
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore
    }
  };

  const activeLinks = links.filter((l) => l.is_active);
  const inactiveLinks = links.filter((l) => !l.is_active);

  return (
    <div className="space-y-2 border-t pt-3">
      <div className="flex items-center justify-between">
        <div className="text-xs font-medium text-muted-foreground">
          外部 token ({activeLinks.length}
          {inactiveLinks.length > 0 ? ` / ${links.length}` : ""})
        </div>
        {!showForm && !justIssued && (
          <Button
            type="button"
            size="xs"
            variant="outline"
            onClick={() => setShowForm(true)}
          >
            + 新規発行
          </Button>
        )}
      </div>

      {/* 発行直後の raw token 表示 (1 回限り、再表示不可) */}
      {justIssued && (
        <div className="rounded-md border border-amber-300 bg-amber-50 p-3 space-y-2 text-xs">
          <div className="font-semibold text-amber-900">
            ✨ 新しい token を発行しました ({justIssued.pseudo_email}、
            {ROLE_LABELS[justIssued.role as ShareRole] ?? justIssued.role})
          </div>
          <p className="text-amber-800">
            <strong>raw token は二度と表示できません。</strong>{" "}
            今すぐコピーして相手に送ってください。
            <br />
            <span className="text-amber-700">
              (誤閉じ防止のため、コピー後に下の「コピーした、閉じる」を
              押すまで modal は閉じません)
            </span>
          </p>
          <div className="bg-white border rounded p-2 font-mono text-[11px] break-all">
            {justIssued.token}
          </div>
          <div className="flex gap-1.5 flex-wrap">
            <Button
              type="button"
              size="xs"
              variant="outline"
              onClick={handleCopy}
            >
              {copied ? "✓ コピー" : "token をコピー"}
            </Button>
            <Button
              type="button"
              size="xs"
              variant="outline"
              onClick={handleCopyUrl}
            >
              {copied ? "✓ コピー" : "共有 URL をコピー"}
            </Button>
            <Button
              type="button"
              size="xs"
              variant="ghost"
              onClick={() => {
                setJustIssued(null);
                setCopied(false);
              }}
            >
              コピーした、閉じる
            </Button>
          </div>
        </div>
      )}

      {/* 新規発行フォーム */}
      {showForm && !justIssued && (
        <form
          onSubmit={handleIssue}
          className="space-y-2 rounded-md border border-dashed p-2.5"
        >
          <div className="grid grid-cols-2 gap-2">
            <Input
              type="email"
              value={pseudoEmail}
              onChange={(e) => setPseudoEmail(e.target.value)}
              placeholder="pseudo email (例: ext+jane@klab.share)"
              required
              disabled={submitting}
              className="h-8 text-xs col-span-2"
              title="audit 用 identity。token で投稿された記録の created_by に刻まれる"
            />
            <Input
              type="text"
              value={pseudoName}
              onChange={(e) => setPseudoName(e.target.value)}
              placeholder="表示名 (例: Jane (NIMS))"
              disabled={submitting}
              className="h-8 text-xs"
            />
            <Input
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="label (整理用 メモ)"
              disabled={submitting}
              className="h-8 text-xs"
            />
            <div
              className="inline-flex items-center rounded-md border border-input p-0.5 bg-background text-xs col-span-1"
              role="radiogroup"
              aria-label="権限"
            >
              {(["viewer", "analyst"] as ShareRole[]).map((r) => {
                const active = role === r;
                return (
                  <button
                    key={r}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    disabled={submitting}
                    onClick={() => setRole(r)}
                    title={r === "viewer" ? "閲覧 + DL のみ" : "解析投稿可能"}
                    className={
                      "px-2 py-0.5 rounded-sm cursor-pointer text-[11px] " +
                      (active
                        ? "bg-primary text-primary-foreground"
                        : "text-muted-foreground hover:text-foreground hover:bg-muted")
                    }
                  >
                    {ROLE_LABELS[r]}
                  </button>
                );
              })}
            </div>
            <Input
              type="number"
              value={expiresDays}
              onChange={(e) => setExpiresDays(e.target.value)}
              placeholder="有効期限 (日、0=無期限)"
              min={0}
              max={365}
              disabled={submitting}
              className="h-8 text-xs"
              title="0 = 無期限、最大 365 日"
            />
          </div>
          <div className="flex gap-1.5">
            <Button
              type="submit"
              disabled={submitting || !pseudoEmail.trim()}
              size="sm"
            >
              {submitting ? "発行中..." : "発行"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setShowForm(false);
                setError(null);
              }}
            >
              キャンセル
            </Button>
          </div>
        </form>
      )}

      {/* 既存 token 一覧 */}
      {loading && links.length === 0 ? (
        <Skeleton className="h-8 w-full" />
      ) : links.length === 0 ? (
        !showForm && !justIssued ? (
          <p className="text-xs text-muted-foreground py-1">
            まだ token は発行されていません。
          </p>
        ) : null
      ) : (
        <ul className="space-y-1.5">
          {links.map((link) => (
            <li
              key={link.token_hash_prefix}
              className={
                "rounded-md border px-2 py-1.5 text-xs space-y-0.5 " +
                (link.is_active ? "" : "opacity-50 line-through")
              }
            >
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="font-mono truncate" title={link.pseudo_email}>
                  {link.pseudo_display_name || link.pseudo_email}
                </span>
                <Badge
                  variant={link.role === "analyst" ? "default" : "outline"}
                  className="text-[10px]"
                >
                  {ROLE_LABELS[link.role as ShareRole] ?? link.role}
                </Badge>
                {!link.is_active && (
                  <Badge variant="secondary" className="text-[10px]">
                    {link.revoked_at ? "失効" : "期限切れ"}
                  </Badge>
                )}
                {link.label && (
                  <span className="text-muted-foreground truncate">
                    {link.label}
                  </span>
                )}
                {link.is_active && (
                  <button
                    type="button"
                    className="ml-auto text-muted-foreground hover:text-destructive cursor-pointer"
                    disabled={submitting}
                    onClick={() => handleRevoke(link.token_hash_prefix)}
                    title="この token を失効する (取り消し不可)"
                  >
                    ×
                  </button>
                )}
              </div>
              <div className="text-[10px] text-muted-foreground font-mono">
                {link.token_hash_prefix}…{" "}
                {link.expires_at
                  ? `· 失効: ${new Date(link.expires_at).toLocaleDateString("ja-JP")}`
                  : "· 無期限"}
                {" · "}発行: {new Date(link.created_at).toLocaleDateString("ja-JP")}
                {/* S1-OBS9/UX5 (2026-06-29): 最終使用時刻を表示。dormant /
                    漏洩疑い token の特定に使う。null = 未使用 */}
                {" · "}
                {link.last_used_at
                  ? `最終使用: ${new Date(link.last_used_at).toLocaleDateString("ja-JP")}`
                  : "未使用"}
              </div>
            </li>
          ))}
        </ul>
      )}

      {error && (
        <p className="text-xs text-destructive bg-destructive/10 px-2 py-1.5 rounded">
          {error}
        </p>
      )}
    </div>
  );
}
