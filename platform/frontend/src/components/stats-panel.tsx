"use client";

import { useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  fetchAggregate,
  fetchTemplateRequiredResultKeys,
  type AggregateResponse,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";

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
 * D4 (PR #81): 初見ゼロ状態を埋める。
 * - template 紐付き record では、その template の `required_results`
 *   上位 3 件を初期 keys として自動投入 (ユーザーが 1 度も触っていない
 *   `touched=false` の間のみ)。
 * - template 紐付き無しでは、`keySuggestions` 上位 3 件を **「お試し」**
 *   として読み取り表示する (右端にピン留めボタン)。ピン留めで keys に
 *   昇格 + 永続化。
 *
 * D4 副次: localStorage の team-prefix 化。team を切り替えても他 team
 * のキーが残らないように。
 */

const PREVIEW_COUNT = 3;

// D4: team 単位で localStorage を分離する。team 不明な間は読み書きを skip。
function _keysKey(team: string): string {
  return `labvault.${team}.records.stats.keys.v2`;
}
function _touchedKey(team: string): string {
  return `labvault.${team}.records.stats.user_touched.v2`;
}

function loadKeys(team: string): string[] {
  if (typeof window === "undefined" || !team) return [];
  try {
    const raw = window.localStorage.getItem(_keysKey(team));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((k) => typeof k === "string") : [];
  } catch {
    return [];
  }
}

function saveKeys(team: string, keys: string[]) {
  if (typeof window === "undefined" || !team) return;
  try {
    window.localStorage.setItem(_keysKey(team), JSON.stringify(keys));
  } catch {
    /* localStorage 不可 (private モード等) は無視 */
  }
}

function loadTouched(team: string): boolean {
  if (typeof window === "undefined" || !team) return false;
  try {
    return window.localStorage.getItem(_touchedKey(team)) === "1";
  } catch {
    return false;
  }
}

function saveTouched(team: string) {
  if (typeof window === "undefined" || !team) return;
  try {
    window.localStorage.setItem(_touchedKey(team), "1");
  } catch {
    /* ignore */
  }
}

function formatNumber(n: number): string {
  if (!Number.isFinite(n)) return "-";
  const abs = Math.abs(n);
  if (abs !== 0 && (abs < 0.001 || abs >= 100000)) return n.toExponential(3);
  return Number.isInteger(n) ? n.toString() : n.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
}

interface StatsPanelProps {
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
  rightSlot,
  numbersClassOverride,
}: {
  agg: AggregateResponse | { error: string; key: string };
  rightSlot: React.ReactNode;
  numbersClassOverride?: string;
}) {
  if ("error" in agg) {
    return (
      <div className="grid grid-cols-[auto_1fr_auto] items-center gap-3 px-3 py-2 border-b border-border/40 last:border-b-0">
        <span className="font-mono text-sm">{agg.key}</span>
        <span className="text-xs text-destructive">エラー: {agg.error}</span>
        {rightSlot}
      </div>
    );
  }

  const { key, record_count, value_count, stats, truncated } = agg;
  const hasValues = stats.count > 0;
  // truncated = backend が 500 件で打ち切った状態。「数字だけ読まれる」
  // 罠を避けるため、stats 自体を灰色化して「サンプル」の見た目に落とす。
  const numbersClass = numbersClassOverride
    ? numbersClassOverride
    : truncated
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
        <div className={`grid grid-cols-6 gap-3 text-xs tabular-nums ${numbersClass}`}>
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
      {rightSlot}
    </div>
  );
}

export function StatsPanel({ filters, keySuggestions = [] }: StatsPanelProps) {
  const { currentTeam } = useAuth();
  const team = currentTeam ?? "";

  const isRootOnly = !filters.parentId;

  const [keys, setKeys] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  // localStorage / template の初期投入が完了したかどうか。team / template
  // が決まるまでは fetch を走らせない (ちらつき防止)。
  const [initialized, setInitialized] = useState(false);
  const [results, setResults] = useState<
    Record<string, AggregateResponse | { error: string; key: string }>
  >({});
  const [loadingKeys, setLoadingKeys] = useState<Set<string>>(new Set());

  // 初期化: team と templateName が揃った時点で 1 度走る。
  // - touched=true: localStorage の保存 keys を採用
  // - touched=false かつ template 指定あり: その template の required_results
  //   上位 3 件を初期 keys にする (実利用例の素早い起動)
  // - touched=false かつ template 無し: 空 (お試し preview が代わりに表示される)
  useEffect(() => {
    if (!team) {
      // team 不明の間は何もしない
      return;
    }
    let cancelled = false;
    (async () => {
      const touched = loadTouched(team);
      if (touched) {
        if (!cancelled) {
          setKeys(loadKeys(team));
          setInitialized(true);
        }
        return;
      }
      if (filters.template) {
        const reqs = await fetchTemplateRequiredResultKeys(filters.template);
        if (cancelled) return;
        setKeys(reqs.slice(0, PREVIEW_COUNT));
        setInitialized(true);
        return;
      }
      // template も touched も無し: 空状態 (preview モード)
      if (!cancelled) {
        setKeys([]);
        setInitialized(true);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [team, filters.template]);

  // 「お試し」preview 用のキー (template 紐付き無し + keys 空 + touched 無し)
  const previewKeys = useMemo(() => {
    if (keys.length > 0) return [];
    if (filters.template) return []; // template 紐付き record 用には preview を出さない
    if (!loadTouched(team)) return keySuggestions.slice(0, PREVIEW_COUNT);
    return [];
  }, [keys.length, filters.template, keySuggestions, team]);

  // 表示中の全 key の aggregate を fetch。preview keys も同様に走らせる
  // (ピン留めしなくても結果が見える = 初見の存在意義)。
  const allKeys = useMemo(
    () => [...keys, ...previewKeys.filter((k) => !keys.includes(k))],
    [keys, previewKeys],
  );

  useEffect(() => {
    if (!initialized) return;
    if (allKeys.length === 0) {
      setResults({});
      return;
    }
    let cancelled = false;
    setLoadingKeys(new Set(allKeys));
    Promise.all(
      allKeys.map(async (key) => {
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
      setLoadingKeys(new Set());
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialized, allKeys.join("|"), JSON.stringify(filters)]);

  const markTouchedAndSave = (nextKeys: string[]) => {
    setKeys(nextKeys);
    if (team) {
      saveKeys(team, nextKeys);
      saveTouched(team);
    }
  };

  const addKey = (k: string) => {
    const trimmed = k.trim();
    if (!trimmed || keys.includes(trimmed)) return;
    markTouchedAndSave([...keys, trimmed]);
    setDraft("");
  };

  const removeKey = (k: string) => {
    markTouchedAndSave(keys.filter((x) => x !== k));
    setResults((prev) => {
      const { [k]: _drop, ...rest } = prev;
      void _drop;
      return rest;
    });
  };

  // suggest は「まだ追加されていない + preview に出ていない」
  const availableSuggestions = keySuggestions.filter(
    (s) => !keys.includes(s) && !previewKeys.includes(s),
  );

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

        {/* 結果テーブル: keys (永続) + previewKeys (お試し) を 1 つにまとめて並べる */}
        {!initialized ? (
          <div className="rounded-md border border-border/40 px-3 py-2">
            <Skeleton className="h-4 w-full" />
          </div>
        ) : allKeys.length === 0 ? (
          <p className="text-xs text-muted-foreground px-1 py-2">
            数値キーが見つかりませんでした。キー名を入力して追加してください。
          </p>
        ) : (
          <div className="rounded-md border border-border/40">
            {previewKeys.length > 0 && (
              <div className="px-3 py-1 text-[10px] uppercase tracking-wide text-muted-foreground bg-muted/30 border-b border-border/40">
                お試し (ピン留めで保存)
              </div>
            )}
            {previewKeys.map((k) => {
              const r = results[k];
              if (loadingKeys.has(k) && !r) {
                return (
                  <div
                    key={`preview-${k}`}
                    className="grid grid-cols-[auto_1fr_auto] items-center gap-3 px-3 py-2 border-b border-border/40 last:border-b-0"
                  >
                    <span className="font-mono text-sm">{k}</span>
                    <Skeleton className="h-3 w-full" />
                    <span className="text-xs text-muted-foreground">…</span>
                  </div>
                );
              }
              if (!r) return null;
              return (
                <StatsRow
                  key={`preview-${k}`}
                  agg={r}
                  numbersClassOverride="text-muted-foreground"
                  rightSlot={
                    <button
                      type="button"
                      onClick={() => addKey(k)}
                      className="text-[10px] text-primary hover:underline cursor-pointer"
                      title="このキーをピン留めして常時表示する"
                    >
                      📌 ピン留め
                    </button>
                  }
                />
              );
            })}
            {keys.length > 0 && previewKeys.length > 0 && (
              <div className="px-3 py-1 text-[10px] uppercase tracking-wide text-muted-foreground bg-muted/30 border-b border-border/40">
                ピン留め済
              </div>
            )}
            {keys.map((k) => {
              const r = results[k];
              if (loadingKeys.has(k) && !r) {
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
              return (
                <StatsRow
                  key={k}
                  agg={r}
                  rightSlot={
                    <button
                      type="button"
                      onClick={() => removeKey(k)}
                      className="text-xs text-muted-foreground hover:text-foreground cursor-pointer"
                      title="この行を削除"
                    >
                      ×
                    </button>
                  }
                />
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
