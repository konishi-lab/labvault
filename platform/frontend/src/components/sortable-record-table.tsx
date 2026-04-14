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

const statusColor: Record<string, string> = {
  running: "bg-blue-100 text-blue-800",
  success: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  partial: "bg-yellow-100 text-yellow-800",
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ja-JP", {
    month: "short",
    day: "numeric",
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
  pageSize,
}: {
  records: RecordSummary[];
  defaultSort?: string;
  conditionsMap?: Map<string, Record<string, unknown>>;
  conditionColumns?: string[];
  availableConditionKeys?: string[];
  onColumnsChange?: (cols: string[]) => void;
  pageSize?: number;
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

  const toggleColumn = (key: string) => {
    if (!onColumnsChange) return;
    if (cols.includes(key)) {
      onColumnsChange(cols.filter((c) => c !== key));
    } else {
      onColumnsChange([...cols, key]);
    }
  };

  return (
    <div className="space-y-2">
      {/* カラム選択 */}
      {available.length > 0 && onColumnsChange && (
        <div className="flex items-center gap-2 flex-wrap">
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs cursor-pointer"
            onClick={() => setShowColumnPicker(!showColumnPicker)}
          >
            条件カラム {cols.length > 0 ? `(${cols.length})` : ""}
          </Button>
          {showColumnPicker && (
            <div className="flex flex-wrap gap-1">
              {available.map((key) => (
                <Badge
                  key={key}
                  variant={cols.includes(key) ? "default" : "outline"}
                  className="text-xs cursor-pointer"
                  onClick={() => toggleColumn(key)}
                >
                  {key}
                </Badge>
              ))}
            </div>
          )}
        </div>
      )}

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
            {paged.map((rec) => (
              <TableRow
                key={rec.id}
                className="cursor-pointer hover:bg-muted/50"
              >
                <TableCell className="font-mono font-semibold">
                  <Link
                    href={`/records/${rec.id}`}
                    className="text-primary hover:underline"
                  >
                    {rec.id}
                  </Link>
                </TableCell>
                <TableCell>
                  <Link href={`/records/${rec.id}`} className="hover:underline">
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
            ))}
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
