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
  fetchShares,
  grantShare,
  revokeShare,
  type CreatedShareLink,
  type ShareEntry,
  type ShareRole,
} from "@/lib/api";
import { canGrant as computeCanGrant } from "./share-dialog-helpers";
import { ROLE_LABELS } from "@/lib/format";
import { ShareLinksPanel } from "./share-link-panel";

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

  // S1 TEST15 (2026-06-30): pure logic は share-dialog-helpers に切出し、
  // unit test 可能にしている。backend の ``can_grant`` と一致:
  // super_admin OR record.created_by 本人 OR owner team の admin。
  const canGrant = computeCanGrant({
    isSuperAdmin,
    currentUserEmail,
    createdBy,
    ownerTeam,
    isOwnerTeamAdmin,
  });

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
              {ROLE_LABELS[myShareRole as ShareRole] ?? myShareRole}
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
                      {ROLE_LABELS[s.role as ShareRole] ?? s.role}
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
                    {ROLE_LABELS[r]}
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

