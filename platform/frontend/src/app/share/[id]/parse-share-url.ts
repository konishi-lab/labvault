// S1 Phase D1 (2026-06-30): /share/<id>[#<token>] の URL 解釈を 1 箇所に
// 集約。以下の 3 パターン:
//
// 1. 新形式: /share/<record_id>#<token>
//    fragment に token がある。path id は record_id。
//    → token で scope を verify、record を fetch。
//
// 2. 旧形式: /share/<token> (fragment 無し)
//    Phase 2B 時代の URL。path id が token そのもの。
//    → token で scope を fetch、scope.record_id を取り、
//      window.location.replace(`/share/${scope.record_id}#${token}`)
//      で新 URL に付け替える (= ユーザのブックマーク / 履歴も更新)。
//
// 3. それ以外: path id が token でも record_id でもない / hash も無い
//    → 「URL が壊れています」エラー表示。
//
// 識別ヒューリスティック: token は ``ls_<hex>`` 固定 prefix
// (share_links.py:generate_token 参照)。record_id は Crockford Base32 6
// 文字 (大文字英数のみ) という別フォーマットなので衝突しない。

export type ShareUrlParse =
  | { kind: "new"; recordId: string; token: string }
  | { kind: "migrate"; token: string }
  | { kind: "invalid"; reason: string };

// share-link backend が ``secrets.token_urlsafe(32)`` の前に必ず
// ``ls_`` を付けて発行する。新規 token はこの prefix を保証する。
export const TOKEN_PREFIX = "ls_";

/**
 * Page で `useParams()` → `id` と `window.location.hash` を切り出して
 * 渡す。pure 関数なので vitest で直接テストできる。
 */
export function parseShareUrl(input: {
  pathId: string;
  hash: string; // 先頭 '#' は呼び出し側で除去済み (例: "ls_abc")
}): ShareUrlParse {
  const pathId = input.pathId?.trim() ?? "";
  const hash = input.hash?.trim() ?? "";

  if (!pathId) {
    return { kind: "invalid", reason: "URL が指定されていません" };
  }

  // 新形式: fragment に ls_ で始まる token がある
  if (hash.startsWith(TOKEN_PREFIX)) {
    return { kind: "new", recordId: pathId, token: hash };
  }

  // 旧形式: hash が無く path id 自体が token
  if (!hash && pathId.startsWith(TOKEN_PREFIX)) {
    return { kind: "migrate", token: pathId };
  }

  // hash はあるが ls_ で始まらない / path id も token でない
  if (hash) {
    return {
      kind: "invalid",
      reason:
        "URL の token (# 以降) の形式が不正です。発行者から再度 link を貰い直してください。",
    };
  }
  return {
    kind: "invalid",
    reason:
      "URL に token が含まれていません。発行者から /share/<record_id>#<token> 形式の link を貰ってください。",
  };
}

/** ShareLinksPanel が発行直後に組み立てる共有 URL。 */
export function buildShareUrl(input: {
  origin: string;
  recordId: string;
  token: string;
}): string {
  return `${input.origin}/share/${input.recordId}#${input.token}`;
}
