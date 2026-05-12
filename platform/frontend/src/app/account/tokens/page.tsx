"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
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
        <Link href="/">
          <Button variant="ghost" className="cursor-pointer">
            ← 一覧
          </Button>
        </Link>
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
                ラベル (用途のメモ)
              </span>
              <Input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                onKeyDown={(e) => {
                  if (e.nativeEvent.isComposing || e.keyCode === 229) return;
                  if (e.key === "Enter") {
                    e.preventDefault();
                    void handleCreate();
                  }
                }}
                placeholder="例: 装置 PC, ノート PC, CI"
                disabled={creating}
                maxLength={100}
              />
            </label>
            <Button onClick={handleCreate} disabled={creating}>
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
            <p className="text-xs text-amber-900">
              安全な場所に保存してください。例:{" "}
              <code className="rounded bg-background px-1">
                ~/.labvault/credentials
              </code>{" "}
              に <code className="rounded bg-background px-1">LABVAULT_TOKEN=...</code>{" "}
              として配置するなど。
            </p>
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
              {tokens.map((t) => (
                <li
                  key={t.id}
                  className="flex flex-wrap items-center gap-3 py-2 text-sm"
                >
                  <div className="flex-1 space-y-0.5">
                    <div className="font-medium">{t.label || "(無題)"}</div>
                    <div className="text-xs text-muted-foreground">
                      <code className="rounded bg-muted px-1 py-0.5">
                        {t.prefix}...
                      </code>
                      {" — 作成: "}
                      {new Date(t.created_at).toLocaleString("ja-JP")}
                      {t.last_used_at &&
                        ` — 最終利用: ${new Date(t.last_used_at).toLocaleString("ja-JP")}`}
                    </div>
                  </div>
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={() => handleRevoke(t)}
                    disabled={revoking === t.id}
                  >
                    {revoking === t.id ? "失効中..." : "失効"}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
