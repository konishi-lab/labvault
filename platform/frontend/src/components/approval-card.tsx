"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  approveUser,
  type PendingUser,
  type TeamSummary,
} from "@/lib/api";

type Mode = "create_team" | "assign";
type Role = "admin" | "member" | "viewer";

interface Props {
  pending: PendingUser;
  existingTeams: TeamSummary[];
  onApproved: () => void;
}

function slugify(s: string): string {
  return s
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function ApprovalCard({ pending, existingTeams, onApproved }: Props) {
  // 既存 team が無ければ create 一択。あれば assign を初期値にする (既存のどこかに
  // 入れる方が頻度高い想定)。
  const [mode, setMode] = useState<Mode>(
    existingTeams.length > 0 ? "assign" : "create_team",
  );
  const [role, setRole] = useState<Role>("member");

  // create_team フィールド
  const [teamId, setTeamId] = useState(slugify(pending.requested_team_name));
  const [teamName, setTeamName] = useState(pending.requested_team_name);
  // group_folder は既存 team の値を default にする (将来 ARIM プロジェクト変更でも
  // 自動追従)。なければフォールバックなし (空のまま、ユーザーが入力する)
  const defaultGroupFolder = useMemo(
    () => existingTeams[0]?.nextcloud_group_folder ?? "",
    [existingTeams],
  );
  const [groupFolder, setGroupFolder] = useState(defaultGroupFolder);
  const [editingFolder, setEditingFolder] = useState(false);

  // assign フィールド
  const [existingTeamId, setExistingTeamId] = useState<string>(
    existingTeams[0]?.team_id ?? "",
  );

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleApprove = async () => {
    setError(null);
    setSubmitting(true);
    try {
      if (mode === "create_team") {
        if (!teamId.trim() || !groupFolder.trim()) {
          throw new Error("team_id と nextcloud_group_folder は必須です");
        }
        await approveUser({
          email: pending.email,
          action: "create_team",
          role,
          new_team: {
            team_id: teamId.trim(),
            name: teamName.trim() || teamId.trim(),
            nextcloud_group_folder: groupFolder.trim(),
          },
        });
      } else {
        if (!existingTeamId.trim()) {
          throw new Error("既存 team を選択してください");
        }
        await approveUser({
          email: pending.email,
          action: "assign",
          role,
          team_id: existingTeamId.trim(),
        });
      }
      onApproved();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const folderUnchanged =
    !editingFolder && groupFolder === defaultGroupFolder && !!defaultGroupFolder;

  return (
    <Card>
      <CardHeader className="space-y-1 pb-3">
        <CardTitle className="text-base font-medium">
          {pending.display_name || pending.email}
        </CardTitle>
        <div className="text-sm text-muted-foreground">
          <code className="rounded bg-muted px-1 py-0.5">{pending.email}</code>
          {" — 申請: "}
          <span className="font-medium">
            {pending.requested_team_name || "(空)"}
          </span>
        </div>
        {pending.note && (
          <div className="text-sm text-muted-foreground">
            備考: {pending.note}
          </div>
        )}
        {pending.created_at && (
          <div className="text-xs text-muted-foreground">
            申請日時: {new Date(pending.created_at).toLocaleString("ja-JP")}
          </div>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <label className="flex items-center gap-1.5">
            <input
              type="radio"
              name={`mode-${pending.email}`}
              checked={mode === "assign"}
              onChange={() => setMode("assign")}
              disabled={existingTeams.length === 0}
            />
            既存 team に追加
          </label>
          <label className="flex items-center gap-1.5">
            <input
              type="radio"
              name={`mode-${pending.email}`}
              checked={mode === "create_team"}
              onChange={() => setMode("create_team")}
            />
            新規 team を作成
          </label>
        </div>

        {mode === "assign" ? (
          <div className="grid gap-2 md:grid-cols-2">
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">既存 team</span>
              <select
                value={existingTeamId}
                onChange={(e) => setExistingTeamId(e.target.value)}
                disabled={submitting}
                className="rounded border border-input bg-background px-2 py-1 text-sm"
              >
                {existingTeams.length === 0 && (
                  <option value="">(既存 team がありません)</option>
                )}
                {existingTeams.map((t) => (
                  <option key={t.team_id} value={t.team_id}>
                    {t.name ? `${t.name} (${t.team_id})` : t.team_id}
                  </option>
                ))}
              </select>
            </label>
          </div>
        ) : (
          <div className="space-y-2">
            <div className="grid gap-2 md:grid-cols-2">
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium">team_id (slug)</span>
                <Input
                  value={teamId}
                  onChange={(e) => setTeamId(e.target.value)}
                  placeholder="smith-lab"
                  disabled={submitting}
                />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium">表示名</span>
                <Input
                  value={teamName}
                  onChange={(e) => setTeamName(e.target.value)}
                  placeholder="Smith Lab"
                  disabled={submitting}
                />
              </label>
            </div>

            {folderUnchanged ? (
              <div className="flex items-center gap-2 text-sm">
                <span className="text-muted-foreground">
                  Nextcloud group folder:
                </span>
                <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
                  {defaultGroupFolder}
                </code>
                <span className="text-xs text-muted-foreground">
                  (実際のパスは <code>{defaultGroupFolder}/labvault/{teamId || "{team_id}"}/...</code>)
                </span>
                <button
                  type="button"
                  onClick={() => setEditingFolder(true)}
                  className="ml-auto text-xs text-primary underline-offset-2 hover:underline"
                >
                  変更
                </button>
              </div>
            ) : (
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium">Nextcloud group folder</span>
                <Input
                  value={groupFolder}
                  onChange={(e) => setGroupFolder(e.target.value)}
                  placeholder={defaultGroupFolder || "large/24UTARIM004"}
                  disabled={submitting}
                />
                <span className="text-xs text-muted-foreground">
                  実際のパスは <code>{groupFolder || "{group_folder}"}/labvault/{teamId || "{team_id}"}/...</code>
                </span>
              </label>
            )}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="font-medium">role:</span>
          {(["admin", "member", "viewer"] as Role[]).map((r) => (
            <label key={r} className="flex items-center gap-1.5">
              <input
                type="radio"
                name={`role-${pending.email}`}
                checked={role === r}
                onChange={() => setRole(r)}
              />
              {r}
            </label>
          ))}
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <div className="flex justify-end">
          <Button onClick={handleApprove} disabled={submitting}>
            {submitting ? "承認中..." : "承認"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
