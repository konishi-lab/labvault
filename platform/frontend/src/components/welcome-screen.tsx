"use client";

import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/lib/auth";

/**
 * 認可後 (allowed_users 登録 + active) の初回ログインで 1 回だけ表示する
 * welcome panel。「始める」ボタンで /api/auth/welcome-acknowledged を叩いて
 * 以降出さない。
 */
export function WelcomeScreen() {
  const { user, teams, dismissWelcome } = useAuth();
  const [submitting, setSubmitting] = useState(false);

  const handleStart = async () => {
    setSubmitting(true);
    try {
      await dismissWelcome();
    } finally {
      setSubmitting(false);
    }
  };

  const teamLabel =
    teams.length === 1
      ? teams[0].name || teams[0].team_id
      : teams.length > 1
        ? `${teams.length} 個の team (${teams.map((t) => t.name || t.team_id).join(", ")})`
        : "(team 未設定)";

  return (
    <div className="mx-auto max-w-2xl space-y-6 py-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-bold tracking-tight">
          labvault へようこそ {user?.displayName ? `, ${user.displayName}` : ""}
        </h1>
        <p className="text-sm text-muted-foreground">
          管理者に承認されました。所属: <strong>{teamLabel}</strong>
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Web UI でできること</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <ul className="list-disc space-y-1 pl-5">
            <li>レコード一覧・詳細の閲覧、条件・結果のグラフ表示</li>
            <li>タグ・メモ・単位の編集、ファイルの一括アップロード</li>
            <li>条件で絞り込み検索 (例: <code>power &gt;= 50</code>)</li>
          </ul>
        </CardContent>
      </Card>

      <Card className="border-primary/30 bg-primary/5">
        <CardHeader>
          <CardTitle className="text-base">
            SDK / 装置 PC で使うなら API トークンを発行
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p>
            Python SDK (Notebook / CLI / MCP) や装置 PC から labvault に書き込む
            には、Personal Access Token (PAT) を発行して
            <code className="ml-1 mr-1 rounded bg-muted px-1 py-0.5">
              ~/.labvault/credentials
            </code>
            に置いてください。Google アカウント無しでも動作します。
          </p>
          <div className="flex flex-wrap gap-2">
            <Link href="/account/tokens">
              <Button size="sm">トークンを発行</Button>
            </Link>
            <a
              href="https://github.com/konishi-lab/labvault/blob/main/docs/instrument_pc_setup.md"
              target="_blank"
              rel="noreferrer"
            >
              <Button size="sm" variant="outline">
                装置 PC セットアップ手順
              </Button>
            </a>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">困ったら</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1 text-sm">
          <p>所属 team / role の変更は管理者にご連絡ください。</p>
          <p>
            アカウントを無効化されたい場合も管理者に。トークンの失効は{" "}
            <Link
              href="/account/tokens"
              className="text-primary underline-offset-2 hover:underline"
            >
              /account/tokens
            </Link>{" "}
            から自分で操作できます。
          </p>
        </CardContent>
      </Card>

      <div className="flex justify-end">
        <Button onClick={handleStart} disabled={submitting} size="lg">
          {submitting ? "..." : "始める"}
        </Button>
      </div>
    </div>
  );
}
