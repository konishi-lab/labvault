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
import { fetchRecord, fetchChildren, fetchChildrenConditions } from "@/lib/api";
import type { RecordDetail, RecordSummary } from "@/lib/api";
import { BulkUploadButton } from "@/components/bulk-upload";
import { SortableRecordTable } from "@/components/sortable-record-table";
import { TagEditor } from "@/components/tag-editor";
import { NoteForm } from "@/components/note-form";
import { ConditionsCard } from "@/components/conditions-card";
import { ResultsCard } from "@/components/results-card";
import { ConditionFilterPanel } from "@/components/condition-filter";
import type { ConditionFilter } from "@/components/condition-filter";
import { ConditionScatterChart } from "@/components/scatter-chart";
import type { NoteResponse } from "@/lib/api";

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

function previewType(name: string): "vk4" | "image" | null {
  const lower = name.toLowerCase();
  if (lower.endsWith(".vk4")) return "vk4";
  if (lower.endsWith(".png") || lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image";
  return null;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function imageUrl(recordId: string, filename: string): string {
  const ptype = previewType(filename);
  return ptype === "vk4"
    ? `${API_BASE}/api/records/${recordId}/preview/${encodeURIComponent(filename)}`
    : `${API_BASE}/api/records/${recordId}/files/${encodeURIComponent(filename)}`;
}

function ImageThumbnail({
  recordId,
  filename,
  label,
  onClickExpand,
}: {
  recordId: string;
  filename: string;
  label?: string;
  onClickExpand?: () => void;
}) {
  const [status, setStatus] = useState<"loading" | "loaded" | "error">(
    "loading"
  );
  const url = imageUrl(recordId, filename);

  return (
    <div
      className="relative rounded-lg border bg-muted/30 p-1 cursor-pointer hover:ring-2 hover:ring-primary/30 transition-all"
      onClick={onClickExpand}
    >
      {status === "loading" && <Skeleton className="h-40 w-full rounded" />}
      {status === "error" && (
        <p className="h-40 flex items-center justify-center text-xs text-muted-foreground">
          読み込めません
        </p>
      )}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={url}
        alt={filename}
        className={`w-full h-40 object-contain rounded ${status === "loaded" ? "" : "absolute opacity-0 pointer-events-none"}`}
        onLoad={() => setStatus("loaded")}
        onError={() => setStatus("error")}
      />
      {label && (
        <p className="text-xs text-center text-muted-foreground mt-1 truncate">
          {label}
        </p>
      )}
    </div>
  );
}

function ImageModal({
  recordId,
  filename,
  onClose,
}: {
  recordId: string;
  filename: string;
  onClose: () => void;
}) {
  const url = imageUrl(recordId, filename);
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70"
      onClick={onClose}
    >
      <div className="relative max-w-[90vw] max-h-[90vh]">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={url} alt={filename} className="max-w-full max-h-[90vh] rounded-lg" />
        <p className="absolute bottom-2 left-2 text-xs text-white/80 bg-black/50 px-2 py-1 rounded">
          {filename}
        </p>
      </div>
    </div>
  );
}

function FileSection({
  recordId,
  files,
}: {
  recordId: string;
  files: { name: string; content_type: string; size_bytes: number }[];
}) {
  const [expandedImage, setExpandedImage] = useState<string | null>(null);

  const imageFiles = files.filter((f) => previewType(f.name) !== null);
  const dataFiles = files.filter((f) => previewType(f.name) === null);

  return (
    <>
      {expandedImage && (
        <ImageModal
          recordId={recordId}
          filename={expandedImage}
          onClose={() => setExpandedImage(null)}
        />
      )}

      {imageFiles.length > 0 && (
        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">
              画像 ({imageFiles.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              {imageFiles.map((file) => (
                <ImageThumbnail
                  key={file.name}
                  recordId={recordId}
                  filename={file.name}
                  label={file.name}
                  onClickExpand={() => setExpandedImage(file.name)}
                />
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {dataFiles.length > 0 && (
        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">
              データファイル ({dataFiles.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {dataFiles.map((file, i) => (
              <div key={file.name}>
                {i > 0 && <Separator className="mb-2" />}
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
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-muted-foreground">
                      {file.size_bytes > 0 ? formatBytes(file.size_bytes) : "-"}
                    </span>
                    <a
                      href={`${API_BASE}/api/records/${recordId}/files/${encodeURIComponent(file.name)}?download=1`}
                      download={file.name}
                      className="text-xs text-primary hover:underline"
                    >
                      DL
                    </a>
                  </div>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </>
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
      fetchChildren(id, { limit: 10000 }).catch(() => ({
        items: [],
        total: 0,
      })),
    ])
      .then(([rec, kids]) => {
        setRecord(rec);
        setChildren(kids.items);
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
  const results = Object.entries(record.results).filter(
    ([key]) => !key.endsWith("__analysis_id")
  );

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
            <Separator />
            <div className="space-y-1">
              <span className="text-muted-foreground">タグ</span>
              <TagEditor
                recordId={id}
                tags={record.tags}
                onUpdate={(newTags) =>
                  setRecord({ ...record, tags: newTags })
                }
              />
            </div>
          </CardContent>
        </Card>

        {/* 条件 */}
        {conditions.length > 0 && (
          <ConditionsCard
            recordId={id}
            conditions={conditions}
            units={record.condition_units || {}}
            descriptions={record.condition_descriptions || {}}
            onUpdate={(units, descs) =>
              setRecord({
                ...record,
                condition_units: units,
                condition_descriptions: descs,
              })
            }
          />
        )}

        {/* 結果 */}
        {results.length > 0 && (
          <ResultsCard
            results={results}
            units={record.result_units || {}}
            allResults={record.results}
          />
        )}

        {/* ファイル */}
        {record.files.length > 0 && (
          <FileSection recordId={id} files={record.files} />
        )}

        {/* メモ */}
        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">
              メモ ({record.notes.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-sm">
            {record.notes.map((note, i) => (
              <div key={i} className="flex gap-3">
                <span className="shrink-0 text-muted-foreground text-xs">
                  {formatDate(note.created_at)}
                </span>
                <span>{note.text}</span>
              </div>
            ))}
            <Separator />
            <NoteForm
              recordId={id}
              onAdded={(note) =>
                setRecord({
                  ...record,
                  notes: [...record.notes, note],
                })
              }
            />
          </CardContent>
        </Card>

        {/* サブレコード */}
        {children.length > 0 && (
          <ChildrenSection
            recordId={id}
            children={children}
            onRefresh={() => {
              fetchChildren(id, { limit: 10000 })
                .then((res) => setChildren(res.items))
                .catch(() => {});
            }}
          />
        )}
      </div>
    </div>
  );
}

function ColumnPicker({
  label,
  keys,
  selected,
  onChange,
}: {
  label: string;
  keys: string[];
  selected: string[];
  onChange: (cols: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  if (keys.length === 0) return null;

  const toggle = (key: string) => {
    if (selected.includes(key)) {
      onChange(selected.filter((c) => c !== key));
    } else {
      onChange([...selected, key]);
    }
  };

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <Button
        variant="outline"
        size="sm"
        className="h-7 text-xs cursor-pointer"
        onClick={() => setOpen(!open)}
      >
        {label} {selected.length > 0 ? `(${selected.length})` : ""}
      </Button>
      {open && (
        <div className="flex flex-wrap gap-1">
          {keys.map((key) => (
            <Badge
              key={key}
              variant={selected.includes(key) ? "default" : "outline"}
              className="text-xs cursor-pointer"
              onClick={() => toggle(key)}
            >
              {key}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

function ChildrenSection({
  recordId,
  children,
  onRefresh,
}: {
  recordId: string;
  children: RecordSummary[];
  onRefresh: () => void;
}) {
  const [condFilters, setCondFilters] = useState<ConditionFilter[]>([]);
  const [fieldsMap, setFieldsMap] = useState<
    Map<string, Record<string, unknown>>
  >(new Map());
  const [conditionKeys, setConditionKeys] = useState<string[]>([]);
  const [resultKeys, setResultKeys] = useState<string[]>([]);
  const [dataLoaded, setDataLoaded] = useState(false);
  const [condCols, setCondCols] = useState<string[]>([]);
  const [resCols, setResCols] = useState<string[]>([]);

  // 子レコードの conditions + results を取得
  useEffect(() => {
    fetchChildrenConditions(recordId)
      .then((items) => {
        const map = new Map<string, Record<string, unknown>>();
        const cKeys = new Set<string>();
        const rKeys = new Set<string>();
        for (const item of items) {
          // conditions と results をマージ
          map.set(item.id, { ...item.conditions, ...item.results });
          Object.keys(item.conditions).forEach((k) => cKeys.add(k));
          Object.keys(item.results).forEach((k) => rKeys.add(k));
        }
        setFieldsMap(map);
        setConditionKeys(Array.from(cKeys).sort());
        setResultKeys(Array.from(rKeys).sort());
        setDataLoaded(true);
      })
      .catch(() => {});
  }, [recordId]);

  // 利用可能なキー (conditions + results)
  const availableKeys = [...conditionKeys, ...resultKeys];

  // フィルタ適用
  const filtered =
    condFilters.length === 0
      ? children
      : children.filter((rec) => {
          const fields = fieldsMap.get(rec.id);
          if (!fields) return false;
          return condFilters.every((f) => {
            const val = fields[f.key];
            if (val === undefined) return false;
            const numFilter = Number(f.value);
            if (!isNaN(numFilter) && typeof val === "number") {
              return val === numFilter;
            }
            return String(val) === f.value;
          });
        });

  return (
    <>
      {dataLoaded && fieldsMap.size > 0 && (
        <div className="md:col-span-2">
          <ConditionScatterChart
            records={filtered}
            conditionsMap={fieldsMap}
          />
        </div>
      )}

      <Card className="md:col-span-2">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">
              サブレコード ({filtered.length}
              {condFilters.length > 0 ? ` / ${children.length}` : ""})
            </CardTitle>
            <BulkUploadButton
              recordId={recordId}
              childCount={children.length}
              onComplete={onRefresh}
            />
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {dataLoaded && (
            <ConditionFilterPanel
              filters={condFilters}
              onChange={setCondFilters}
            />
          )}
          {dataLoaded && (
            <ColumnPicker
              label="条件カラム"
              keys={conditionKeys}
              selected={condCols}
              onChange={setCondCols}
            />
          )}
          {dataLoaded && resultKeys.length > 0 && (
            <ColumnPicker
              label="結果カラム"
              keys={resultKeys}
              selected={resCols}
              onChange={setResCols}
            />
          )}
          <SortableRecordTable
            records={filtered}
            defaultSort="title"
            conditionsMap={fieldsMap}
            conditionColumns={[...condCols, ...resCols]}
            pageSize={100}
          />
        </CardContent>
      </Card>
    </>
  );
}
