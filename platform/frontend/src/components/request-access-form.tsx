"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/lib/auth";
import { requestAccess } from "@/lib/api";

export function RequestAccessForm() {
  const { user, signOut, refreshAuthStatus } = useAuth();
  const [teamName, setTeamName] = useState("");
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!teamName.trim()) {
      setError("研究室名を入力してください");
      return;
    }
    setSubmitting(true);
    try {
      await requestAccess(teamName.trim(), note.trim());
      await refreshAuthStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto flex min-h-[60vh] max-w-md flex-col justify-center gap-6">
      <div>
        <div className="text-lg font-semibold">アクセス申請</div>
        <div className="mt-1 text-sm text-muted-foreground">
          {user?.email} はまだ labvault に登録されていません。所属研究室を入力して
          申請してください。admin が承認すると利用可能になります。
        </div>
      </div>
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">研究室名 (例: konishi-lab)</span>
          <Input
            value={teamName}
            onChange={(e) => setTeamName(e.target.value)}
            placeholder="所属研究室名"
            disabled={submitting}
            required
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">備考 (任意)</span>
          <Input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="admin への補足メッセージ"
            disabled={submitting}
          />
        </label>
        {error && (
          <p className="text-sm text-destructive">{error}</p>
        )}
        <div className="flex items-center gap-3">
          <Button type="submit" disabled={submitting}>
            {submitting ? "申請中..." : "申請する"}
          </Button>
          <Button type="button" variant="outline" onClick={signOut}>
            ログアウト
          </Button>
        </div>
      </form>
    </div>
  );
}
