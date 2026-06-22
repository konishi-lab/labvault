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
import { fetchAggregate, type AggregateResponse } from "@/lib/api";

/**
 * 戦略案 #6 Phase A: `/records` の現フィルタ集合に対する数値統計 panel。
 *
 * 表示中の 200 件でなく、backend で「フィルタにマッチする全集合 (上限
 * 500 件)」を走査して n / mean / min / max / median を出す。
 *
 *   ── 嘘グラフ回避の肝 ──
 * SortableRecordTable は表示中の 200 件しか持っていない。それを
 * frontend で集計すると「200 件で打ち切った窓の統計」になり、
 * 解析者が「全体傾向」と誤解する。Phase A の存在価値はこの誤解を
 * 構造的に防ぐこと。`truncated=true` 時は明示的にバッジで警告する。
 *
 * キー入力は手動 (textbox)。後の Phase で suggest を拡充する想定。
 */

const KEY_STORAGE_KEY = "labvault.records.stats.keys.v1";

function loadKeys(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((k) => typeof k === "string") : [];
  } catch {
    return [];
  }
}

function saveKeys(keys: string[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY_STORAGE_KEY, JSON.stringify(keys));
  } catch {
    // localStorage 不可 (private モード等) は無視
  }
}

function formatNumber(n: number): string {
  if (!Number.isFinite(n)) return "-";
  const abs = Math.abs(n);
  if (abs !== 0 && (abs < 0.001 || abs >= 100000)) return n.toExponential(3);
  // 整数値は小数を出さない、それ以外は最大 4 桁
  return Number.isInteger(n) ? n.toString() : n.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
}

interface StatsPanelProps {
  // /records と同じフィルタ。空オブジェクトでも可。
  filters: {
    query?: string;
    conditions?: Record<string, unknown>;
    createdBy?: string;
    template?: string;
    parentId?: string;
  };
  keySuggestions?: string[];
}

function StatsRow({
  agg,
  onRemove,
}: {
  agg: AggregateResponse | { error: string; key: string };
  onRemove: () => void;
}) {
  if ("error" in agg) {
    return (
      <div className="grid grid-cols-[auto_1fr_auto] items-center gap-3 px-3 py-2 border-b border-border/40 last:border-b-0">
        <span className="font-mono text-sm">{agg.key}</span>
        <span className="text-xs text-destructive">エラー: {agg.error}</span>
        <button
          type="button"
          onClick={onRemove}
          className="text-xs text-muted-foreground hover:text-foreground cursor-pointer"
          title="この行を削除"
        >
          ×
        </button>
      </div>
    );
  }

  const { key, record_count, value_count, stats, truncated } = agg;
  const hasValues = stats.count > 0;
  // truncated = backend が 500 件で打ち切った状態。「数字だけ読まれる」
  // 罠を避けるため、stats 自体を灰色化して「サンプル」の見た目に落とす
  // (記号は出すが、確定値として使えないことを視覚的に表す)。
  const numbersClass = truncated
    ? "text-muted-foreground/70"
    : "";

  return (
    <div className="grid grid-cols-[auto_1fr_auto] items-center gap-3 px-3 py-2 border-b border-border/40 last:border-b-0">
      <div className="flex items-center gap-2 min-w-0">
        <span className="font-mono text-sm font-medium">{key}</span>
        {truncated && (
          <Badge
            variant="outline"
            className="text-[10px] border-amber-300 text-amber-800 bg-amber-50"
            title="フィルタにヒットする record が 500 件を超えたため、最初の 500 件 (= 作成日新しい順) のみで集計しました。確定値ではなく標本値として扱ってください。"
          >
            ⚠ 500 件サンプル
          </Badge>
        )}
      </div>
      {hasValues ? (
        <div
          className={`grid grid-cols-6 gap-3 text-xs tabular-nums ${numbersClass}`}
        >
          <span>
            <span className="text-muted-foreground">n </span>
            {stats.count}
            {value_count !== record_count && (
              <span
                className="text-muted-foreground"
                title={`${record_count} 件中 ${value_count} 件が数値`}
              >
                /{record_count}
              </span>
            )}
          </span>
          <span>
            <span className="text-muted-foreground">mean </span>
            {formatNumber(stats.mean)}
          </span>
          <span>
            <span className="text-muted-foreground">std </span>
            {formatNumber(stats.std)}
          </span>
          <span>
            <span className="text-muted-foreground">min </span>
            {formatNumber(stats.min)}
          </span>
          <span>
            <span className="text-muted-foreground">max </span>
            {formatNumber(stats.max)}
          </span>
          <span>
            <span className="text-muted-foreground">median </span>
            {formatNumber(stats.median)}
          </span>
        </div>
      ) : (
        <span className="text-xs text-muted-foreground">
          {record_count} 件中、数値として読める {key} はありませんでした
        </span>
      )}
      <button
        type="button"
        onClick={onRemove}
        className="text-xs text-muted-foreground hover:text-foreground cursor-pointer"
        title="この行を削除"
      >
        ×
      </button>
    </div>
  );
}

export function StatsPanel({ filters, keySuggestions = [] }: StatsPanelProps) {
  // parent_id 未指定 = backend が parent_id=None で root のみ走査する。
  // 「power の全実験統計」を期待するユーザーへ仕様を明示するため header
  // に注釈を出す。明示的に parent_id を渡してきた呼び出し側 (将来の親
  // record 詳細ページ等) では出さない。
  const isRootOnly = !filters.parentId;
  const [keys, setKeys] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [results, setResults] = useState<
    Record<string, AggregateResponse | { error: string; key: string }>
  >({});
  const [loading, setLoading] = useState<Set<string>>(new Set());

  // 初回 mount で localStorage から復元 (ユーザーがよく見るキーは記憶される)。
  useEffect(() => {
    setKeys(loadKeys());
  }, []);

  // keys が変わったら永続化。
  useEffect(() => {
    saveKeys(keys);
  }, [keys]);

  // フィルタが変わるたび、全 keys を再計算。
  useEffect(() => {
    if (keys.length === 0) {
      setResults({});
      return;
    }
    let cancelled = false;
    const next = new Set(keys);
    setLoading(next);
    Promise.all(
      keys.map(async (key) => {
        try {
          const res = await fetchAggregate(key, filters);
          return { key, value: res };
        } catch (e) {
          return {
            key,
            value: { key, error: e instanceof Error ? e.message : "failed" },
          };
        }
      }),
    ).then((entries) => {
      if (cancelled) return;
      const obj: Record<string, AggregateResponse | { error: string; key: string }> = {};
      for (const { key, value } of entries) obj[key] = value;
      setResults(obj);
      setLoading(new Set());
    });
    return () => {
      cancelled = true;
    };
    // filters は呼び出し側で memoize されている想定 (オブジェクト同値性に頼る)。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keys, JSON.stringify(filters)]);

  const addKey = (k: string) => {
    const trimmed = k.trim();
    if (!trimmed || keys.includes(trimmed)) return;
    setKeys([...keys, trimmed]);
    setDraft("");
  };

  const removeKey = (k: string) => {
    setKeys(keys.filter((x) => x !== k));
    setResults((prev) => {
      const { [k]: _, ...rest } = prev;
      void _;
      return rest;
    });
  };

  // suggest は「まだ追加されていない indexed_fields」のみ。
  const availableSuggestions = keySuggestions.filter((s) => !keys.includes(s));

  return (
    <Card className="border-slate-200">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium flex items-center gap-2 flex-wrap">
          数値サマリ
          <span
            className="text-xs font-normal text-muted-foreground"
            title="表示中の 200 件でなく、フィルタにマッチする全集合 (上限 500) の統計"
          >
            (フィルタ全集合, 上限 500)
          </span>
          {isRootOnly && (
            <span
              className="text-xs font-normal text-muted-foreground"
              title="/records 一覧はルートレコードのみ表示しているため、子レコードの値は集計に含まれません。子も含めて見るには 親 record 詳細ページ (将来の Phase) または CLI `labvault aggregate` を使う必要があります。"
            >
              · ルートレコードのみ
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <input
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addKey(draft);
              }
            }}
            placeholder="数値キーを追加 (例: power, lattice_a_A)"
            className="text-xs border rounded px-2 py-1 w-64 bg-background"
            list="stats-key-suggestions"
          />
          <datalist id="stats-key-suggestions">
            {availableSuggestions.map((s) => (
              <option key={s} value={s} />
            ))}
          </datalist>
          {availableSuggestions.slice(0, 6).map((s) => (
            <Badge
              key={s}
              variant="outline"
              onClick={() => addKey(s)}
              className="text-xs cursor-pointer hover:bg-slate-50"
              title={`${s} を追加`}
            >
              + {s}
            </Badge>
          ))}
        </div>
        {keys.length === 0 ? (
          <p className="text-xs text-muted-foreground px-1 py-2">
            キーを追加すると、現在のフィルタにマッチする全 record の統計
            (n / mean / std / min / max / median) を表示します。
          </p>
        ) : (
          <div className="rounded-md border border-border/40 divide-y-0">
            {keys.map((k) => {
              const r = results[k];
              if (loading.has(k) && !r) {
                return (
                  <div
                    key={k}
                    className="grid grid-cols-[auto_1fr_auto] items-center gap-3 px-3 py-2 border-b border-border/40 last:border-b-0"
                  >
                    <span className="font-mono text-sm">{k}</span>
                    <Skeleton className="h-3 w-full" />
                    <span className="text-xs text-muted-foreground">…</span>
                  </div>
                );
              }
              if (!r) return null;
              return <StatsRow key={k} agg={r} onRemove={() => removeKey(k)} />;
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
