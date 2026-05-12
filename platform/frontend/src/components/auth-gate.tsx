"use client";

import { useEffect, type ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import { setTeamProvider, setTokenProvider } from "@/lib/api";
import { RequestAccessForm } from "@/components/request-access-form";
import { PendingStatus } from "@/components/pending-status";
import { LoginForm } from "@/components/login-form";
import { WelcomeScreen } from "@/components/welcome-screen";

export function AuthGate({ children }: { children: ReactNode }) {
  const { user, loading, getIdToken, currentTeam, authStatus, showWelcome } =
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
    return <LoginForm />;
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

  // 初回ログイン (welcomed_at が無い) なら welcome 画面を 1 回だけ出す。
  if (showWelcome) {
    return <WelcomeScreen />;
  }

  // authorized — team 切替時は子コンポーネントを remount して全 fetch を再発火させる。
  return (
    <div key={currentTeam ?? "no-team"} className="contents">
      {children}
    </div>
  );
}
