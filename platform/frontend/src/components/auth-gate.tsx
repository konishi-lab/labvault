"use client";

import { useEffect, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";
import { setTeamProvider, setTokenProvider } from "@/lib/api";
import { RequestAccessForm } from "@/components/request-access-form";
import { PendingStatus } from "@/components/pending-status";

export function AuthGate({ children }: { children: ReactNode }) {
  const { user, loading, signIn, getIdToken, currentTeam, authStatus } =
    useAuth();

  // api.ts 側に token / team 取得関数を渡す。user 切替時に最新を反映。
  useEffect(() => {
    setTokenProvider(getIdToken);
  }, [getIdToken]);

  useEffect(() => {
    setTeamProvider(() => currentTeam);
  }, [currentTeam]);

  if (loading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center text-muted-foreground">
        認証確認中...
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4">
        <div className="text-lg font-semibold">labvault にログイン</div>
        <div className="text-sm text-muted-foreground">
          許可されたアカウントのみアクセスできます
        </div>
        <Button onClick={signIn}>Google でログイン</Button>
      </div>
    );
  }

  // /api/auth/me 応答待ち。
  if (authStatus === "loading") {
    return (
      <div className="flex min-h-[50vh] items-center justify-center text-muted-foreground">
        認可状態を確認中...
      </div>
    );
  }

  if (authStatus === "unregistered") {
    return <RequestAccessForm />;
  }

  if (authStatus === "pending") {
    return <PendingStatus />;
  }

  if (authStatus === "deactivated") {
    return (
      <div className="mx-auto max-w-md space-y-3 rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-sm">
        <div className="text-base font-semibold text-destructive">
          このアカウントは無効化されています
        </div>
        <p className="text-muted-foreground">
          {user.email} は管理者によって無効化されました。アクセスを再開するには
          管理者に連絡してください。
        </p>
      </div>
    );
  }

  // authorized — team 切替時は子コンポーネントを remount して全 fetch を再発火させる。
  return (
    <div key={currentTeam ?? "no-team"} className="contents">
      {children}
    </div>
  );
}
