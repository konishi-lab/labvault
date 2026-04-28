"use client";

import { useAuth } from "@/lib/auth";

export function TeamSelector() {
  const { teams, currentTeam, setCurrentTeam } = useAuth();
  if (teams.length <= 1) return null;
  return (
    <select
      value={currentTeam ?? ""}
      onChange={(e) => setCurrentTeam(e.target.value)}
      className="rounded border border-input bg-background px-2 py-1 text-sm"
      aria-label="チーム切替"
    >
      {teams.map((t) => (
        <option key={t.team_id} value={t.team_id}>
          {t.name || t.team_id}
        </option>
      ))}
    </select>
  );
}
