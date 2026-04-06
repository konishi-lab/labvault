"use client";

import { useState } from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
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

type SortKey = "id" | "title" | "type" | "status" | "created_at";
type SortDir = "asc" | "desc";

export function SortableRecordTable({
  records,
  defaultSort = "title",
}: {
  records: RecordSummary[];
  defaultSort?: SortKey;
}) {
  const [sortKey, setSortKey] = useState<SortKey>(defaultSort);
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  if (records.length === 0) {
    return (
      <p className="py-8 text-center text-muted-foreground">
        レコードがありません
      </p>
    );
  }

  const sorted = [...records].sort((a, b) => {
    let va: string;
    let vb: string;
    if (sortKey === "title") {
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

  const toggle = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const arrow = (key: SortKey) =>
    sortKey === key ? (sortDir === "asc" ? " ↑" : " ↓") : "";

  const headClass =
    "cursor-pointer hover:text-foreground select-none transition-colors";

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className={`w-20 ${headClass}`} onClick={() => toggle("id")}>
            ID{arrow("id")}
          </TableHead>
          <TableHead className={headClass} onClick={() => toggle("title")}>
            タイトル{arrow("title")}
          </TableHead>
          <TableHead className={`w-28 ${headClass}`} onClick={() => toggle("type")}>
            タイプ{arrow("type")}
          </TableHead>
          <TableHead className={`w-24 ${headClass}`} onClick={() => toggle("status")}>
            ステータス{arrow("status")}
          </TableHead>
          <TableHead>タグ</TableHead>
          <TableHead className={`w-36 ${headClass}`} onClick={() => toggle("created_at")}>
            作成日{arrow("created_at")}
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sorted.map((rec) => (
          <TableRow key={rec.id} className="cursor-pointer hover:bg-muted/50">
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
            <TableCell className="text-muted-foreground">{rec.type}</TableCell>
            <TableCell>
              <Badge variant="secondary" className={statusColor[rec.status]}>
                {rec.status}
              </Badge>
            </TableCell>
            <TableCell>
              <div className="flex flex-wrap gap-1">
                {rec.tags.map((tag) => (
                  <Badge key={tag} variant="outline" className="text-xs">
                    {tag}
                  </Badge>
                ))}
              </div>
            </TableCell>
            <TableCell className="text-muted-foreground text-sm">
              {formatDate(rec.created_at)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
