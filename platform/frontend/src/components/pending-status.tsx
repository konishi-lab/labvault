"use client";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";

export function PendingStatus() {
  const { user, signOut, pendingInfo, refreshAuthStatus } = useAuth();
  return (
    <div className="mx-auto flex min-h-[60vh] max-w-md flex-col items-center justify-center gap-4 text-center">
      <div className="text-lg font-semibold">申請を確認中です</div>
      <div className="text-sm text-muted-foreground">
        {user?.email} は申請済みです。admin が承認するまでお待ちください。
      </div>
      {pendingInfo?.requested_team_name && (
        <div className="text-sm text-muted-foreground">
          申請した研究室: <code className="rounded bg-muted px-1.5 py-0.5">{pendingInfo.requested_team_name}</code>
        </div>
      )}
      <div className="mt-4 flex items-center gap-3">
        <Button variant="outline" onClick={() => refreshAuthStatus()}>
          状態を再確認
        </Button>
        <Button variant="outline" onClick={signOut}>
          ログアウト
        </Button>
      </div>
    </div>
  );
}
