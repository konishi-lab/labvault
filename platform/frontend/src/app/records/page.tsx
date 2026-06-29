"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { SortableRecordTable } from "@/components/sortable-record-table";
import { SearchBar } from "@/components/search-bar";
import {
  ConditionFilterPanel,
  type ConditionFilter,
} from "@/components/condition-filter";
import {
  fetchIndexedFieldSuggestions,
  fetchRecords,
  fetchSharedWithMe,
  searchRecords,
} from "@/lib/api";
import type { RecordSummary, SharedRecordSummary } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { StatsPanel } from "@/components/stats-panel";
import { SharedRecordsList } from "@/components/shared-records-list";

const PAGE_LIMIT = 200;

function _parseFilters(raw: string | null): ConditionFilter[] {
  if (!raw) return [];
  try {
    const obj = JSON.parse(raw) as Record<string, unknown>;
    return Object.entries(obj).map(([key, value]) => ({
      key,
      value: String(value),
    }));
  } catch {
    return [];
  }
}

function _serializeFilters(filters: ConditionFilter[]): string {
  if (filters.length === 0) return "";
  const obj: Record<string, string> = {};
  for (const f of filters) {
    obj[f.key] = f.value;
  }
  return JSON.stringify(obj);
}

// Next.js 16 の docs 推奨パターン: filter UI のような「同じ page で
// 検索パラメータだけ変える」操作は `router.push` ではなく
// `window.history.pushState` を使う。`router.push` は production で
// 「同じ pathname なら navigation を dedupe」する挙動を持ち、
// useSearchParams の更新が走らないケースがある (`/records?mine=1` →
// `/records` で button 状態が解除されない bug の真因と推定)。
// `pushState` は Next.js Router と統合されているので、
// useSearchParams / usePathname の購読側にも反映される。
//
// 空クエリのときは `?` を落とす (`/records?` のような trailing `?` 付き
// URL も同様に navigation dedupe を踏みやすい)。
function _updateRecordsUrl(params: URLSearchParams) {
  const qs = params.toString();
  const url = qs ? `/records?${qs}` : "/records";
  if (typeof window !== "undefined") {
    window.history.pushState(null, "", url);
  }
}

function RecordsContent() {
  const searchParams = useSearchParams();
  const query = searchParams.get("q") || "";
  const rawConditions = searchParams.get("conditions");
  const mineOnly = searchParams.get("mine") === "1";
  // D3: 「自分のみ」+ 暗黙ソートの二重を解消。
  //   - mineOnly=1: backend で自分の record のみに絞り込み (旧仕様)
  //   - boost=1: 全員出すが「自分の record を上に並べる」(明示トグル)
  //   - 両方なし: 完全フラット (作成日順)
  // 旧仕様 (mine=1 のみ) で来たユーザーには backward-compat で同じ挙動。
  const boostMine = searchParams.get("boost") === "1";
  // S1 Phase 1B: 「他チームから共有された record」モード。shared=1 のとき
  // 通常の /api/records ではなく /api/records/shared-with-me を叩いて
  // cross-team で「自分宛て共有」だけを表示する。mine / boost / template
  // / conditions / query は無視 (backend が条件 filter を受けない)。
  const sharedMode = searchParams.get("shared") === "1";
  const templateFilter = searchParams.get("template") || "";

  const { user } = useAuth();
  const currentUserEmail = user?.email || null;

  const [records, setRecords] = useState<RecordSummary[]>([]);
  const [sharedRecords, setSharedRecords] = useState<SharedRecordSummary[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [keySuggestions, setKeySuggestions] = useState<string[]>([]);

  // 条件 chip の key 候補 (template の indexed_fields union)。team が変わら
  // ないうちは 1 度だけ取得すれば良い。失敗時は空配列のまま (自由入力で動く)。
  useEffect(() => {
    let cancelled = false;
    fetchIndexedFieldSuggestions().then((suggestions) => {
      if (!cancelled) setKeySuggestions(suggestions);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const filters = useMemo(() => _parseFilters(rawConditions), [rawConditions]);
  const conditionsObj = useMemo<Record<string, unknown>>(() => {
    const obj: Record<string, string> = {};
    for (const f of filters) {
      obj[f.key] = f.value;
    }
    return obj;
  }, [filters]);

  const handleFiltersChange = useCallback(
    (next: ConditionFilter[]) => {
      const params = new URLSearchParams(searchParams.toString());
      const serialized = _serializeFilters(next);
      if (serialized) {
        params.set("conditions", serialized);
      } else {
        params.delete("conditions");
      }
      // window.history.pushState は Next.js Router と統合され、戻る
      // ボタンでも前の filter 状態に戻れる (#16 quick win)。chip の
      // 追加/削除/トグルは確定アクションなので 1 操作 = 1 history
      // entry の方が自然。
      _updateRecordsUrl(params);
    },
    [searchParams],
  );

  // D3 + S1 Phase 1B: 4 値セグメント [全員] [自分を上に] [自分のみ]
  // [共有された]。URL の bool を組み合わせる (互換性のため):
  //   "all"     → mine 削除 / boost 削除 / shared 削除
  //   "boost"   → boost=1 / mine 削除 / shared 削除
  //   "mine"    → mine=1 / boost 削除 / shared 削除
  //   "shared"  → shared=1 / mine 削除 / boost 削除
  type ListMode = "all" | "boost" | "mine" | "shared";
  const listMode: ListMode = sharedMode
    ? "shared"
    : mineOnly
      ? "mine"
      : boostMine
        ? "boost"
        : "all";
  const handleListModeChange = useCallback(
    (next: ListMode) => {
      const params = new URLSearchParams(searchParams.toString());
      params.delete("mine");
      params.delete("boost");
      params.delete("shared");
      if (next === "mine") params.set("mine", "1");
      if (next === "boost") params.set("boost", "1");
      if (next === "shared") params.set("shared", "1");
      _updateRecordsUrl(params);
    },
    [searchParams],
  );

  useEffect(() => {
    setLoading(true);
    setError(null);

    // S1 Phase 1B: shared mode は cross-team で別 endpoint を叩く。
    // query / conditions / mine / template は backend が受けないので無視。
    if (sharedMode) {
      fetchSharedWithMe({ limit: PAGE_LIMIT })
        .then((res) => {
          setSharedRecords(res.items);
          setRecords([]);
          setHasMore(!!res.has_more);
        })
        .catch((err: Error) => setError(err.message))
        .finally(() => setLoading(false));
      return;
    }

    // query / conditions / created_by を **同時に** 受け付ける統一ロード経路。
    // backend は /api/search が q + conditions + created_by を全部受ける
    // (search.py)。query が空なら /api/records 経由で同じ filter を渡す。
    const hasConditions = Object.keys(conditionsObj).length > 0;
    const createdBy = mineOnly && currentUserEmail ? currentUserEmail : undefined;

    const load = query
      ? searchRecords(query, {
          conditions: hasConditions ? conditionsObj : undefined,
          createdBy,
          template: templateFilter || undefined,
          limit: PAGE_LIMIT,
        }).then((items) => ({ items, has_more: items.length >= PAGE_LIMIT }))
      : fetchRecords({
          limit: PAGE_LIMIT,
          conditions: hasConditions ? conditionsObj : undefined,
          createdBy,
          template: templateFilter || undefined,
        }).then((res) => ({
          items: res.items,
          has_more: !!res.has_more,
        }));

    load
      .then(({ items, has_more }) => {
        setRecords(items);
        setSharedRecords([]);
        setHasMore(has_more);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [
    query,
    conditionsObj,
    mineOnly,
    sharedMode,
    currentUserEmail,
    templateFilter,
  ]);

  // D3: 「自分を上に」は `boost=1` で **明示** トグルされた時のみ。
  // 旧仕様の暗黙ソートは「なぜ俺の record が上にあるんだ」の問い合わせ
  // 原因だったので廃止。`mine=1` は backend で絞り込み済なので no-op。
  const orderedRecords = useMemo(() => {
    if (!boostMine || !currentUserEmail || mineOnly) return records;
    const mine: RecordSummary[] = [];
    const others: RecordSummary[] = [];
    for (const r of records) {
      if (r.created_by === currentUserEmail) {
        mine.push(r);
      } else {
        others.push(r);
      }
    }
    return [...mine, ...others];
  }, [records, currentUserEmail, mineOnly, boostMine]);

  if (error) {
    return <p className="py-8 text-center text-destructive">エラー: {error}</p>;
  }

  const handleClearTemplate = () => {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("template");
    _updateRecordsUrl(params);
  };

  return (
    <div className="space-y-4">
      {/* フィルタバー: D3 + S1 セグメント + template chip + condition chip */}
      <div className="flex items-center gap-2 flex-wrap">
        <ListModeSegment
          mode={listMode}
          onChange={handleListModeChange}
          disabled={!currentUserEmail}
        />
        {!sharedMode && templateFilter && (
          <Button
            size="sm"
            variant="outline"
            onClick={handleClearTemplate}
            title={`template "${templateFilter}" でフィルタ中 (クリックで解除)`}
            className="gap-1"
          >
            <span aria-hidden>📎</span>template: {templateFilter} ×
          </Button>
        )}
        {/* condition chip は shared mode では無効化 (backend が受けない) */}
        {!sharedMode && (
          <ConditionFilterPanel
            filters={filters}
            onChange={handleFiltersChange}
            keySuggestions={keySuggestions}
          />
        )}
      </div>

      {sharedMode ? (
        // S1 Phase 1B: 共有された record の一覧 (cross-team)。
        loading ? (
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : (
          <SharedRecordsList items={sharedRecords} hasMore={hasMore} />
        )
      ) : (
        <>
          {/* 件数ヘッダ */}
          {!loading && (
            <div className="text-xs text-muted-foreground px-1">
              {orderedRecords.length === 0 ? (
                "該当なし"
              ) : hasMore ? (
                <>
                  {orderedRecords.length}+ 件以上ヒット (
                  <strong>条件を絞り込んでください</strong>)
                </>
              ) : (
                <>{orderedRecords.length} 件表示中</>
              )}
              {boostMine && currentUserEmail && orderedRecords.length > 0 && (
                <span className="ml-2">· 自分の record を上に表示中</span>
              )}
            </div>
          )}

          {/* 数値サマリ panel (戦略案 #6 Phase A)。「現フィルタにマッチする
              全集合 (上限 500) の n / mean / std / min / max / median」を
              backend で計算して出す。frontend 集計だと「表示中 200 件で
              打ち切った窓の統計」になってしまうのを構造的に防ぐ。 */}
          <StatsPanel
            filters={{
              query,
              conditions:
                Object.keys(conditionsObj).length > 0 ? conditionsObj : undefined,
              createdBy:
                mineOnly && currentUserEmail ? currentUserEmail : undefined,
              template: templateFilter || undefined,
            }}
            keySuggestions={keySuggestions}
          />

          {loading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : (
            <SortableRecordTable
              records={orderedRecords}
              defaultSort="created_at"
              currentUserEmail={currentUserEmail}
            />
          )}
        </>
      )}
    </div>
  );
}

// D3 + S1 Phase 1B: [全員] [自分を上に] [自分のみ] [共有された] の
// 4 値セグメントコントロール。
// - D3 (PR #81): 暗黙ソートを廃止し「自分を上に」を明示トグル化。
// - S1 (本 PR): 「共有された」を追加し、cross-team の shared-with-me
//   経由のリスト表示に切り替える。conditions / template / mine は
//   shared mode では無視される (backend が受けない)。
function ListModeSegment({
  mode,
  onChange,
  disabled,
}: {
  mode: "all" | "boost" | "mine" | "shared";
  onChange: (m: "all" | "boost" | "mine" | "shared") => void;
  disabled?: boolean;
}) {
  const opts: Array<{
    value: "all" | "boost" | "mine" | "shared";
    label: string;
    title: string;
  }> = [
    { value: "all", label: "全員", title: "現 team の全 record をフラットに表示" },
    {
      value: "boost",
      label: "自分を上に",
      title:
        "現 team の全 record を出すが、自分が作った record を先頭に並べる",
    },
    {
      value: "mine",
      label: "自分のみ",
      title: "現 team で自分が作った record だけ表示",
    },
    {
      value: "shared",
      label: "共有された",
      title:
        "別 team から自分宛てに share された record (cross-team)。フィルタや条件は無視される",
    },
  ];
  return (
    <div
      className="inline-flex items-center rounded-md border border-input p-0.5 bg-background text-xs"
      role="radiogroup"
      aria-label="表示モード"
    >
      {opts.map((o) => {
        const active = mode === o.value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={disabled}
            onClick={() => onChange(o.value)}
            title={
              disabled
                ? "ログイン情報を取得中"
                : o.title
            }
            className={
              "px-2.5 py-1 rounded-sm transition-colors cursor-pointer " +
              (active
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground hover:bg-muted") +
              (disabled ? " opacity-50 cursor-not-allowed" : "")
            }
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export default function HomePage() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">レコード</h1>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base font-medium">実験一覧</CardTitle>
            <Suspense>
              <SearchBar />
            </Suspense>
          </div>
        </CardHeader>
        <CardContent>
          <Suspense>
            <RecordsContent />
          </Suspense>
        </CardContent>
      </Card>
    </div>
  );
}
