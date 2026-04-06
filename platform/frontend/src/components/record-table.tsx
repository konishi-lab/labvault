"use client";

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

export function RecordTable({ records }: { records: RecordSummary[] }) {
  if (records.length === 0) {
    return (
      <p className="py-8 text-center text-muted-foreground">
        レコードがありません
      </p>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-20">ID</TableHead>
          <TableHead>タイトル</TableHead>
          <TableHead className="w-28">タイプ</TableHead>
          <TableHead className="w-24">ステータス</TableHead>
          <TableHead>タグ</TableHead>
          <TableHead className="w-32">作成日</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {records.map((rec) => (
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
