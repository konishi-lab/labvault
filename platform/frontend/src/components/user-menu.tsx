"use client";

import { Button } from "@/components/ui/button";
import { TeamSelector } from "@/components/team-selector";
import { useAuth } from "@/lib/auth";

export function UserMenu() {
  const { user, signOut } = useAuth();
  if (!user) return null;
  return (
    <div className="flex items-center gap-3 text-sm">
      <TeamSelector />
      <span className="text-muted-foreground">{user.displayName}</span>
      <Button size="sm" variant="outline" onClick={signOut}>
        ログアウト
      </Button>
    </div>
  );
}
