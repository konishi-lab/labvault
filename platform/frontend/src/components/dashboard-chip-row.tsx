"use client";

import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import type { DashboardSummary } from "@/lib/dashboard";

// D5: ホームの 3 chip 行。`/api/records?limit=200` を frontend 集計した
// `DashboardSummary` を受け取って描画する pure component。
//
// 各 chip は全体クリックで `/records` の絞り込み済 URL に飛ぶ tap target
// (mobile 44px 確保)。chip 高さは `min-h-[88px]` で揃え、C3 が短い場合も
// 段差が出ない。

function _fmtDelta(delta: number, deltaPct: number | null): string {
  if (delta === 0) return "先週と同じ";
  const sign = delta > 0 ? "+" : "";
  const arrow = delta > 0 ? "▲" : "▼";
  const pct = deltaPct === null ? "" : ` ${arrow} ${Math.abs(deltaPct)}%`;
  return `先週比 ${sign}${delta}${pct}`;
}

function ChipShell({
  href,
  title,
  children,
  truncated,
  truncatedHint,
}: {
  href: string;
  title: string;
  children: React.ReactNode;
  truncated?: boolean;
  truncatedHint?: string;
}) {
  return (
    <Link href={href} className="group">
      <Card className="h-full min-h-[88px] transition-colors hover:border-primary/40 hover:bg-muted/30">
        <CardContent className="p-4 space-y-2">
          <div className="text-xs text-muted-foreground group-hover:text-foreground">
            {title}
          </div>
          {children}
          {truncated && truncatedHint && (
            <div className="text-[10px] text-amber-700/80">
              ⚠ {truncatedHint}
            </div>
          )}
        </CardContent>
      </Card>
    </Link>
  );
}

export function DashboardChipRow({
  summary,
}: {
  summary: DashboardSummary;
}) {
  const { weekly, status30d, templatesThisWeek, truncated } = summary;

  return (
    <div className="grid gap-3 grid-cols-1 sm:grid-cols-3">
      {/* C1: 今週件数 + 先週比 */}
      <ChipShell
        href="/records"
        title="今週投入された record"
        truncated={truncated}
        truncatedHint="200 件で打ち切り (本来はもっと多い)"
      >
        <div className="text-2xl font-semibold tabular-nums">
          {weekly.thisWeek} 件
        </div>
        <div className="text-xs text-muted-foreground">
          {_fmtDelta(weekly.delta, weekly.deltaPct)}
        </div>
      </ChipShell>

      {/* C2: 直近 30 日 status 内訳 */}
      <ChipShell href="/records" title="直近 30 日の status">
        <div className="text-2xl font-semibold tabular-nums flex items-baseline gap-3">
          <span title={`success: ${status30d.done}`}>
            <span className="text-emerald-700">✓</span> {status30d.done}
          </span>
          <span title={`running: ${status30d.running}`}>
            <span className="text-sky-700">▶</span> {status30d.running}
          </span>
          <span title={`failed: ${status30d.failed}`}>
            <span className="text-red-700">✗</span> {status30d.failed}
          </span>
        </div>
        <div className="text-xs text-muted-foreground">
          計 {status30d.total} 件
          {status30d.other > 0 && ` (他 ${status30d.other})`}
        </div>
      </ChipShell>

      {/* C3: 今週の template 上位 3 */}
      <ChipShell href="/records" title="今週の測定内訳 (template)">
        {templatesThisWeek.length === 0 ? (
          <div className="text-sm text-muted-foreground">今週はまだなし</div>
        ) : (
          <div className="space-y-1">
            {templatesThisWeek.map((t) => {
              const max = templatesThisWeek[0].count;
              const widthPct = max > 0 ? Math.round((t.count / max) * 100) : 0;
              return (
                <div key={t.name} className="flex items-center gap-2 text-xs">
                  <div
                    className="font-mono truncate max-w-[6rem]"
                    title={t.name}
                  >
                    {t.name}
                  </div>
                  <div className="flex-1 h-2 bg-muted rounded overflow-hidden">
                    <div
                      className="h-full bg-primary/60"
                      style={{ width: `${widthPct}%` }}
                    />
                  </div>
                  <div className="tabular-nums w-6 text-right">{t.count}</div>
                </div>
              );
            })}
          </div>
        )}
      </ChipShell>
    </div>
  );
}

// 0 件 team 向けの onboarding カード。3 chip を空のまま並べると新 team に
// 冷たい印象を与えるので、ChipRow の代わりに 1 枚の誘導カードを出す。
export function DashboardOnboarding() {
  return (
    <Card className="border-dashed">
      <CardContent className="p-6 text-center space-y-3">
        <div className="text-sm font-medium">
          まだレコードがありません
        </div>
        <p className="text-xs text-muted-foreground">
          SDK で <code className="rounded bg-muted px-1 py-0.5">lab.new(...)</code>{" "}
          するか、Web UI から一括投入してみてください。
        </p>
        <div className="flex items-center justify-center gap-2">
          <Link
            href="/welcome"
            className="text-xs text-primary underline-offset-2 hover:underline"
          >
            SDK の使い方を見る →
          </Link>
          <span className="text-muted-foreground">·</span>
          <Link
            href="/records"
            className="text-xs text-primary underline-offset-2 hover:underline"
          >
            一括投入を試す →
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}
