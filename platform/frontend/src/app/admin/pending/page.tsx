"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth";
import { ApprovalCard } from "@/components/approval-card";
import {
  fetchAllTeams,
  fetchPendingUsers,
  type PendingUser,
  type TeamSummary,
} from "@/lib/api";

export default function AdminPendingPage() {
  const { role } = useAuth();
  const [items, setItems] = useState<PendingUser[]>([]);
  const [teams, setTeams] = useState<TeamSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [list, ts] = await Promise.all([
        fetchPendingUsers(),
        fetchAllTeams(),
      ]);
      setItems(list);
      setTeams(ts);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (role !== "admin") return;
    reload();
  }, [role, reload]);

  if (role !== "admin") {
    return (
      <div className="space-y-4">
        <Link href="/">
          <Button variant="ghost" className="cursor-pointer">
            ← 一覧に戻る
          </Button>
        </Link>
        <p className="text-destructive">
          super-admin 権限が必要です。
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link href="/">
          <Button variant="ghost" className="cursor-pointer">
            ← 一覧
          </Button>
        </Link>
        <h1 className="text-2xl font-bold tracking-tight">サインアップ申請</h1>
        <Button variant="outline" onClick={reload} className="ml-auto">
          再読込
        </Button>
      </div>

      {error && (
        <p className="text-sm text-destructive">エラー: {error}</p>
      )}

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base font-medium">
              保留中の申請はありません
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            ユーザーが <code>/api/auth/request-access</code> を叩くとここに表示されます。
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {items.map((p) => (
            <ApprovalCard
              key={p.email}
              pending={p}
              existingTeams={teams}
              onApproved={reload}
            />
          ))}
        </div>
      )}
    </div>
  );
}
