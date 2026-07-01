"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchCellLogs, type CellLogEntry } from "@/lib/api";

/**
 * 戦略案 #6 → 戦略 B1: CellLog (R13) Web 露出。
 *
 * IPython hooks (`CellTracker`) が pre/post_run_cell で自動収集した
 * Notebook セル実行ログを時系列 (cell_number 昇順) で表示する。
 * 各セルはデフォルト折り畳み、クリックで source / new_vars / error を展開。
 *
 * 比較資料での最大差別化軸が「LLM が Notebook 履歴を辿る」だが、これまで
 * Web/MCP どちらにも露出が無く実質死蔵だった (Roadmap レビュー指摘)。
 * 本コンポーネント + MCP `get_notebook_log` で初めて消費経路が成立する。
 */

function formatDuration(sec: number): string {
  if (sec < 0.001) return "<1ms";
  if (sec < 1) return `${Math.round(sec * 1000)}ms`;
  if (sec < 60) return `${sec.toFixed(2)}s`;
  return `${Math.round(sec / 60)}m${Math.round(sec % 60)}s`;
}

function formatDateTime(iso: string | null): string {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString("ja-JP");
  } catch {
    return iso;
  }
}

function VarBadge({
  name,
  digest,
  kind,
}: {
  name: string;
  digest: unknown;
  kind: "new" | "changed";
}) {
  // digest は dict (type/shape/hash 等) or scalar。`type` キーがあれば
  // それを優先、なければ JSON 圧縮形を tooltip に。
  const d =
    digest && typeof digest === "object" && !Array.isArray(digest)
      ? (digest as Record<string, unknown>)
      : null;
  const typeStr = d?.type ? String(d.type) : "";
  const shapeStr = d?.shape ? ` ${JSON.stringify(d.shape)}` : "";
  const subtitle = typeStr ? `${typeStr}${shapeStr}` : "";
  const color =
    kind === "new"
      ? "border-emerald-200 bg-emerald-50 text-emerald-800"
      : "border-amber-200 bg-amber-50 text-amber-800";
  return (
    <Badge
      variant="outline"
      className={`text-[10px] ${color}`}
      title={JSON.stringify(digest)}
    >
      {kind === "new" ? "+ " : "Δ "}
      <span className="font-mono">{name}</span>
      {subtitle && <span className="ml-1 opacity-70">{subtitle}</span>}
    </Badge>
  );
}

function CellRow({ entry }: { entry: CellLogEntry }) {
  const [open, setOpen] = useState(false);
  const hasError = !!entry.error;
  const newVars = Object.entries(entry.new_vars);
  const changedVars = Object.entries(entry.changed_vars);
  const sourceLines = entry.source.split("\n");
  const firstLine = sourceLines[0]?.trim() || "(empty cell)";

  return (
    <div className="border-b border-border/40 last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full text-left px-3 py-2 hover:bg-muted/30 cursor-pointer flex items-center gap-3"
      >
        <span className="text-xs text-muted-foreground font-mono tabular-nums shrink-0 w-12">
          #{entry.cell_number}
          {entry.execution_count > 0 && (
            <span className="opacity-50"> [{entry.execution_count}]</span>
          )}
        </span>
        <code className="text-xs font-mono truncate flex-1 text-foreground/80">
          {firstLine}
          {sourceLines.length > 1 && (
            <span className="text-muted-foreground"> …</span>
          )}
        </code>
        <span className="text-[10px] text-muted-foreground shrink-0">
          {formatDuration(entry.duration_sec)}
        </span>
        {hasError && (
          <Badge
            variant="outline"
            className="text-[10px] border-red-300 text-red-800 bg-red-50 shrink-0"
            title={entry.error?.message}
          >
            ⚠ {entry.error?.type}
          </Badge>
        )}
        {(newVars.length > 0 || changedVars.length > 0) && (
          <span className="text-[10px] text-muted-foreground shrink-0 tabular-nums">
            {newVars.length > 0 && <>+{newVars.length}</>}
            {changedVars.length > 0 && <> Δ{changedVars.length}</>}
          </span>
        )}
        <span className="text-xs text-muted-foreground shrink-0">
          {open ? "▼" : "▶"}
        </span>
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-2 bg-muted/10">
          {/* source */}
          <pre className="text-xs font-mono bg-background border border-border/40 rounded p-2 overflow-x-auto whitespace-pre">
            {entry.source}
          </pre>
          {/* timestamp + session */}
          <div className="text-[10px] text-muted-foreground space-x-3">
            <span>{formatDateTime(entry.executed_at)}</span>
            {entry.session_id && (
              <span title={entry.session_id}>
                session: {entry.session_id.slice(0, 16)}
                {entry.session_id.length > 16 && "…"}
              </span>
            )}
          </div>
          {/* error detail */}
          {hasError && (
            <div className="text-xs bg-red-50 border border-red-200 rounded p-2 font-mono text-red-900 whitespace-pre-wrap">
              {entry.error?.type}: {entry.error?.message}
            </div>
          )}
          {/* vars */}
          {(newVars.length > 0 ||
            changedVars.length > 0 ||
            entry.deleted_vars.length > 0) && (
            <div className="flex flex-wrap gap-1">
              {newVars.map(([name, digest]) => (
                <VarBadge key={`n-${name}`} name={name} digest={digest} kind="new" />
              ))}
              {changedVars.map(([name, digest]) => (
                <VarBadge
                  key={`c-${name}`}
                  name={name}
                  digest={digest}
                  kind="changed"
                />
              ))}
              {entry.deleted_vars.map((name) => (
                <Badge
                  key={`d-${name}`}
                  variant="outline"
                  className="text-[10px] border-slate-300 text-slate-600 line-through"
                >
                  − <span className="font-mono">{name}</span>
                </Badge>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function CellLogSection({
  recordId,
  anchorId,
}: {
  recordId: string;
  anchorId?: string;
}) {
  const [entries, setEntries] = useState<CellLogEntry[] | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // 2026-07-01: セクション全体をデフォルト折り畳み。record 詳細画面は他の
  // カード (conditions / results / files / cell logs) が縦に長く伸びがちで、
  // Notebook 由来の record では特に cell log セクションだけで 50+ 行になる。
  // 「一覧するときは基本閉じておいて、必要になったら開く」に統一。
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setLoading(true);
    fetchCellLogs(recordId, { limit: 200 })
      .then((res) => {
        setEntries(res.items);
        setHasMore(res.has_more);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [recordId]);

  // CellLog 0 件 ( = Notebook で作られた record ではない or hooks 未起動)
  // のときは Card 自体を出さない。条件カード等と同じ流儀で「未投入」表示
  // を増やすと装置 PC スクリプト由来の record で常時ノイズになる。
  if (!loading && !error && (entries === null || entries.length === 0)) {
    return null;
  }

  const count = entries?.length ?? 0;
  const errorCount = entries?.filter((e) => e.error).length ?? 0;

  return (
    <Card id={anchorId} className="md:col-span-2 scroll-mt-20">
      <CardHeader className="p-0">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="w-full text-left px-6 py-4 hover:bg-muted/30 cursor-pointer flex items-center gap-2"
          aria-expanded={open}
        >
          <CardTitle className="text-base flex items-center gap-2 flex-1">
            Notebook セルログ
            {entries && (
              <span className="text-xs font-normal text-muted-foreground">
                ({count}
                {hasMore && "+"}
                {errorCount > 0 && (
                  <span className="text-red-700"> · ⚠ {errorCount}</span>
                )}
                )
              </span>
            )}
            <span
              className="text-xs font-normal text-muted-foreground"
              title="IPython hooks が pre/post_run_cell で自動記録したセル実行履歴。LLM が Notebook で何をやったか辿るための差別化資産 (R13)"
            >
              · 自動記録
            </span>
          </CardTitle>
          <span className="text-xs text-muted-foreground shrink-0">
            {open ? "▼" : "▶"}
          </span>
        </button>
      </CardHeader>
      {open && (
        <CardContent className="p-0">
          {loading && (
            <div className="p-3 space-y-2">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-6 w-full" />
              ))}
            </div>
          )}
          {error && (
            <p className="px-3 py-2 text-xs text-destructive">
              ログの取得に失敗しました: {error}
            </p>
          )}
          {!loading && !error && entries && (
            <div className="divide-y-0 border-t border-border/40">
              {entries.map((e) => (
                <CellRow key={e.cell_id} entry={e} />
              ))}
              {hasMore && (
                <div className="px-3 py-2 text-[10px] text-amber-700 bg-amber-50 border-t border-amber-200">
                  ⚠ 表示上限 (200 件) に達しました。それ以降のセルログは
                  MCP `get_notebook_log` または SDK `record.cell_logs()`
                  から `limit` を上げて取得してください。
                </div>
              )}
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}
