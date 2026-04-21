"use client";

import { useEffect, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";
import { setTokenProvider } from "@/lib/api";

export function AuthGate({ children }: { children: ReactNode }) {
  const { user, loading, signIn, getIdToken } = useAuth();

  // api.ts 側に token 取得関数を渡す。user 切替時に最新の getIdToken を反映。
  useEffect(() => {
    setTokenProvider(getIdToken);
  }, [getIdToken]);

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

  return <>{children}</>;
}
