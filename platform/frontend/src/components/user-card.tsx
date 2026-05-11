"use client";

import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  addUserTeam,
  removeUserTeam,
  type AllowedUserSummary,
  type TeamRole,
  type TeamSummary,
} from "@/lib/api";

interface Props {
  user: AllowedUserSummary;
  allTeams: TeamSummary[];
  onChanged: () => void;
}

export function UserCard({ user, allTeams, onChanged }: Props) {
  const [adding, setAdding] = useState(false);
  const [pendingTeam, setPendingTeam] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const memberOf = useMemo(
    () => new Set(user.teams.map((t) => t.team_id)),
    [user.teams],
  );
  const candidates = useMemo(
    () => allTeams.filter((t) => !memberOf.has(t.team_id)),
    [allTeams, memberOf],
  );

  const [newTeamId, setNewTeamId] = useState<string>(
    candidates[0]?.team_id ?? "",
  );
  const [newRole, setNewRole] = useState<TeamRole>("member");

  const handleAdd = async () => {
    if (!newTeamId) return;
    setError(null);
    setAdding(true);
    try {
      await addUserTeam(user.email, newTeamId, newRole);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setAdding(false);
    }
  };

  const handleRemove = async (teamId: string) => {
    if (
      !confirm(
        `${user.email} を team "${teamId}" から外しますか?`,
      )
    ) {
      return;
    }
    setError(null);
    setPendingTeam(teamId);
    try {
      await removeUserTeam(user.email, teamId);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPendingTeam(null);
    }
  };

  return (
    <Card className={user.active ? "" : "opacity-60"}>
      <CardHeader className="space-y-1 pb-3">
        <CardTitle className="flex items-center gap-2 text-base font-medium">
          <span>{user.display_name || user.email}</span>
          {user.role === "admin" && (
            <Badge variant="default">super-admin</Badge>
          )}
          {!user.active && <Badge variant="destructive">deactivated</Badge>}
        </CardTitle>
        <div className="text-sm text-muted-foreground">
          <code className="rounded bg-muted px-1 py-0.5">{user.email}</code>
          {user.default_team && (
            <>
              {" — default: "}
              <span className="font-medium">{user.default_team}</span>
            </>
          )}
        </div>
        {user.last_login_at && (
          <div className="text-xs text-muted-foreground">
            最終ログイン: {new Date(user.last_login_at).toLocaleString("ja-JP")}
          </div>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1">
          <div className="text-xs font-medium uppercase text-muted-foreground">
            所属 team
          </div>
          {user.teams.length === 0 ? (
            <div className="text-sm text-destructive">team 未設定</div>
          ) : (
            <div className="flex flex-wrap gap-2">
              {user.teams.map((t) => (
                <span
                  key={t.team_id}
                  className="inline-flex items-center gap-1 rounded-full border bg-muted/50 py-0.5 pl-2 pr-1 text-xs"
                >
                  <span className="font-medium">{t.name || t.team_id}</span>
                  <span className="text-muted-foreground">({t.role})</span>
                  <button
                    type="button"
                    onClick={() => handleRemove(t.team_id)}
                    disabled={pendingTeam === t.team_id}
                    className="ml-0.5 inline-flex h-4 w-4 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive disabled:opacity-50"
                    aria-label={`Remove ${t.team_id}`}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>

        {candidates.length > 0 && (
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs font-medium text-muted-foreground">
                team を追加
              </span>
              <select
                value={newTeamId}
                onChange={(e) => setNewTeamId(e.target.value)}
                disabled={adding}
                className="rounded border border-input bg-background px-2 py-1 text-sm"
              >
                {candidates.map((t) => (
                  <option key={t.team_id} value={t.team_id}>
                    {t.name ? `${t.name} (${t.team_id})` : t.team_id}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs font-medium text-muted-foreground">
                role
              </span>
              <select
                value={newRole}
                onChange={(e) => setNewRole(e.target.value as TeamRole)}
                disabled={adding}
                className="rounded border border-input bg-background px-2 py-1 text-sm"
              >
                <option value="admin">admin</option>
                <option value="member">member</option>
                <option value="viewer">viewer</option>
              </select>
            </label>
            <Button
              size="sm"
              onClick={handleAdd}
              disabled={adding || !newTeamId}
            >
              {adding ? "追加中..." : "追加"}
            </Button>
          </div>
        )}

        {error && <p className="text-sm text-destructive">{error}</p>}
      </CardContent>
    </Card>
  );
}
