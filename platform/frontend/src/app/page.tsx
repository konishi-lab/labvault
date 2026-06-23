"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth";
import { fetchRecords } from "@/lib/api";
import type { RecordSummary } from "@/lib/api";
import { computeDashboard } from "@/lib/dashboard";
import {
  DashboardChipRow,
  DashboardOnboarding,
} from "@/components/dashboard-chip-row";

/**
 * トップ (ダッシュボード)。
 *
 * D5 (戦略案 #7 を full hub 化せず最小コスト版で代替):
 * - ChipRow 3 枚: 今週件数 + 先週比 / 直近 30 日 status / 今週 template top 3
 * - 「最近のレコード 5 件」セクションは削除 (QuickLink「レコード一覧」と
 *   役割重複していた)。chip クリックで `/records` に飛ばすことで動線を吸収
 * - 0 件 team: `DashboardOnboarding` カードに差し替え (空 chip を並べると
 *   新 team に冷たい印象を与えるため)
 */
export default function HomePage() {
  const { user, teams, isAdmin } = useAuth();
  const [records, setRecords] = useState<RecordSummary[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchRecords({ limit: 200 })
      .then((res) => {
        setRecords(res.items);
        setHasMore(!!res.has_more);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const dashboard = useMemo(
    () => computeDashboard(records, hasMore),
    [records, hasMore],
  );

  const teamLabel =
    teams.length === 0
      ? "(team 未設定)"
      : teams.length === 1
        ? teams[0].name || teams[0].team_id
        : `${teams.length} team (${teams.map((t) => t.name || t.team_id).join(", ")})`;

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold tracking-tight">
          {user?.displayName ? `${user.displayName} さん、ようこそ` : "labvault"}
        </h1>
        <p className="text-sm text-muted-foreground">
          所属: <span className="font-medium">{teamLabel}</span>
        </p>
      </div>

      {/* ChipRow (or onboarding) — PI が活動量を 5 秒で把握する区画 */}
      {error && <p className="text-sm text-destructive">エラー: {error}</p>}
      {!error && loading && (
        <div className="grid gap-3 grid-cols-1 sm:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-[88px]" />
          ))}
        </div>
      )}
      {!error && !loading && records.length === 0 && <DashboardOnboarding />}
      {!error && !loading && records.length > 0 && (
        <DashboardChipRow summary={dashboard} />
      )}

      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <QuickLink
          href="/records"
          title="レコード一覧"
          description="実験データの閲覧 / 検索 / 散布図 / 一括アップロード"
        />
        <QuickLink
          href="/account/tokens"
          title="API トークン"
          description="SDK / 装置 PC 用の Personal Access Token を発行・管理"
        />
        <QuickLinkExternal
          href="https://github.com/konishi-lab/labvault/blob/main/docs/instrument_pc_setup.md"
          title="装置 PC セットアップ"
          description="装置 PC から labvault に投入する手順 (GitHub)"
        />
        {isAdmin && (
          <QuickLink
            href="/admin/users"
            title="ユーザー管理"
            description="所属 team のメンバー追加 / 権限変更 (admin のみ)"
          />
        )}
      </div>

      <Card>
        <CardContent className="p-4 space-y-1 text-sm text-muted-foreground">
          <p className="font-medium text-foreground text-base">困ったら</p>
          <p>所属 team / role の変更は管理者に連絡してください。</p>
          <p>
            トークンの失効は{" "}
            <Link
              href="/account/tokens"
              className="text-primary underline-offset-2 hover:underline"
            >
              /account/tokens
            </Link>{" "}
            から自分で操作できます。
          </p>
          <p>
            ようこそ画面 (labvault の紹介・トークン発行・装置 PC 手順) は{" "}
            <Link
              href="/welcome"
              className="text-primary underline-offset-2 hover:underline"
            >
              /welcome
            </Link>{" "}
            からいつでも見直せます。
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

function QuickLink({
  href,
  title,
  description,
}: {
  href: string;
  title: string;
  description: string;
}) {
  return (
    <Link href={href} className="group">
      <Card className="h-full transition-colors hover:border-primary/40 hover:bg-muted/30">
        <CardContent className="space-y-1 p-4">
          <div className="text-sm font-semibold group-hover:text-primary">
            {title}
          </div>
          <div className="text-xs text-muted-foreground">{description}</div>
        </CardContent>
      </Card>
    </Link>
  );
}

function QuickLinkExternal({
  href,
  title,
  description,
}: {
  href: string;
  title: string;
  description: string;
}) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className="group">
      <Card className="h-full transition-colors hover:border-primary/40 hover:bg-muted/30">
        <CardContent className="space-y-1 p-4">
          <div className="text-sm font-semibold group-hover:text-primary">
            {title} ↗
          </div>
          <div className="text-xs text-muted-foreground">{description}</div>
        </CardContent>
      </Card>
    </a>
  );
}
