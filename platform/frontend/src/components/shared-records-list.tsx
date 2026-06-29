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

const ROLE_LABEL: Record<string, string> = {
  viewer: "閲覧",
  analyst: "解析",
};

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
    // S1-UX1 hot-fix (2026-06-29): 切替判定は **currentTeam との差分** で行う。
    //
    // 旧実装は `if (!myTeamIds.has(item.team))` で『自 team の所属判定』を
    // 使っていた。これだと teams=[A,B] / currentTeam=A の user が team B の
    // 共有 record をクリックしても切り替わらず (B も myTeamIds に含まれるため)、
    // 詳細ページで X-Labvault-Team: A のまま record(team=B) を lookup して
    // 404 になっていた。
    //
    // 正しくは『現 header と違う team の record なら切り替える』。これで
    // 自 team / 他 team いずれも構造的に同じ挙動になる。
    // 自分の所属していない team へ切替える場合は useAuth の setCurrentTeam が
    // localStorage にも保存するため、戻った後も同じ team で表示が続く点に
    // 注意 (team selector で手動で戻す)。Phase 2 で `?team=X` override 方式
    // を検討予定。
    if (item.team && item.team !== currentTeam) {
      setCurrentTeam(item.team);
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
                    {ROLE_LABEL[item.role] ?? item.role}
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
