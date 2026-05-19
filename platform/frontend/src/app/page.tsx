"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth";
import { fetchRecords } from "@/lib/api";
import type { RecordSummary } from "@/lib/api";

/**
 * トップ (ダッシュボード)。
 * - 既存ユーザー: 最近のレコード 5 件 + 主要セクションへのクイックリンク
 * - 新規ユーザー: WelcomeScreen が AuthGate 段階で出るので、ここに来た時点で
 *   「welcome 完了済み」状態
 * - レコード一覧は /records に分離
 */
export default function HomePage() {
  const { user, teams, isAdmin } = useAuth();
  const [recent, setRecent] = useState<RecordSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchRecords({ limit: 5 })
      .then((res) => setRecent(res.items))
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

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
        <CardHeader className="flex flex-row items-center justify-between pb-3">
          <CardTitle className="text-base font-medium">最近のレコード</CardTitle>
          <Link href="/records">
            <Button variant="ghost" size="sm">
              すべて見る →
            </Button>
          </Link>
        </CardHeader>
        <CardContent>
          {error && <p className="text-sm text-destructive">エラー: {error}</p>}
          {loading ? (
            <div className="space-y-2">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : recent.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              まだレコードがありません。SDK で <code>lab.new(...)</code> するか、
              <Link
                href="/records"
                className="ml-1 text-primary underline-offset-2 hover:underline"
              >
                /records
              </Link>{" "}
              から一括アップロードで作成できます。
            </p>
          ) : (
            <ul className="divide-y">
              {recent.map((r) => (
                <li key={r.id} className="py-2">
                  <Link
                    href={`/records/${r.id}`}
                    className="flex items-center gap-3 text-sm hover:bg-muted/50 -mx-2 px-2 py-1 rounded"
                  >
                    <code className="rounded bg-muted px-1 py-0.5 text-xs">
                      {r.id}
                    </code>
                    <span className="flex-1 truncate">{r.title}</span>
                    <span className="text-xs text-muted-foreground">
                      {r.status}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base font-medium">困ったら</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1 text-sm text-muted-foreground">
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
