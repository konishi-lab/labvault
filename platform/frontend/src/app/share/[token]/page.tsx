"use client";

// S1 Phase 2B: ``/share/{token}`` 公開ページ。
//
// Firebase アカウントを持たない外部協力者向け。token を URL から取り出し、
// `Authorization: Bearer ls_<hex>` で API を叩く。AuthGate は /share/* を
// skip するので、Firebase ログイン状態に関係なく開ける。
//
// 流れ:
// 1. URL の token で `/api/share-links/me` を叩いて scope (record_id /
//    team / role / pseudo identity) を取得
// 2. 同じ token で `/api/records/{record_id}` を叩いて record 詳細を表示
// 3. analyst なら、簡易な「ファイル upload」フォームを出す
//    (子 record 作成は MVP では省略 — SDK 経由で実施)

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  fetchShareLinkScope,
  shareTokenFetch,
  type RecordDetail,
  type ShareLinkScopeMe,
} from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const ROLE_LABEL: Record<string, string> = {
  viewer: "閲覧のみ",
  analyst: "閲覧 + 解析投稿",
};

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("ja-JP");
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

export default function SharePage() {
  const params = useParams();
  const token = (params.token as string) || "";

  const [scope, setScope] = useState<ShareLinkScopeMe | null>(null);
  const [record, setRecord] = useState<RecordDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setError("token が指定されていません");
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        // 1. scope (record_id) を解決
        const s = await fetchShareLinkScope(token);
        if (cancelled) return;
        setScope(s);
        // 2. record 詳細を fetch (同じ token で Authorization)
        const res = await shareTokenFetch(
          token,
          `${API_BASE}/api/records/${s.record_id}`,
          { headers: { "X-Labvault-Team": s.team } },
        );
        if (!res.ok) {
          throw new Error(`record の取得に失敗しました (${res.status})`);
        }
        const rec = (await res.json()) as RecordDetail;
        if (cancelled) return;
        setRecord(rec);
      } catch (e) {
        if (cancelled) return;
        const msg = (e as Error).message;
        if (msg.includes("401")) {
          setError(
            "この token は無効または期限切れです。link を発行した方に再発行を依頼してください。",
          );
        } else if (msg.includes("403")) {
          setError(
            "この token ではこの record にアクセスできません (scope mismatch)",
          );
        } else {
          setError(msg);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (loading) {
    return (
      <div className="mx-auto max-w-3xl space-y-4 p-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="mx-auto max-w-md space-y-3 rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-sm m-6">
        <div className="text-base font-semibold text-destructive">
          共有 link を開けません
        </div>
        <p className="text-muted-foreground">{error}</p>
      </div>
    );
  }

  if (!scope || !record) {
    return null;
  }

  const conditions = Object.entries(record.conditions);
  const results = Object.entries(record.results).filter(
    ([key]) => !key.endsWith("__analysis_id"),
  );
  const isAnalyst = scope.role === "analyst";

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4 sm:p-6">
      {/* ヘッダ: タイトル + scope バッジ */}
      <div className="space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <Badge variant="outline" className="text-xs gap-1">
            <span aria-hidden>🔗</span>外部共有
          </Badge>
          <Badge
            variant={isAnalyst ? "default" : "secondary"}
            className="text-xs"
            title={
              isAnalyst
                ? "閲覧 + 解析結果 (ファイル) 投稿が可能"
                : "閲覧 + ファイル DL のみ"
            }
          >
            {ROLE_LABEL[scope.role] ?? scope.role}
          </Badge>
          <span className="text-xs text-muted-foreground">
            as <span className="font-mono">{scope.pseudo_email}</span>
            {scope.pseudo_display_name && ` (${scope.pseudo_display_name})`}
          </span>
          {scope.expires_at && (
            <span className="text-xs text-muted-foreground">
              · 失効:{" "}
              {new Date(scope.expires_at).toLocaleDateString("ja-JP")}
            </span>
          )}
        </div>
        <h1 className="text-2xl font-bold tracking-tight">{record.title}</h1>
        <p className="text-xs text-muted-foreground">
          <span className="font-mono">{record.id}</span>
          {" · "}team: {scope.team}
          {" · "}作成: {record.created_by || "-"}
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {/* 基本情報 */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">基本情報</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">タイプ</span>
              <span>{record.type}</span>
            </div>
            <Separator />
            <div className="flex justify-between">
              <span className="text-muted-foreground">ステータス</span>
              <Badge variant="secondary" className="text-xs">
                {record.status}
              </Badge>
            </div>
            <Separator />
            <div className="flex justify-between">
              <span className="text-muted-foreground">作成日</span>
              <span>{formatDate(record.created_at)}</span>
            </div>
            <Separator />
            <div className="flex justify-between">
              <span className="text-muted-foreground">更新日</span>
              <span>{formatDate(record.updated_at)}</span>
            </div>
            {record.tags.length > 0 && (
              <>
                <Separator />
                <div className="flex justify-between gap-2">
                  <span className="text-muted-foreground shrink-0">タグ</span>
                  <div className="flex gap-1 flex-wrap justify-end">
                    {record.tags.map((t) => (
                      <Badge key={t} variant="outline" className="text-xs">
                        {t}
                      </Badge>
                    ))}
                  </div>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* 条件 */}
        {conditions.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                条件 ({conditions.length})
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1.5 text-sm">
              {conditions.map(([key, value]) => {
                const unit = record.condition_units?.[key];
                return (
                  <div
                    key={key}
                    className="flex justify-between gap-2 border-b last:border-0 pb-1"
                  >
                    <span className="font-mono text-xs text-muted-foreground">
                      {key}
                    </span>
                    <span className="font-mono text-xs">
                      {String(value)}
                      {unit && (
                        <span className="text-muted-foreground ml-1">
                          {unit}
                        </span>
                      )}
                    </span>
                  </div>
                );
              })}
            </CardContent>
          </Card>
        )}

        {/* 結果 */}
        {results.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                結果 ({results.length})
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1.5 text-sm">
              {results.map(([key, value]) => {
                const unit = record.result_units?.[key];
                return (
                  <div
                    key={key}
                    className="flex justify-between gap-2 border-b last:border-0 pb-1"
                  >
                    <span className="font-mono text-xs text-muted-foreground">
                      {key}
                    </span>
                    <span className="font-mono text-xs">
                      {typeof value === "object"
                        ? JSON.stringify(value)
                        : String(value)}
                      {unit && (
                        <span className="text-muted-foreground ml-1">
                          {unit}
                        </span>
                      )}
                    </span>
                  </div>
                );
              })}
            </CardContent>
          </Card>
        )}

        {/* ファイル一覧 + DL */}
        {record.files.length > 0 && (
          <Card className="md:col-span-2">
            <CardHeader>
              <CardTitle className="text-base">
                ファイル ({record.files.length})
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              {record.files.map((file) => (
                <div
                  key={file.name}
                  className="flex items-center justify-between gap-2 border-b last:border-0 pb-1.5"
                >
                  <span className="font-mono text-xs truncate">
                    {file.name}
                  </span>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-xs text-muted-foreground">
                      {file.size_bytes > 0 ? formatBytes(file.size_bytes) : "-"}
                    </span>
                    <SharedFileDownloadButton
                      token={token}
                      recordId={record.id}
                      team={scope.team}
                      filename={file.name}
                    />
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        )}

        {/* analyst のみ: ファイル upload フォーム */}
        {isAnalyst && (
          <AnalystUploadCard
            token={token}
            recordId={record.id}
            team={scope.team}
            onUploaded={(newRec) => setRecord(newRec)}
          />
        )}
      </div>

      <div className="text-center text-xs text-muted-foreground border-t pt-4">
        labvault — 外部共有 link 経由でアクセス中。
        子 record (解析結果の親) や複雑なファイル登録は SDK 経由で。
      </div>
    </div>
  );
}

// --- ファイル DL ボタン (token authed blob) -------------------------------

function SharedFileDownloadButton({
  token,
  recordId,
  team,
  filename,
}: {
  token: string;
  recordId: string;
  team: string;
  filename: string;
}) {
  const [busy, setBusy] = useState(false);
  const handleDownload = async () => {
    setBusy(true);
    try {
      const res = await shareTokenFetch(
        token,
        `${API_BASE}/api/records/${recordId}/files/${encodeURIComponent(filename)}?download=1`,
        { headers: { "X-Labvault-Team": team } },
      );
      if (!res.ok) throw new Error(`DL failed: ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      window.alert(
        `ダウンロードに失敗しました: ${(e as Error).message}`,
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <button
      type="button"
      onClick={handleDownload}
      disabled={busy}
      className="text-xs text-primary hover:underline cursor-pointer"
    >
      {busy ? "DL中..." : "DL"}
    </button>
  );
}

// --- analyst: 単一ファイル upload ----------------------------------------

function AnalystUploadCard({
  token,
  recordId,
  team,
  onUploaded,
}: {
  token: string;
  recordId: string;
  team: string;
  onUploaded: (rec: RecordDetail) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await shareTokenFetch(
        token,
        `${API_BASE}/api/records/${recordId}/files`,
        { method: "POST", headers: { "X-Labvault-Team": team }, body: fd },
      );
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`upload failed: ${res.status} ${text}`);
      }
      const rec = (await res.json()) as RecordDetail;
      onUploaded(rec);
      setMsg(`upload 完了: ${file.name}`);
      setFile(null);
      // input をリセット
      (e.target as HTMLFormElement).reset();
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="md:col-span-2 border-amber-300 bg-amber-50/30">
      <CardHeader>
        <CardTitle className="text-base">解析結果ファイルを送る</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleUpload} className="space-y-2">
          <input
            type="file"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            disabled={busy}
            className="block w-full text-xs file:mr-3 file:rounded-md file:border file:border-input file:bg-background file:px-3 file:py-1.5 file:text-xs file:font-medium file:cursor-pointer cursor-pointer"
          />
          <div className="flex items-center gap-2 flex-wrap">
            <Button type="submit" size="sm" disabled={busy || !file}>
              {busy ? "送信中..." : "upload"}
            </Button>
            <p className="text-xs text-muted-foreground">
              この record に解析結果として直接添付されます。子 record の
              作成は SDK ({" "}
              <code className="rounded bg-muted px-1 py-0.5">
                rec.sub(...)
              </code>
              ) で。
            </p>
          </div>
          {msg && (
            <p className="text-xs text-green-700 bg-green-50 px-2 py-1 rounded">
              {msg}
            </p>
          )}
          {err && (
            <p className="text-xs text-destructive bg-destructive/10 px-2 py-1 rounded">
              {err}
            </p>
          )}
        </form>
      </CardContent>
    </Card>
  );
}
