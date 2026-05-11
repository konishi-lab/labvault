"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth";
import { UserCard } from "@/components/user-card";
import {
  fetchAllowedUsers,
  fetchAllTeams,
  type AllowedUserSummary,
  type TeamSummary,
} from "@/lib/api";

export default function AdminUsersPage() {
  const { role, user: currentUser } = useAuth();
  const [users, setUsers] = useState<AllowedUserSummary[]>([]);
  const [teams, setTeams] = useState<TeamSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [u, t] = await Promise.all([
        fetchAllowedUsers(),
        fetchAllTeams(),
      ]);
      setUsers(u);
      setTeams(t);
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
        <p className="text-destructive">super-admin 権限が必要です。</p>
      </div>
    );
  }

  const q = filter.trim().toLowerCase();
  const visible = q
    ? users.filter(
        (u) =>
          u.email.toLowerCase().includes(q) ||
          u.display_name.toLowerCase().includes(q) ||
          u.teams.some(
            (t) =>
              t.team_id.toLowerCase().includes(q) ||
              (t.name || "").toLowerCase().includes(q),
          ),
      )
    : users;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link href="/">
          <Button variant="ghost" className="cursor-pointer">
            ← 一覧
          </Button>
        </Link>
        <h1 className="text-2xl font-bold tracking-tight">ユーザー管理</h1>
        <Button variant="outline" onClick={reload} className="ml-auto">
          再読込
        </Button>
      </div>

      {error && <p className="text-sm text-destructive">エラー: {error}</p>}

      <Input
        placeholder="email / 名前 / team で絞り込み"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        className="max-w-md"
      />

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base font-medium">
              {users.length === 0
                ? "承認済ユーザーはいません"
                : "条件に一致するユーザーがいません"}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            申請の承認は{" "}
            <Link
              href="/admin/pending"
              className="text-primary underline-offset-2 hover:underline"
            >
              /admin/pending
            </Link>{" "}
            から。
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {visible.map((u) => (
            <UserCard
              key={u.email}
              user={u}
              allTeams={teams}
              currentAdminEmail={currentUser?.email ?? null}
              onChanged={reload}
            />
          ))}
        </div>
      )}
    </div>
  );
}
