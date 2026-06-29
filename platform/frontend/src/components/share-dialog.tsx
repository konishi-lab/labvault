"use client";

// S1 Phase 1B (PR for 2026-06-29): record 共有モーダル。
//
// PR #84 で SDK + backend に grant / revoke / list endpoint が整い、PR #85
// で shared-with-me 一覧が整った。本コンポーネントはそれを使う Web UI 側で、
// record 詳細から「共有」ボタンで開くダイアログ。
//
// 表示する情報:
// - 既存 share の一覧 (email + role + 削除ボタン)
// - 新規 grant フォーム (email + role 選択 + 追加ボタン)
// - 自分が share されている場合は自分の role が見える
//
// 認可:
// - grant 主体 (record.created_by 本人 / team admin / super-admin) でない
//   user が grant/revoke を試みると backend が 403 を返す。本 UI は事前
//   判定 (frontend 側) で grant フォームを隠す + backend 403 で inline
//   error 表示の二重防御。
// - 自分自身に共有しようとすると backend が 400。これも inline で表示。

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  fetchShareLinks,
  fetchShares,
  grantShare,
  issueShareLink,
  revokeShare,
  revokeShareLink,
  type CreatedShareLink,
  type ShareEntry,
  type ShareLinkInfo,
  type ShareLinkRole,
  type ShareRole,
} from "@/lib/api";

interface ShareDialogProps {
  recordId: string;
  /** record の created_by。「あなたが grant 主体か」の前段判定に使う。 */
  createdBy: string;
  /** record owner team。team admin なら grant 主体になれる。null は
   *  team 情報が分からない (shared-with-me 経由でない通常表示など)。
   *  通常は currentTeam を渡せば良い。 */
  ownerTeam: string | null;
  /** 詳細ページ初期 fetch 時に取れた shares 辞書 (キャッシュ)。
   *  null なら open 時に backend から再取得する。 */
  initialShares?: Record<string, string> | null;
  /** 現在ログインユーザーの email (grant 主体判定 + 自己 share 防止)。 */
  currentUserEmail: string | null;
  /** legacy global super-admin (allowed_users.role === "admin")。 */
  isSuperAdmin: boolean;
  /** ユーザーが ownerTeam の admin かどうか。 */
  isOwnerTeamAdmin: boolean;
  /** grant / revoke 成功時に呼ばれる。記録詳細側で shares を再同期するため。 */
  onUpdated?: (shares: Record<string, string>) => void;
}

const ROLE_LABEL: Record<string, string> = {
  viewer: "閲覧のみ",
  analyst: "閲覧 + 解析投稿",
};

const ROLE_DESCRIPTION: Record<string, string> = {
  viewer: "record 詳細とファイルを閲覧できます。条件・結果・ファイルの追加は不可。",
  analyst:
    "閲覧に加え、子 record (= 解析結果) の作成 + ファイル upload ができます。record 自体の編集は不可。",
};

export function ShareDialog({
  recordId,
  createdBy,
  ownerTeam,
  initialShares,
  currentUserEmail,
  isSuperAdmin,
  isOwnerTeamAdmin,
  onUpdated,
}: ShareDialogProps) {
  const [open, setOpen] = useState(false);
  const [shares, setShares] = useState<ShareEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newEmail, setNewEmail] = useState("");
  const [newRole, setNewRole] = useState<ShareRole>("viewer");
  const [submitting, setSubmitting] = useState(false);
  // S1-UX2 hot-fix (2026-06-29): 発行直後の raw token (1 回限り表示)
  // は親 ShareDialog に持ち上げ、modal close を抑止する。child の
  // ShareLinksPanel が unmount された瞬間に raw token が永久喪失する
  // 罠を構造的に防ぐ。
  const [justIssued, setJustIssued] = useState<CreatedShareLink | null>(null);

  // grant 主体判定 (frontend 側で先回り)。backend の `can_grant` と一致:
  // super_admin OR record.created_by 本人 OR owner team の admin。
  // shares 経由でアクセスしている user は再 grant 不可 (= ここで false)。
  const canGrant =
    isSuperAdmin ||
    (currentUserEmail !== null &&
      createdBy.toLowerCase() === currentUserEmail.toLowerCase()) ||
    (ownerTeam !== null && isOwnerTeamAdmin);

  // initialShares (詳細 fetch 時のキャッシュ) があればそれを起点に出す。
  // ダイアログを開いたタイミングで backend から最新を取り直す (race 対策)。
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchShares(recordId)
      .then((items) => {
        if (cancelled) return;
        setShares(items);
      })
      .catch((e: Error) => {
        if (cancelled) return;
        setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, recordId]);

  // open 前は initialShares で表示 (再 fetch 待ちの間も chip が見える)
  useEffect(() => {
    if (open) return;
    if (initialShares) {
      setShares(
        Object.entries(initialShares).map(([email, role]) => ({ email, role })),
      );
    } else {
      setShares([]);
    }
  }, [initialShares, open]);

  const handleGrant = async (e: React.FormEvent) => {
    e.preventDefault();
    const email = newEmail.trim().toLowerCase();
    if (!email) {
      setError("email を入力してください");
      return;
    }
    if (!email.includes("@")) {
      setError("有効な email を入力してください");
      return;
    }
    if (currentUserEmail && email === currentUserEmail.toLowerCase()) {
      setError("自分自身には共有できません");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const detail = await grantShare(recordId, email, newRole);
      const updated = detail.shares ?? {};
      setShares(
        Object.entries(updated).map(([e, r]) => ({ email: e, role: r })),
      );
      onUpdated?.(updated);
      setNewEmail("");
      // role は最後に選んだものを keep — 連続 grant を素早く回せる
    } catch (err) {
      const msg = (err as Error).message;
      // backend は `... 403 ...` のような文字列で返す。表示用に整形。
      if (msg.includes("403")) {
        setError("この record の共有を変更する権限がありません");
      } else if (msg.includes("400")) {
        setError("入力内容が無効です (email 形式 / role / 自己共有)");
      } else {
        setError(msg);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleRevoke = async (email: string) => {
    setSubmitting(true);
    setError(null);
    try {
      const detail = await revokeShare(recordId, email);
      const updated = detail.shares ?? {};
      setShares(
        Object.entries(updated).map(([e, r]) => ({ email: e, role: r })),
      );
      onUpdated?.(updated);
    } catch (err) {
      const msg = (err as Error).message;
      if (msg.includes("403")) {
        setError("この record の共有を変更する権限がありません");
      } else {
        setError(msg);
      }
    } finally {
      setSubmitting(false);
    }
  };

  // 自分自身が shared されている role を強調表示するためのマーキング。
  const myShareRole =
    currentUserEmail !== null
      ? shares.find(
          (s) => s.email.toLowerCase() === currentUserEmail.toLowerCase(),
        )?.role ?? null
      : null;

  // S1-UX2 hot-fix: 発行直後の raw token を表示中は modal close を抑止
  // する。ESC / 外側クリック / X ボタンいずれでも閉じない。明示的な
  // 「閉じる」ボタン (ShareLinksPanel 内) でだけ setJustIssued(null) →
  // 通常の close が可能になる。raw token は Firestore に hash しか
  // 保存されていない (再表示不可) ため、誤操作で永久喪失する罠を防ぐ。
  const handleOpenChange = (next: boolean) => {
    if (!next && justIssued) {
      return; // close を無視
    }
    setOpen(next);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger
        render={
          <Button
            variant="outline"
            size="sm"
            className="gap-1"
            title="この record を別チームメンバー / 外部協力者に共有"
          >
            <span aria-hidden>🔗</span>
            共有
            {shares.length > 0 && (
              <Badge variant="secondary" className="ml-1 h-4 px-1 text-[10px]">
                {shares.length}
              </Badge>
            )}
          </Button>
        }
      />
      <DialogContent
        className="sm:max-w-md"
        // S1-UX2: raw token 表示中は右上 X ボタンも隠す (handleOpenChange
        // が close を抑止するので X を残しても閉じないが、UI 上の混乱を防ぐ)。
        showCloseButton={!justIssued}
      >
        <DialogHeader>
          <DialogTitle>record の共有</DialogTitle>
          <DialogDescription>
            別チームメンバーや外部の協力者にこの record を共有します。
            <strong>viewer</strong> は閲覧のみ、<strong>analyst</strong> は
            解析結果 (子 record / ファイル) の追加も可能。
          </DialogDescription>
        </DialogHeader>

        {/* 自分が shared されている場合のお知らせ (情報表示) */}
        {myShareRole && (
          <div className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs">
            あなたはこの record に
            <strong className="mx-1">
              {ROLE_LABEL[myShareRole] ?? myShareRole}
            </strong>
            として share されています。
          </div>
        )}

        {/* 既存 share の一覧 */}
        <div className="space-y-2">
          <div className="text-xs font-medium text-muted-foreground">
            共有中 ({shares.length})
          </div>
          {loading && shares.length === 0 ? (
            <Skeleton className="h-12 w-full" />
          ) : shares.length === 0 ? (
            <p className="text-xs text-muted-foreground py-2">
              まだ誰にも共有されていません。
            </p>
          ) : (
            <ul className="space-y-1.5">
              {shares.map((s) => (
                <li
                  key={s.email}
                  className="flex items-center justify-between gap-2 rounded-md border px-2 py-1.5 text-xs"
                >
                  <span className="font-mono truncate" title={s.email}>
                    {s.email}
                  </span>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <Badge
                      variant={s.role === "analyst" ? "default" : "outline"}
                      className="text-[10px]"
                      title={ROLE_DESCRIPTION[s.role] ?? s.role}
                    >
                      {ROLE_LABEL[s.role] ?? s.role}
                    </Badge>
                    {canGrant && (
                      <button
                        type="button"
                        className="text-muted-foreground hover:text-destructive cursor-pointer"
                        disabled={submitting}
                        onClick={() => handleRevoke(s.email)}
                        title="この共有を取り消す"
                      >
                        ×
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* 新規 grant フォーム — grant 主体だけが見える */}
        {canGrant ? (
          <form onSubmit={handleGrant} className="space-y-2">
            <div className="text-xs font-medium text-muted-foreground">
              新しく共有する
            </div>
            <Input
              type="email"
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
              placeholder="email@example.com"
              required
              disabled={submitting}
              className="h-9 text-sm"
            />
            <div
              className="inline-flex items-center rounded-md border border-input p-0.5 bg-background text-xs"
              role="radiogroup"
              aria-label="権限"
            >
              {(["viewer", "analyst"] as ShareRole[]).map((r) => {
                const active = newRole === r;
                return (
                  <button
                    key={r}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    disabled={submitting}
                    onClick={() => setNewRole(r)}
                    title={ROLE_DESCRIPTION[r]}
                    className={
                      "px-2.5 py-1 rounded-sm transition-colors cursor-pointer " +
                      (active
                        ? "bg-primary text-primary-foreground"
                        : "text-muted-foreground hover:text-foreground hover:bg-muted")
                    }
                  >
                    {ROLE_LABEL[r]}
                  </button>
                );
              })}
            </div>
            <Button
              type="submit"
              disabled={submitting || !newEmail.trim()}
              className="w-full"
              size="sm"
            >
              {submitting ? "追加中..." : "共有を追加"}
            </Button>
          </form>
        ) : (
          <p className="text-xs text-muted-foreground border-t pt-3">
            共有の追加・削除は record の作成者 (
            <span className="font-mono">{createdBy || "(不明)"}</span>) または
            team admin のみが行えます。
          </p>
        )}

        {/* inline error */}
        {error && (
          <p className="text-xs text-destructive bg-destructive/10 px-2 py-1.5 rounded">
            {error}
          </p>
        )}

        {/* S1 Phase 2: 外部 token 共有 (ls_*) — Firebase アカウントを持たない
            協力者向け。grant 主体だけが見える */}
        {canGrant && open && (
          <ShareLinksPanel
            recordId={recordId}
            justIssued={justIssued}
            setJustIssued={setJustIssued}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

// --- S1 Phase 2: 外部 token (ls_*) panel -----------------------------------

const TOKEN_ROLE_LABEL: Record<string, string> = {
  viewer: "閲覧のみ",
  analyst: "閲覧 + 解析投稿",
};

function ShareLinksPanel({
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
  const [role, setRole] = useState<ShareLinkRole>("viewer");
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
    const days = Number(expiresDays);
    if (!Number.isInteger(days) || days < 0 || days > 365) {
      setError("有効期限は 0〜365 日で指定してください (0 = 無期限)");
      return;
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
    const url = `${window.location.origin}/share/${justIssued.token}`;
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
            {TOKEN_ROLE_LABEL[justIssued.role] ?? justIssued.role})
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
              {copied ? "✓ コピー" : "共有 URL (/share/...) をコピー"}
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
              {(["viewer", "analyst"] as ShareLinkRole[]).map((r) => {
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
                    {TOKEN_ROLE_LABEL[r]}
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
                  {TOKEN_ROLE_LABEL[link.role] ?? link.role}
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
