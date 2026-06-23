// ダッシュボード集計 (D5)。`/api/records?limit=200` の生レスポンス
// (`RecordSummary[]`) からクライアント集計のみで PI 用 3 chip を作る。
// backend 集計 endpoint は Phase C の検討対象 (戦略案 #6 Phase D)
// なのでここでは frontend 集計に閉じる。

import type { RecordSummary } from "@/lib/api";

const DAY_MS = 24 * 60 * 60 * 1000;
const WEEK_MS = 7 * DAY_MS;
const MONTH_MS = 30 * DAY_MS;

export interface WeeklyCount {
  thisWeek: number;
  lastWeek: number;
  delta: number;
  deltaPct: number | null; // 先週 0 件のときは null (∞ を出さない)
}

export interface StatusBreakdown {
  // 成功 / 進行中 / 失敗 (それ以外は other に丸める)。
  done: number;
  running: number;
  failed: number;
  other: number;
  total: number;
}

export interface TemplateBar {
  name: string;
  count: number;
}

export interface DashboardSummary {
  // C1: 今週件数 + 先週比
  weekly: WeeklyCount;
  // C2: 直近 30 日の status 内訳
  status30d: StatusBreakdown;
  // C3: 今週の template 上位 3 (template 未紐付きは "(未紐付け)")
  templatesThisWeek: TemplateBar[];
  // limit=200 で打ち切られた可能性 (chip に「+N 件あり」を出すか判定)
  truncated: boolean;
}

function _ts(iso: string): number {
  // 不正な ISO は 0 にして「無効レコード」として無視 (epoch 開始 ≠ 今)
  const t = new Date(iso).getTime();
  return Number.isFinite(t) ? t : 0;
}

export function computeDashboard(
  records: RecordSummary[],
  hasMore: boolean,
  nowMs: number = Date.now(),
): DashboardSummary {
  // C1: 今週・先週
  let thisWeek = 0;
  let lastWeek = 0;
  for (const r of records) {
    const age = nowMs - _ts(r.created_at);
    if (age < WEEK_MS) thisWeek++;
    else if (age < 2 * WEEK_MS) lastWeek++;
  }
  const delta = thisWeek - lastWeek;
  const deltaPct =
    lastWeek === 0 ? null : Math.round((delta / lastWeek) * 100);

  // C2: 直近 30 日 status 内訳
  const status30d: StatusBreakdown = {
    done: 0,
    running: 0,
    failed: 0,
    other: 0,
    total: 0,
  };
  for (const r of records) {
    const age = nowMs - _ts(r.created_at);
    if (age >= MONTH_MS) continue;
    status30d.total++;
    const s = r.status;
    if (s === "success" || s === "done") status30d.done++;
    else if (s === "running") status30d.running++;
    else if (s === "failed") status30d.failed++;
    else status30d.other++;
  }

  // C3: 今週の template 上位 3
  const tmpl: Map<string, number> = new Map();
  for (const r of records) {
    if (nowMs - _ts(r.created_at) >= WEEK_MS) continue;
    const name = r.template_name?.trim() || "(未紐付け)";
    tmpl.set(name, (tmpl.get(name) ?? 0) + 1);
  }
  const templatesThisWeek = [...tmpl.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 3);

  return {
    weekly: { thisWeek, lastWeek, delta, deltaPct },
    status30d,
    templatesThisWeek,
    truncated: hasMore,
  };
}
