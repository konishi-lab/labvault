"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { BackButton } from "@/components/back-button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  createToken,
  listTokens,
  revokeToken,
  type CreatedToken,
  type TokenSummary,
} from "@/lib/api";

export default function AccountTokensPage() {
  const [tokens, setTokens] = useState<TokenSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [label, setLabel] = useState("");
  const [creating, setCreating] = useState(false);
  const [justCreated, setJustCreated] = useState<CreatedToken | null>(null);
  const [copied, setCopied] = useState(false);

  const [revoking, setRevoking] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await listTokens();
      setTokens(list);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const handleCreate = async () => {
    setError(null);
    setCreating(true);
    setCopied(false);
    try {
      const t = await createToken(label.trim());
      setJustCreated(t);
      setLabel("");
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  };

  const handleCopy = async () => {
    if (!justCreated) return;
    try {
      await navigator.clipboard.writeText(justCreated.token);
      setCopied(true);
    } catch {
      // ignore
    }
  };

  const handleRevoke = async (t: TokenSummary) => {
    if (
      !confirm(
        `${t.label || "(無題)"} (${t.prefix}...) を失効させますか?\nこの操作は取り消せません。`,
      )
    ) {
      return;
    }
    setError(null);
    setRevoking(t.id);
    try {
      await revokeToken(t.id);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRevoking(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <BackButton />
        <h1 className="text-2xl font-bold tracking-tight">API トークン</h1>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base font-medium">
            新しいトークンを発行
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-1 flex-col gap-1 text-sm">
              <span className="text-xs font-medium text-muted-foreground">
                ラベル (用途のメモ・必須)
              </span>
              <Input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                onKeyDown={(e) => {
                  if (e.nativeEvent.isComposing || e.keyCode === 229) return;
                  if (e.key === "Enter") {
                    e.preventDefault();
                    if (label.trim()) void handleCreate();
                  }
                }}
                placeholder="例: 装置 PC, ノート PC, CI"
                disabled={creating}
                maxLength={100}
              />
            </label>
            <Button
              onClick={handleCreate}
              disabled={creating || !label.trim()}
              title={
                !label.trim()
                  ? "ラベルを入力してください (後でどの token がどの用途かわかるように)"
                  : undefined
              }
            >
              {creating ? "発行中..." : "発行"}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            <code className="rounded bg-muted px-1 py-0.5">
              Authorization: Bearer lv_...
            </code>{" "}
            で labvault API に認証できます。SDK / curl / 装置 PC スクリプト等で利用。
          </p>
        </CardContent>
      </Card>

      {justCreated && (
        <Card className="border-amber-300 bg-amber-50/50">
          <CardHeader>
            <CardTitle className="text-base font-medium text-amber-900">
              発行されたトークン (この画面を離れると再表示できません)
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <code className="flex-1 break-all rounded border bg-background px-2 py-1 font-mono text-xs">
                {justCreated.token}
              </code>
              <Button size="sm" onClick={handleCopy}>
                {copied ? "コピー済み" : "コピー"}
              </Button>
            </div>
            <div className="space-y-2 text-xs text-amber-900">
              <p>
                <strong>このトークンで pip install もランタイム認証も両方できます</strong>
                (gcloud 不要)。下に使い方の例を貼っているので、必要な部分を
                コピーしてください。
              </p>
              <UsageSnippets token={justCreated.token} />
            </div>
            <div className="flex justify-end">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setJustCreated(null)}
              >
                閉じる
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {error && <p className="text-sm text-destructive">エラー: {error}</p>}

      <Card>
        <CardHeader>
          <CardTitle className="text-base font-medium">
            有効なトークン
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-2">
              {Array.from({ length: 2 }).map((_, i) => (
                <Skeleton key={i} className="h-14 w-full" />
              ))}
            </div>
          ) : tokens.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              発行済みのトークンはありません。
            </p>
          ) : (
            <ul className="divide-y">
              {tokens.map((t) => {
                const expanded = expandedId === t.id;
                return (
                  <li key={t.id} className="py-2 text-sm">
                    <div className="flex flex-wrap items-center gap-3">
                      <button
                        type="button"
                        onClick={() =>
                          setExpandedId(expanded ? null : t.id)
                        }
                        className="flex-1 min-w-0 text-left rounded px-1 -mx-1 py-0.5 hover:bg-muted/40 cursor-pointer transition-colors"
                        aria-expanded={expanded}
                        aria-controls={`token-usage-${t.id}`}
                        title="クリックして使い方の例を表示"
                      >
                        <div className="font-medium flex items-center gap-1">
                          <span
                            className="inline-block w-3 text-muted-foreground"
                            aria-hidden
                          >
                            {expanded ? "▾" : "▸"}
                          </span>
                          {t.label || "(無題)"}
                        </div>
                        <div className="text-xs text-muted-foreground pl-4">
                          <code className="rounded bg-muted px-1 py-0.5">
                            {t.prefix}...
                          </code>
                          {" — 作成: "}
                          {new Date(t.created_at).toLocaleString("ja-JP")}
                          {t.last_used_at &&
                            ` — 最終利用: ${new Date(t.last_used_at).toLocaleString("ja-JP")}`}
                        </div>
                      </button>
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => handleRevoke(t)}
                        disabled={revoking === t.id}
                      >
                        {revoking === t.id ? "失効中..." : "失効"}
                      </Button>
                    </div>
                    {expanded && (
                      <div
                        id={`token-usage-${t.id}`}
                        className="mt-2 ml-4 rounded border bg-muted/30 px-3 py-2 space-y-2 text-xs"
                      >
                        <p className="text-muted-foreground">
                          このトークンの raw 文字列は <strong>発行直後の
                          画面でしか表示されない</strong> ため、ここでは
                          表示できません。コピーしたものを以下の{" "}
                          <code className="rounded bg-background px-1">
                            &lt;YOUR_TOKEN&gt;
                          </code>{" "}
                          に置き換えて使ってください。失くしたら新しく
                          発行 + 古い方は「失効」してください。
                        </p>
                        <UsageSnippets token="<YOUR_TOKEN>" />
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

const PLATFORM_URL =
  "https://labvault-api-355809880738.asia-northeast1.run.app";

/**
 * トークンの使い方サンプル (pip install + labvault auth set-token +
 * credentials 手書き) を一括表示するコンポーネント。
 *
 * - 発行成功カードでは `token` に raw 文字列を入れて完成形を表示する
 * - 発行済リストの expand では `token` を `<YOUR_TOKEN>` のような
 *   placeholder にしてテンプレ表示する (raw token はもう取れないため)
 */
function UsageSnippets({ token }: { token: string }) {
  const proxy = `https://__token__:${token}@labvault-api-355809880738.asia-northeast1.run.app/api/pypi/simple/`;
  return (
    <div className="space-y-2">
      <p className="font-semibold">
        1. SDK ランタイム認証 (推奨: <code>labvault auth set-token</code>)
      </p>
      <pre className="overflow-x-auto rounded border bg-background px-2 py-1 font-mono text-[11px]">
{`# Mac / Linux / Windows 共通。--token-stdin で shell 履歴に残らない
echo "${token}" | labvault auth set-token --token-stdin

# 装置 PC では識別子を付ける
echo "${token}" | labvault auth set-token --token-stdin --user instrument-xrd-1`}
      </pre>

      <p className="font-semibold">2. pip install (Mac / Linux)</p>
      <pre className="overflow-x-auto rounded border bg-background px-2 py-1 font-mono text-[11px]">
{`pip install \\
  --index-url https://pypi.org/simple/ \\
  --extra-index-url "${proxy}" \\
  "labvault[all]"`}
      </pre>

      <p className="font-semibold">3. pip install (Windows PowerShell)</p>
      <pre className="overflow-x-auto rounded border bg-background px-2 py-1 font-mono text-[11px]">
{`pip install \`
  --index-url https://pypi.org/simple/ \`
  --extra-index-url "${proxy}" \`
  "labvault[all]"`}
      </pre>

      <p className="font-semibold">
        4. (代替) 手書きで <code>~/.labvault/credentials</code>
      </p>
      <pre className="overflow-x-auto rounded border bg-background px-2 py-1 font-mono text-[11px]">
{`LABVAULT_TOKEN=${token}
LABVAULT_PLATFORM_URL=${PLATFORM_URL}
LABVAULT_TEAM=konishi-lab`}
      </pre>
      <p>
        Windows なら{" "}
        <code className="rounded bg-background px-1">
          %USERPROFILE%\.labvault\credentials
        </code>
        。詳細は{" "}
        <a
          className="underline"
          href="https://github.com/konishi-lab/labvault/blob/main/docs/instrument_pc_setup.md"
          target="_blank"
          rel="noreferrer"
        >
          装置 PC セットアップ手順
        </a>
        。
      </p>
    </div>
  );
}
