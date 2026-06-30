// CQ14 (2026-06-30): 複数 file に重複していた helper を集約。
//
// formatDate は呼び出し側ごとに 5 種類のフォーマット差 (一覧 vs 詳細 vs
// バッジ vs cell log etc.) があり意図的なので、ここでは触らない。

import type { ShareRole } from "./api";

/**
 * バイト数を人間可読 (B / KB / MB) 表記に。
 *
 * - < 1 KB: そのままバイト
 * - < 1 MB: 1.5 KB のように KB
 * - それ以上: 1.5 MB のように MB
 *
 * 元: `records/[id]/page.tsx` と `share/[id]/page.tsx` に同一実装が
 * 重複していた。
 */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

/**
 * 共有 role の長文ラベル (form / dialog 内の説明的表示用)。
 *
 * 元: `share-dialog.tsx` の ``ROLE_LABEL`` + ``TOKEN_ROLE_LABEL``、
 * `share/[id]/page.tsx` の ``ROLE_LABEL`` の 3 箇所に同一定義が散在
 * していた。
 */
export const ROLE_LABELS: Record<ShareRole, string> = {
  viewer: "閲覧のみ",
  analyst: "閲覧 + 解析投稿",
};

/**
 * 共有 role の短縮ラベル (Badge 内など、スペースが厳しい場所用)。
 *
 * 元: `shared-records-list.tsx` の ``ROLE_LABEL``。長文版と意味的に対の
 * 関係なので、明示的に ``_BADGE`` suffix で区別する。
 */
export const ROLE_LABELS_BADGE: Record<ShareRole, string> = {
  viewer: "閲覧",
  analyst: "解析",
};
