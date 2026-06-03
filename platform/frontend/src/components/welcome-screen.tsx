"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/lib/auth";

/**
 * 認可後 (allowed_users 登録 + active) の初回ログインで 1 回だけ表示する
 * welcome panel。「始める」ボタンで /api/auth/welcome-acknowledged を叩いて
 * 以降出さない。
 *
 * 「トークンを発行」も dismiss + 遷移をセットで行う。AuthGate が
 * showWelcome=true の間は他の URL に行っても WelcomeScreen が出続けるため、
 * Link 単独だと「押しても何も起きない」ように見える。
 */
export function WelcomeScreen() {
  const router = useRouter();
  const { user, teams, dismissWelcome } = useAuth();
  const [submitting, setSubmitting] = useState<null | "start" | "tokens">(null);

  const handleStart = async () => {
    setSubmitting("start");
    try {
      await dismissWelcome();
      // 初回ログイン welcome は AuthGate 経由で出るので、dismiss 後は AuthGate
      // が children を表示し始める = 同じ URL のまま Dashboard 等に切替わる。
      // 一方 /welcome URL から開いている場合は明示的に "/" に push しないと
      // welcome ページがそのまま残るため、両ケースで router.push("/") する。
      router.push("/");
    } finally {
      setSubmitting(null);
    }
  };

  const handleGoToTokens = async () => {
    setSubmitting("tokens");
    try {
      await dismissWelcome();
      router.push("/account/tokens");
    } finally {
      setSubmitting(null);
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
            SDK / 装置 PC で使うなら API トークン (PAT) を発行
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p>
            Python SDK (Notebook / CLI / MCP) や装置 PC から labvault に
            アクセスするには、Personal Access Token (PAT) を発行します。
            <strong>1 つの PAT で pip install もランタイム認証も完了</strong>
            し、Google アカウント / gcloud は不要です。
          </p>
          <ol className="list-decimal space-y-1 pl-5">
            <li>下の「トークンを発行」を押し、ラベル (用途のメモ) を
              入れて発行 → <code>lv_xxx</code> をコピー</li>
            <li>
              端末で <code className="rounded bg-muted px-1">pip install</code> :
              <pre className="mt-1 overflow-x-auto rounded bg-muted px-2 py-1 text-[11px]">
{`pip install \\
  --index-url https://pypi.org/simple/ \\
  --extra-index-url "https://__token__:lv_xxx@labvault-api-355809880738.asia-northeast1.run.app/api/pypi/simple/" \\
  "labvault[all]"`}
              </pre>
            </li>
            <li>
              同じ PAT を{" "}
              <code className="rounded bg-muted px-1">~/.labvault/credentials</code>{" "}
              にも書く (詳細は装置 PC セットアップ手順)
            </li>
          </ol>
          <div className="flex flex-wrap gap-2 pt-1">
            <Button
              size="sm"
              onClick={handleGoToTokens}
              disabled={submitting !== null}
            >
              {submitting === "tokens" ? "..." : "トークンを発行"}
            </Button>
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
        <Button
          onClick={handleStart}
          disabled={submitting !== null}
          size="lg"
        >
          {submitting === "start" ? "..." : "始める"}
        </Button>
      </div>
    </div>
  );
}
