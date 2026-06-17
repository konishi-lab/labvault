"use client";

import { useState } from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { RecordSummary } from "@/lib/api";
import { downloadCsv, toCsv, todayStamp } from "@/lib/csv";

const statusColor: Record<string, string> = {
  running: "bg-blue-100 text-blue-800",
  success: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  partial: "bg-yellow-100 text-yellow-800",
};

function formatDate(iso: string): string {
  // 年を含めて表示。MDG 移行などで数年前のレコードが混ざるとき、年が
  // 無いと判別不能になるため。
  return new Date(iso).toLocaleDateString("ja-JP", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function naturalSortKey(s: string): string {
  return s.replace(/(\d+)/g, (m) => m.padStart(10, "0")).toLowerCase();
}

type SortDir = "asc" | "desc";

export function SortableRecordTable({
  records,
  defaultSort = "title",
  conditionsMap,
  conditionColumns,
  availableConditionKeys,
  onColumnsChange,
  pageSize = 50,
  currentUserEmail,
}: {
  records: RecordSummary[];
  defaultSort?: string;
  conditionsMap?: Map<string, Record<string, unknown>>;
  conditionColumns?: string[];
  availableConditionKeys?: string[];
  onColumnsChange?: (cols: string[]) => void;
  pageSize?: number;
  // 自分の created_by と一致する row に薄いハイライト + 「自分」バッジ。
  currentUserEmail?: string | null;
}) {
  const [sortKey, setSortKey] = useState(defaultSort);
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [showColumnPicker, setShowColumnPicker] = useState(false);
  const [page, setPage] = useState(0);

  const cols = conditionColumns || [];
  const available = availableConditionKeys || [];

  if (records.length === 0) {
    return (
      <p className="py-8 text-center text-muted-foreground">
        レコードがありません
      </p>
    );
  }

  const getCondValue = (recId: string, key: string): unknown => {
    return conditionsMap?.get(recId)?.[key];
  };

  const sorted = [...records].sort((a, b) => {
    let va: string | number;
    let vb: string | number;

    if (cols.includes(sortKey)) {
      const rawA = getCondValue(a.id, sortKey);
      const rawB = getCondValue(b.id, sortKey);
      va = typeof rawA === "number" ? rawA : String(rawA ?? "");
      vb = typeof rawB === "number" ? rawB : String(rawB ?? "");
    } else if (sortKey === "title") {
      va = naturalSortKey(a.title);
      vb = naturalSortKey(b.title);
    } else if (sortKey === "id") {
      va = a.id;
      vb = b.id;
    } else if (sortKey === "type") {
      va = a.type;
      vb = b.type;
    } else if (sortKey === "status") {
      va = a.status;
      vb = b.status;
    } else {
      va = a.created_at;
      vb = b.created_at;
    }
    const cmp = va < vb ? -1 : va > vb ? 1 : 0;
    return sortDir === "asc" ? cmp : -cmp;
  });

  // ページネーション（ソート後に適用）
  const usePaging = pageSize && sorted.length > pageSize;
  const totalPages = usePaging ? Math.ceil(sorted.length / pageSize) : 1;
  const safePage = Math.min(page, totalPages - 1);
  const paged = usePaging
    ? sorted.slice(safePage * pageSize, (safePage + 1) * pageSize)
    : sorted;

  const toggle = (key: string) => {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
    setPage(0);
  };

  const arrow = (key: string) =>
    sortKey === key ? (sortDir === "asc" ? " ↑" : " ↓") : "";

  const headClass =
    "cursor-pointer hover:text-foreground select-none transition-colors";

  // 「コピーしました」を 2 秒だけ表示する feedback。
  const [copiedAt, setCopiedAt] = useState<number | null>(null);
  const copyJustNow = copiedAt && Date.now() - copiedAt < 2000;

  const handleCopyIds = async () => {
    const text = records.map((r) => r.id).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopiedAt(Date.now());
      setTimeout(() => setCopiedAt(null), 2000);
    } catch {
      // clipboard 不可 (古いブラウザ / iframe) のときは select 用 textarea fallback
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        setCopiedAt(Date.now());
        setTimeout(() => setCopiedAt(null), 2000);
      } catch {
        // 何もできない
      }
      ta.remove();
    }
  };

  const handleDownloadCsv = () => {
    // 現在表示中の records を、SDK で扱いやすい columns に絞って出力。
    // 条件カラムや結果カラムを足したい場合は将来拡張するが、まず最小限。
    const headers = [
      "id",
      "title",
      "type",
      "status",
      "created_by",
      "created_at",
      "updated_at",
      "parent_id",
    ];
    const rows = records.map((r) => [
      r.id,
      r.title,
      r.type,
      r.status,
      r.created_by,
      r.created_at,
      r.updated_at,
      r.parent_id ?? "",
    ]);
    const csv = toCsv(headers, rows);
    downloadCsv(`labvault-records-${todayStamp()}.csv`, csv);
  };

  return (
    <div className="space-y-2">
      {/* エクスポート toolbar */}
      <div className="flex items-center gap-2 text-xs">
        <Button
          variant="outline"
          size="xs"
          onClick={handleDownloadCsv}
          title="表示中のレコード一覧を CSV でダウンロード (Excel 日本語対応)"
        >
          CSV ダウンロード
        </Button>
        <Button
          variant="outline"
          size="xs"
          onClick={handleCopyIds}
          title="表示中のレコード ID を改行区切りでコピー (Notebook の lab.get_many([...]) 等で貼り付け想定)"
        >
          {copyJustNow ? "✓ コピーしました" : "ID 一覧コピー"}
        </Button>
        <span className="text-muted-foreground ml-auto">
          {records.length} 件
        </span>
      </div>

      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead
                className={`w-20 ${headClass}`}
                onClick={() => toggle("id")}
              >
                ID{arrow("id")}
              </TableHead>
              <TableHead className={headClass} onClick={() => toggle("title")}>
                タイトル{arrow("title")}
              </TableHead>
              {cols.map((key) => (
                <TableHead
                  key={key}
                  className={`${headClass} text-right`}
                  onClick={() => toggle(key)}
                >
                  {key}
                  {arrow(key)}
                </TableHead>
              ))}
              <TableHead
                className={`w-24 ${headClass}`}
                onClick={() => toggle("status")}
              >
                ステータス{arrow("status")}
              </TableHead>
              <TableHead
                className={`w-36 ${headClass}`}
                onClick={() => toggle("created_at")}
              >
                作成日{arrow("created_at")}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {paged.map((rec) => {
              const isMine =
                !!currentUserEmail && rec.created_by === currentUserEmail;
              return (
              <TableRow
                key={rec.id}
                className={`cursor-pointer hover:bg-muted/50 ${
                  isMine ? "bg-blue-50/40" : ""
                }`}
              >
                <TableCell className="font-mono font-semibold">
                  <div className="flex items-center gap-1.5">
                    <Link
                      href={`/records/${rec.id}`}
                      className="text-primary hover:underline"
                    >
                      {rec.id}
                    </Link>
                    {isMine && (
                      <span
                        className="text-[10px] text-blue-700 bg-blue-100 rounded px-1 py-0.5"
                        title={`自分 (${currentUserEmail}) が作成`}
                      >
                        自分
                      </span>
                    )}
                  </div>
                </TableCell>
                <TableCell className="max-w-[40ch]">
                  <Link
                    href={`/records/${rec.id}`}
                    className="block truncate hover:underline"
                    title={rec.title}
                  >
                    {rec.title}
                  </Link>
                </TableCell>
                {cols.map((key) => {
                  const val = getCondValue(rec.id, key);
                  return (
                    <TableCell
                      key={key}
                      className="font-mono text-xs text-right"
                    >
                      {val !== undefined ? String(val) : "-"}
                    </TableCell>
                  );
                })}
                <TableCell>
                  <Badge
                    variant="secondary"
                    className={statusColor[rec.status]}
                  >
                    {rec.status}
                  </Badge>
                </TableCell>
                <TableCell className="text-muted-foreground text-sm">
                  {formatDate(rec.created_at)}
                </TableCell>
              </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      {/* ページネーション */}
      {usePaging && (
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">
            {safePage * pageSize + 1}-
            {Math.min((safePage + 1) * pageSize, sorted.length)} /{" "}
            {sorted.length}
          </span>
          <div className="flex gap-1">
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs cursor-pointer"
              disabled={safePage === 0}
              onClick={() => setPage(safePage - 1)}
            >
              前へ
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs cursor-pointer"
              disabled={safePage >= totalPages - 1}
              onClick={() => setPage(safePage + 1)}
            >
              次へ
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
