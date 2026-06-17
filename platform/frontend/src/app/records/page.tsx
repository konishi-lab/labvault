"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
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
  searchRecords,
} from "@/lib/api";
import type { RecordSummary } from "@/lib/api";
import { useAuth } from "@/lib/auth";

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

function RecordsContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const query = searchParams.get("q") || "";
  const rawConditions = searchParams.get("conditions");
  const mineOnly = searchParams.get("mine") === "1";
  const templateFilter = searchParams.get("template") || "";

  const { user } = useAuth();
  const currentUserEmail = user?.email || null;

  const [records, setRecords] = useState<RecordSummary[]>([]);
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
      // router.push にすることで戻るボタンで前の filter 状態に戻れる
// (#16 quick win)。chip の追加/削除/トグルは確定アクションなので
// 1 操作 = 1 history entry の方が自然。
router.push(`/records?${params.toString()}`);
    },
    [router, searchParams],
  );

  const handleMineToggle = useCallback(() => {
    const params = new URLSearchParams(searchParams.toString());
    if (mineOnly) {
      params.delete("mine");
    } else {
      params.set("mine", "1");
    }
    // router.push にすることで戻るボタンで前の filter 状態に戻れる
// (#16 quick win)。chip の追加/削除/トグルは確定アクションなので
// 1 操作 = 1 history entry の方が自然。
router.push(`/records?${params.toString()}`);
  }, [router, searchParams, mineOnly]);

  useEffect(() => {
    setLoading(true);
    setError(null);

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
        setHasMore(has_more);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [query, conditionsObj, mineOnly, currentUserEmail, templateFilter]);

  // 「自分の record を優先表示」: sort 指定なしのとき、自分の作った record
  // を先頭に持ち上げる (相対順は created_at desc を維持)。mineOnly が ON の
  // 場合は backend で絞り込み済なのでこのソートは no-op。
  const orderedRecords = useMemo(() => {
    if (!currentUserEmail || mineOnly) return records;
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
  }, [records, currentUserEmail, mineOnly]);

  if (error) {
    return <p className="py-8 text-center text-destructive">エラー: {error}</p>;
  }

  const handleClearTemplate = () => {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("template");
    router.push(`/records?${params.toString()}`);
  };

  return (
    <div className="space-y-4">
      {/* フィルタバー: 自分のみ toggle + template chip + condition chip */}
      <div className="flex items-center gap-2 flex-wrap">
        <Button
          size="sm"
          variant={mineOnly ? "default" : "outline"}
          onClick={handleMineToggle}
          disabled={!currentUserEmail}
          title={
            currentUserEmail
              ? mineOnly
                ? "全員の record を表示"
                : "自分が作った record のみ表示"
              : "ログイン情報を取得中"
          }
        >
          {mineOnly ? "✓ 自分のみ" : "自分のみ"}
        </Button>
        {templateFilter && (
          <Button
            size="sm"
            variant="outline"
            onClick={handleClearTemplate}
            className="border-purple-200 text-purple-700 hover:bg-purple-50"
            title={`template "${templateFilter}" でフィルタ中 (クリックで解除)`}
          >
            template: {templateFilter} ×
          </Button>
        )}
        <ConditionFilterPanel
          filters={filters}
          onChange={handleFiltersChange}
          keySuggestions={keySuggestions}
        />
      </div>

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
          {!mineOnly && currentUserEmail && orderedRecords.length > 0 && (
            <span className="ml-2">
              · 自分の record を上部にソート
            </span>
          )}
        </div>
      )}

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
