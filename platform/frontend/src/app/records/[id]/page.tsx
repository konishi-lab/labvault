"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchRecord } from "@/lib/api";
import type { RecordDetail } from "@/lib/api";

const statusColor: Record<string, string> = {
  running: "bg-blue-100 text-blue-800",
  success: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  partial: "bg-yellow-100 text-yellow-800",
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("ja-JP");
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

export default function RecordDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [record, setRecord] = useState<RecordDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchRecord(id)
      .then(setRecord)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (error || !record) {
    return (
      <div className="space-y-4">
        <Link href="/">
          <Button variant="ghost" className="cursor-pointer">
            ← 一覧に戻る
          </Button>
        </Link>
        <p className="text-destructive">
          {error || "レコードが見つかりません"}
        </p>
      </div>
    );
  }

  const conditions = Object.entries(record.conditions);
  const results = Object.entries(record.results);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link href="/">
          <Button variant="ghost" className="cursor-pointer">
            ← 一覧
          </Button>
        </Link>
        <h1 className="text-2xl font-bold tracking-tight">{record.title}</h1>
        <Badge variant="secondary" className={statusColor[record.status]}>
          {record.status}
        </Badge>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* 基本情報 */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">基本情報</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">ID</span>
              <span className="font-mono font-semibold">{record.id}</span>
            </div>
            <Separator />
            <div className="flex justify-between">
              <span className="text-muted-foreground">タイプ</span>
              <span>{record.type}</span>
            </div>
            <Separator />
            <div className="flex justify-between">
              <span className="text-muted-foreground">作成者</span>
              <span>{record.created_by || "-"}</span>
            </div>
            <Separator />
            <div className="flex justify-between">
              <span className="text-muted-foreground">作成日</span>
              <span>{formatDate(record.created_at)}</span>
            </div>
            <Separator />
            <div className="flex justify-between">
              <span className="text-muted-foreground">更新日</span>
              <span>{formatDate(record.updated_at)}</span>
            </div>
            {record.tags.length > 0 && (
              <>
                <Separator />
                <div className="flex justify-between items-start">
                  <span className="text-muted-foreground">タグ</span>
                  <div className="flex flex-wrap gap-1 justify-end">
                    {record.tags.map((tag) => (
                      <Badge key={tag} variant="outline" className="text-xs">
                        {tag}
                      </Badge>
                    ))}
                  </div>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* 条件 */}
        {conditions.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">条件</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              {conditions.map(([key, value], i) => (
                <div key={key}>
                  {i > 0 && <Separator className="mb-2" />}
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">{key}</span>
                    <span className="font-mono">{String(value)}</span>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        )}

        {/* 結果 */}
        {results.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">結果</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              {results.map(([key, value], i) => (
                <div key={key}>
                  {i > 0 && <Separator className="mb-2" />}
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">{key}</span>
                    <span className="font-mono">{String(value)}</span>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        )}

        {/* ファイル */}
        {record.files.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">ファイル</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              {record.files.map((file, i) => (
                <div key={file.name}>
                  {i > 0 && <Separator className="mb-2" />}
                  <div className="flex justify-between">
                    <span className="font-mono">{file.name}</span>
                    <span className="text-muted-foreground">
                      {formatBytes(file.size_bytes)}
                    </span>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        )}

        {/* メモ */}
        {record.notes.length > 0 && (
          <Card className="md:col-span-2">
            <CardHeader>
              <CardTitle className="text-base">メモ</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              {record.notes.map((note, i) => (
                <div key={i} className="flex gap-3">
                  <span className="shrink-0 text-muted-foreground text-xs">
                    {formatDate(note.created_at)}
                  </span>
                  <span>{note.text}</span>
                </div>
              ))}
            </CardContent>
          </Card>
        )}

        {/* リンク */}
        {record.links.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">リンク</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              {record.links.map((link, i) => (
                <div key={i}>
                  {i > 0 && <Separator className="mb-2" />}
                  <div className="flex justify-between">
                    <Link
                      href={`/records/${link.target_id}`}
                      className="font-mono text-primary hover:underline cursor-pointer"
                    >
                      {link.target_id}
                    </Link>
                    <span className="text-muted-foreground">
                      {link.relation}
                    </span>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
