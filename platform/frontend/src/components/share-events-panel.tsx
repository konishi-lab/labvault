"use client";

/**
 * 2026-07-01: 共有 event 監査 log の表示パネル。
 *
 * 共有 dialog の下部にたたまれた状態で出て、開くと「新しい順」の event
 * 一覧が読める。event_type ごとにアイコン + 説明を差し替え、target_email
 * / pseudo_email などの optional field は event に応じて表示・非表示。
 *
 * 認可: grant 主体 (admin) 経路の user だけがこのパネルを見える (親側で
 * canGrant で gating)。
 */

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchShareEvents, type ShareEventEntry } from "@/lib/api";

function formatDateTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString("ja-JP", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

// event_type ごとの 1 行 summary (icon + verb + target)。
// tokenHashPrefix は 16 chars で raw ではないので表示 OK。
function describeEvent(e: ShareEventEntry): {
  icon: string;
  verb: string;
  targetLabel: string;
} {
  switch (e.event_type) {
    case "granted":
      return {
        icon: "✚",
        verb: `${e.role} 共有を付与`,
        targetLabel: e.target_email ?? "(不明)",
      };
    case "revoked":
      return {
        icon: "✕",
        verb: "共有を解除",
        targetLabel: e.target_email ?? "(不明)",
      };
    case "link_issued":
      return {
        icon: "🔗",
        verb: `${e.role} トークン発行`,
        targetLabel: e.pseudo_email ?? e.token_hash_prefix ?? "(不明)",
      };
    case "link_revoked":
      return {
        icon: "🚫",
        verb: "トークン失効",
        targetLabel: e.pseudo_email ?? e.token_hash_prefix ?? "(不明)",
      };
    default:
      return { icon: "?", verb: e.event_type, targetLabel: "" };
  }
}

export function ShareEventsPanel({ recordId }: { recordId: string }) {
  const [open, setOpen] = useState(false);
  const [events, setEvents] = useState<ShareEventEntry[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || events !== null) return;
    setLoading(true);
    fetchShareEvents(recordId, { limit: 200 })
      .then((items) => setEvents(items))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [open, events, recordId]);

  return (
    <div className="border-t pt-3 space-y-2">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full text-left flex items-center gap-2 text-xs font-medium text-muted-foreground hover:text-foreground cursor-pointer"
        aria-expanded={open}
      >
        <span>{open ? "▼" : "▶"}</span>
        <span>履歴 (監査ログ)</span>
        {events && events.length > 0 && (
          <Badge
            variant="outline"
            className="text-[10px] ml-auto"
            title="この record に対する共有操作の履歴 (grant / revoke / トークン発行 / トークン失効)"
          >
            {events.length}
          </Badge>
        )}
      </button>
      {open && (
        <div className="space-y-1">
          {loading && <Skeleton className="h-16 w-full" />}
          {error && (
            <p className="text-[11px] text-destructive">
              履歴の取得に失敗しました: {error}
            </p>
          )}
          {!loading && !error && events && events.length === 0 && (
            <p className="text-[11px] text-muted-foreground py-1">
              履歴はまだありません。
            </p>
          )}
          {!loading && !error && events && events.length > 0 && (
            <ul className="space-y-1.5 max-h-64 overflow-y-auto">
              {events.map((e, i) => {
                const d = describeEvent(e);
                return (
                  <li
                    key={`${e.at}-${i}`}
                    className="rounded border border-border/40 px-2 py-1.5 text-[11px] space-y-0.5"
                  >
                    <div className="flex items-center gap-1.5">
                      <span aria-hidden className="shrink-0">
                        {d.icon}
                      </span>
                      <span className="font-medium">{d.verb}</span>
                      <span
                        className="font-mono text-muted-foreground truncate"
                        title={d.targetLabel}
                      >
                        {d.targetLabel}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 text-muted-foreground pl-4">
                      <span
                        className="font-mono truncate"
                        title={`operator: ${e.actor_email} (${e.actor_audit_source || "unknown"})`}
                      >
                        by {e.actor_email}
                      </span>
                      <span className="ml-auto tabular-nums shrink-0">
                        {formatDateTime(e.at)}
                      </span>
                    </div>
                    {e.label && (
                      <div className="pl-4 text-muted-foreground italic truncate">
                        “{e.label}”
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
