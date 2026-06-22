"use client";

import { Badge } from "@/components/ui/badge";

/**
 * 装置 PC から戻った実験者の「ちゃんと記録できたか?」確認を 5 秒で済ますための
 * sticky 行。各 chip クリックで該当カードへ smooth scroll する。
 *
 * 充足率: template 紐付き record では `required_*` の埋まり具合を併記。
 * 未投入カテゴリは灰色 + 「未投入」表示で「漏れ」を即座に可視化する。
 *
 * 配置側 (record 詳細ページ) は各 Card に id を振る:
 *   - section-conditions / section-results / section-files
 *   - section-notes / section-children
 */

type SectionKind =
  | "conditions"
  | "results"
  | "files"
  | "notes"
  | "children";

interface SectionSummary {
  kind: SectionKind;
  label: string;
  total: number;
  // template が要求する必須 key の数 (なければ 0 = 充足表示なし)
  requiredTotal?: number;
  // そのうち実際に埋まっている数
  requiredFilled?: number;
}

function smoothScrollTo(id: string) {
  const el = document.getElementById(id);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "start" });
}

function Chip({ section }: { section: SectionSummary }) {
  const { kind, label, total, requiredTotal, requiredFilled } = section;
  const empty = total === 0;
  const hasRequired = (requiredTotal ?? 0) > 0;
  const understocked =
    hasRequired && (requiredFilled ?? 0) < (requiredTotal ?? 0);

  // 状態別の見た目:
  //   empty   → 灰色 + 「未投入」
  //   underst → 黄色アクセント + ratio
  //   通常    → 標準 outline
  const className = empty
    ? "text-muted-foreground/70 border-muted bg-muted/30"
    : understocked
      ? "border-amber-300 text-amber-800 bg-amber-50"
      : "border-slate-200 text-slate-700";

  const ratio = hasRequired ? ` ${requiredFilled}/${requiredTotal} 必須` : "";

  return (
    <Badge
      variant="outline"
      onClick={empty ? undefined : () => smoothScrollTo(`section-${kind}`)}
      className={`text-xs ${className} ${empty ? "" : "cursor-pointer hover:brightness-95"}`}
      title={
        empty
          ? `${label} は未投入`
          : understocked
            ? `${label}: 必須項目が ${
                (requiredTotal ?? 0) - (requiredFilled ?? 0)
              } 件未入力`
            : `${label}: ${total} 件`
      }
    >
      {understocked && "⚠ "}
      {label} {total}
      {ratio}
      {empty && " 未投入"}
    </Badge>
  );
}

export function SummaryChips({
  conditionsCount,
  resultsCount,
  filesCount,
  notesCount,
  childrenCount,
  conditionKeys = [],
  resultKeys = [],
  requiredConditions = [],
  requiredResults = [],
}: {
  conditionsCount: number;
  resultsCount: number;
  filesCount: number;
  notesCount: number;
  childrenCount: number;
  // 実際の record に入っている key (required 充足判定に使う)
  conditionKeys?: string[];
  resultKeys?: string[];
  // template が要求する必須 key の一覧
  requiredConditions?: string[];
  requiredResults?: string[];
}) {
  // required の充足カウント (record の key が required リストにあるか)。
  const condFilledCount = requiredConditions.filter((k) =>
    conditionKeys.includes(k),
  ).length;
  const resFilledCount = requiredResults.filter((k) =>
    resultKeys.includes(k),
  ).length;

  const sections: SectionSummary[] = [
    {
      kind: "conditions",
      label: "条件",
      total: conditionsCount,
      requiredTotal: requiredConditions.length,
      requiredFilled: condFilledCount,
    },
    {
      kind: "results",
      label: "結果",
      total: resultsCount,
      requiredTotal: requiredResults.length,
      requiredFilled: resFilledCount,
    },
    { kind: "files", label: "ファイル", total: filesCount },
    { kind: "notes", label: "メモ", total: notesCount },
    { kind: "children", label: "子", total: childrenCount },
  ];

  return (
    <div
      className="sticky top-0 z-20 -mx-2 px-2 py-2 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80 border-b border-border/40 flex items-center gap-2 flex-wrap"
      role="navigation"
      aria-label="レコードサマリ (クリックで該当セクションへ)"
    >
      {sections.map((s) => (
        <Chip key={s.kind} section={s} />
      ))}
    </div>
  );
}
