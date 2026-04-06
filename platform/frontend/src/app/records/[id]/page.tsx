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
import { fetchRecord, fetchChildren } from "@/lib/api";
import type { RecordDetail, RecordSummary } from "@/lib/api";

const statusColor: Record<string, string> = {
  running: "bg-blue-100 text-blue-800",
  success: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  partial: "bg-yellow-100 text-yellow-800",
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("ja-JP");
}

function fileExt(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot + 1).toUpperCase() : "FILE";
}

function fileIcon(name: string): string {
  const ext = fileExt(name).toLowerCase();
  const icons: Record<string, string> = {
    vk4: "\u{1F52C}", // 🔬 microscope
    csv: "\u{1F4CA}", // 📊
    json: "\u{1F4C4}", // 📄
    txt: "\u{1F4DD}", // 📝
    npy: "\u{1F522}", // 🔢
    png: "\u{1F5BC}", // 🖼
    jpg: "\u{1F5BC}",
    tif: "\u{1F5BC}",
    tiff: "\u{1F5BC}",
    ras: "\u{1F4C8}", // 📈
  };
  return icons[ext] || "\u{1F4CE}"; // 📎 default
}

function fileTypeBadge(name: string): string {
  const ext = fileExt(name).toLowerCase();
  const styles: Record<string, string> = {
    vk4: "bg-purple-100 text-purple-800 border-purple-200",
    csv: "bg-green-100 text-green-800 border-green-200",
    json: "bg-blue-100 text-blue-800 border-blue-200",
    npy: "bg-orange-100 text-orange-800 border-orange-200",
    png: "bg-pink-100 text-pink-800 border-pink-200",
    jpg: "bg-pink-100 text-pink-800 border-pink-200",
    ras: "bg-indigo-100 text-indigo-800 border-indigo-200",
  };
  return styles[ext] || "";
}

function isPreviewable(name: string): boolean {
  return name.toLowerCase().endsWith(".vk4");
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function Vk4Preview({
  recordId,
  filename,
}: {
  recordId: string;
  filename: string;
}) {
  const [status, setStatus] = useState<"loading" | "loaded" | "error">(
    "loading"
  );
  const url = `${API_BASE}/api/records/${recordId}/preview/${encodeURIComponent(filename)}`;

  return (
    <div className="rounded-lg border bg-muted/30 p-2">
      {status === "loading" && (
        <Skeleton className="h-48 w-full rounded" />
      )}
      {status === "error" && (
        <p className="py-4 text-center text-xs text-muted-foreground">
          プレビューを読み込めません
        </p>
      )}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={url}
        alt={filename}
        className={`max-h-96 rounded ${status !== "loaded" ? "hidden" : ""}`}
        onLoad={() => setStatus("loaded")}
        onError={() => setStatus("error")}
      />
    </div>
  );
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
  const [children, setChildren] = useState<RecordSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetchRecord(id),
      fetchChildren(id).catch(() => []),
    ])
      .then(([rec, kids]) => {
        setRecord(rec);
        setChildren(kids);
      })
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
          <Card className="md:col-span-2">
            <CardHeader>
              <CardTitle className="text-base">
                ファイル ({record.files.length})
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              {record.files.map((file, i) => (
                <div key={file.name}>
                  {i > 0 && <Separator className="mb-3" />}
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="shrink-0">{fileIcon(file.name)}</span>
                      <span className="font-mono truncate">{file.name}</span>
                      <Badge
                        variant="outline"
                        className={`shrink-0 text-xs ${fileTypeBadge(file.name)}`}
                      >
                        {fileExt(file.name)}
                      </Badge>
                    </div>
                    <span className="shrink-0 text-muted-foreground">
                      {file.size_bytes > 0
                        ? formatBytes(file.size_bytes)
                        : ""}
                    </span>
                  </div>
                  {isPreviewable(file.name) && (
                    <div className="mt-2">
                      <Vk4Preview recordId={id} filename={file.name} />
                    </div>
                  )}
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

        {/* サブレコード */}
        {children.length > 0 && (
          <ChildrenSection children={children} />
        )}
      </div>
    </div>
  );
}

type SortKey = "title" | "created_at";
type SortDir = "asc" | "desc";

function ChildrenSection({ children }: { children: RecordSummary[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("title");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const sorted = [...children].sort((a, b) => {
    const va = sortKey === "title" ? a.title : a.created_at;
    const vb = sortKey === "title" ? b.title : b.created_at;
    const cmp = va < vb ? -1 : va > vb ? 1 : 0;
    return sortDir === "asc" ? cmp : -cmp;
  });

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const arrow = (key: SortKey) =>
    sortKey === key ? (sortDir === "asc" ? " ↑" : " ↓") : "";

  return (
          <Card className="md:col-span-2">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">
                  サブレコード ({children.length})
                </CardTitle>
                <div className="flex gap-1">
                  <Button
                    variant={sortKey === "title" ? "default" : "outline"}
                    size="sm"
                    className="h-7 text-xs cursor-pointer"
                    onClick={() => toggleSort("title")}
                  >
                    名前{arrow("title")}
                  </Button>
                  <Button
                    variant={sortKey === "created_at" ? "default" : "outline"}
                    size="sm"
                    className="h-7 text-xs cursor-pointer"
                    onClick={() => toggleSort("created_at")}
                  >
                    作成日{arrow("created_at")}
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              {sorted.map((child, i) => (
                <div key={child.id}>
                  {i > 0 && <Separator className="mb-2" />}
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <Link
                        href={`/records/${child.id}`}
                        className="font-mono text-primary hover:underline cursor-pointer"
                      >
                        {child.id}
                      </Link>
                      <Link
                        href={`/records/${child.id}`}
                        className="hover:underline cursor-pointer"
                      >
                        {child.title}
                      </Link>
                    </div>
                    <Badge
                      variant="secondary"
                      className={statusColor[child.status]}
                    >
                      {child.status}
                    </Badge>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
  );
}
