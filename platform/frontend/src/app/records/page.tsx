"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { SortableRecordTable } from "@/components/sortable-record-table";
import { SearchBar } from "@/components/search-bar";
import {
  ConditionFilterPanel,
  type ConditionFilter,
} from "@/components/condition-filter";
import { fetchRecords, searchRecords } from "@/lib/api";
import type { RecordSummary } from "@/lib/api";

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

  const [records, setRecords] = useState<RecordSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
      router.replace(`/records?${params.toString()}`);
    },
    [router, searchParams],
  );

  useEffect(() => {
    setLoading(true);
    setError(null);

    // 検索クエリがあるときは /api/search 経由 (vector search、conditions は
    // 現状サポートしていない)。検索クエリが無いときは /api/records 経由で
    // conditions を Firestore に push down する (PR #14)。
    const load = query
      ? searchRecords(query)
      : fetchRecords({
          limit: 50,
          conditions:
            Object.keys(conditionsObj).length > 0 ? conditionsObj : undefined,
        }).then((res) => res.items);

    load
      .then(setRecords)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [query, conditionsObj]);

  if (error) {
    return <p className="py-8 text-center text-destructive">エラー: {error}</p>;
  }

  return (
    <div className="space-y-4">
      <ConditionFilterPanel filters={filters} onChange={handleFiltersChange} />
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : (
        <SortableRecordTable records={records} defaultSort="created_at" />
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
