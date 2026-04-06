"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { RecordTable } from "@/components/record-table";
import { SearchBar } from "@/components/search-bar";
import { fetchRecords, searchRecords } from "@/lib/api";
import type { RecordSummary } from "@/lib/api";

function RecordsContent() {
  const searchParams = useSearchParams();
  const query = searchParams.get("q") || "";
  const [records, setRecords] = useState<RecordSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);

    const load = query
      ? searchRecords(query)
      : fetchRecords({ limit: 50 }).then((res) => res.items);

    load
      .then(setRecords)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [query]);

  if (error) {
    return (
      <p className="py-8 text-center text-destructive">エラー: {error}</p>
    );
  }

  if (loading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    );
  }

  return <RecordTable records={records} />;
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
