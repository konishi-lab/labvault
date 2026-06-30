"use client";

// S1 Phase 1B: 「他チームから共有された record」表示用のシンプルリスト。
//
// 通常の /records 一覧 (`SortableRecordTable`) と並列するが、shared 経路は:
// - 並べ替えやカラム選択は無し (フィルタもしない、cross-team )
// - 各 row に team chip と role badge を出す
// - record をクリックすると currentTeam を **record owner team** に
//   切り替えてから /records/{id} に遷移する。X-Labvault-Team が
//   record の所有 team を指すことで詳細 fetch が 200 で通る。
//   - 自分が元々属する team に戻すには team selector で手動切替。

import { useRouter } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/lib/auth";
import type { SharedRecordSummary } from "@/lib/api";
import { ROLE_LABELS_BADGE } from "@/lib/format";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ja-JP", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function SharedRecordsList({
  items,
  hasMore,
}: {
  items: SharedRecordSummary[];
  hasMore: boolean;
}) {
  const router = useRouter();
  const { setCurrentTeam, currentTeam, teams } = useAuth();

  if (items.length === 0) {
    return (
      <p className="py-8 text-center text-muted-foreground text-sm">
        あなた宛てに共有された record はまだありません。
        <br />
        別チームメンバーから record の URL や ID を教えてもらって、所有者に
        「共有」ボタンから viewer / analyst として追加してもらってください。
      </p>
    );
  }

  // 自分が所属する team の id 集合 (UI ハイライト用)。
  const myTeamIds = new Set(teams.map((t) => t.team_id));

  const handleClick = (item: SharedRecordSummary) => {
    // S1-UX1 (PR #92): 切替判定は currentTeam との差分。teams=[A,B]/
    // currentTeam=A で team B の共有 record をクリックしても 404 にしない。
    //
    // S1-UX3 (2026-06-29、本 PR): localStorage への永続書込を抑制し session
    // のみで切替える。「shared 経由で他チームの record を覗いたら、次回
    // ログイン / 再読み込み時には自分の default team に自然に戻る」が
    // 期待動作。auth.tsx:250-258 の guard で teams に含まれない team は
    // 次回 fetchAuthStatus で default_team に auto-recover するので、
    // 自 team に切り替えた場合は永続化したい (= persist=true) との
    // 細かい挙動差はあるが、シンプルに常に persist=false で十分。
    if (item.team && item.team !== currentTeam) {
      setCurrentTeam(item.team, { persist: false });
    }
    router.push(`/records/${item.id}`);
  };

  return (
    <div className="space-y-2">
      <div className="text-xs text-muted-foreground px-1">
        {items.length} 件{hasMore ? "+ (もっと絞り込んでください)" : ""}
      </div>
      <ul className="space-y-1.5">
        {items.map((item) => {
          const isMyTeam = myTeamIds.has(item.team);
          return (
            <li key={`${item.team}/${item.id}`}>
              <button
                type="button"
                onClick={() => handleClick(item)}
                className="w-full text-left rounded-md border px-3 py-2 hover:bg-muted/50 transition-colors cursor-pointer"
              >
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-mono text-xs font-semibold text-primary">
                    {item.id}
                  </span>
                  <span className="font-medium text-sm truncate">
                    {item.title}
                  </span>
                  <span className="ml-auto text-xs text-muted-foreground">
                    {formatDate(item.updated_at)}
                  </span>
                </div>
                <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                  <Badge
                    variant="outline"
                    className="text-[10px] gap-1"
                    title={
                      isMyTeam
                        ? "自分が所属する team"
                        : "他チームの team (クリックで X-Labvault-Team を一時的に切替)"
                    }
                  >
                    <span aria-hidden>{isMyTeam ? "🏠" : "🌐"}</span>
                    {item.team}
                  </Badge>
                  <Badge
                    variant={item.role === "analyst" ? "default" : "secondary"}
                    className="text-[10px]"
                    title={
                      item.role === "analyst"
                        ? "解析投稿 (子 record + ファイル upload) 可能"
                        : "閲覧 + DL のみ"
                    }
                  >
                    {ROLE_LABELS_BADGE[
                      item.role as keyof typeof ROLE_LABELS_BADGE
                    ] ?? item.role}
                  </Badge>
                  {item.template_name && (
                    <Badge
                      variant="outline"
                      className="text-[10px] gap-1"
                      title={`template: ${item.template_name}`}
                    >
                      <span aria-hidden>📎</span>
                      {item.template_name}
                    </Badge>
                  )}
                  {item.created_by && (
                    <span
                      className="text-[10px] text-muted-foreground font-mono"
                      title={`作成: ${item.created_by}`}
                    >
                      by {item.created_by}
                    </span>
                  )}
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
