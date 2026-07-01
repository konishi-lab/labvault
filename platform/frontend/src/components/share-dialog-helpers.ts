import type { ShareLinkInfo } from "@/lib/api";

// S1 TEST15 (2026-06-30): share-dialog.tsx のロジック単体テスト用の pure
// helper 群。component 本体に inline 展開されていたものを切り出した。
// バグらせやすい部分 (UX4 重複検出 / UX10 expires_days 入力 / canGrant
// 判定) はここに集約して unit test を当てる。

export interface CanGrantInput {
  isSuperAdmin: boolean;
  ownerTeam: string | null;
  isOwnerTeamAdmin: boolean;
}

/**
 * ``grant 主体`` 判定。backend の ``can_grant`` と一致:
 * super_admin OR owner team の admin。
 *
 * **admin only 化 (2026-07-01)**: 以前は record.created_by 本人にも
 * grant を許していたが、実験者が誤って他 team に record を公開する
 * 事故を防ぐため admin 集約に統一。record 作成者は team admin に
 * 依頼する形になる。shares 経由でアクセスしている user は再 grant
 * 不可 (= ここで false) — 従来通り。
 */
export function canGrant({
  isSuperAdmin,
  ownerTeam,
  isOwnerTeamAdmin,
}: CanGrantInput): boolean {
  if (isSuperAdmin) return true;
  if (ownerTeam !== null && isOwnerTeamAdmin) return true;
  return false;
}

export type ValidateExpiresDaysResult =
  | { ok: true; days: number }
  | { ok: false; error: string };

/**
 * S1-UX10 hot-fix (2026-06-29): share-link 発行フォームの ``有効期限``
 * 入力検証。
 *
 * - 空欄 → 0 (= 無期限) と混同しないよう reject。
 * - 0〜365 の整数のみ許可。0 = 無期限 (仕様)。
 * - 365 超 / 負値 / 小数 / 非数 は reject。
 *
 * 戻り値: ``{ok:true, days}`` か ``{ok:false, error}``。error はそのまま
 * UI に表示できる日本語メッセージ。
 */
export function validateExpiresDays(raw: string): ValidateExpiresDaysResult {
  const trimmed = raw.trim();
  if (!trimmed) {
    return {
      ok: false,
      error: "有効期限を入力してください (無期限なら 0 を明示的に)",
    };
  }
  const days = Number(trimmed);
  if (!Number.isInteger(days) || days < 0 || days > 365) {
    return {
      ok: false,
      error: "有効期限は 0〜365 日で指定してください (0 = 無期限)",
    };
  }
  return { ok: true, days };
}

/**
 * S1-UX4 hot-fix (2026-06-29): 同じ pseudo_email で **active な** share
 * link を検索。発行 form 送信時に「既存の active token を revoke して
 * 上書きするか?」の確認 dialog 表示判定に使う。
 *
 * email 比較は lowercase で normalize。revoked / expired は除外する
 * (= 同じ email でも問題なく新規発行できる)。
 */
export function findActiveLinkForEmail(
  links: ShareLinkInfo[],
  pseudoEmail: string,
): ShareLinkInfo | undefined {
  const target = pseudoEmail.trim().toLowerCase();
  if (!target) return undefined;
  return links.find(
    (l) => l.is_active && l.pseudo_email.toLowerCase() === target,
  );
}
