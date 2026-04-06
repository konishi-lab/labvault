"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface MatchItem {
  filename: string;
  grid_row: number;
  grid_col: number;
  record_id: string | null;
  record_title: string | null;
  record_created_at: string | null;
  status: string;
}

interface MatchPreview {
  total_files: number;
  total_records: number;
  matched: number;
  unmatched: number;
  items: MatchItem[];
}

interface UploadResult {
  total: number;
  matched: number;
  uploaded: number;
  errors: string[];
}

type Corner = "top-left" | "top-right" | "bottom-left" | "bottom-right";
type Direction = "row-first" | "column-first";
type Step = "select" | "grid" | "preview" | "uploading" | "done";

export function BulkUploadButton({
  recordId,
  childCount,
  onComplete,
}: {
  recordId: string;
  childCount: number;
  onComplete?: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<Step>("select");
  const [files, setFiles] = useState<File[]>([]);
  const [rows, setRows] = useState(1);
  const [cols, setCols] = useState(1);
  const [corner, setCorner] = useState<Corner>("top-left");
  const [direction, setDirection] = useState<Direction>("row-first");
  const [preview, setPreview] = useState<MatchPreview | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [loading, setLoading] = useState(false);

  const reset = () => {
    setStep("select");
    setFiles([]);
    setPreview(null);
    setResult(null);
    setLoading(false);
  };

  const handleSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files || []);
    if (selected.length === 0) return;
    setFiles(selected);
    // グリッドサイズの初期推定
    const n = selected.length;
    const sqrt = Math.ceil(Math.sqrt(n));
    setRows(Math.ceil(n / sqrt));
    setCols(sqrt);
    setStep("grid");
  };

  const handlePreview = async () => {
    setLoading(true);
    try {
      const res = await fetch(
        `${API_BASE}/api/records/${recordId}/bulk-upload/preview`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            grid: { rows, cols, start_position: corner, direction },
            filenames: files.map((f) => f.name),
          }),
        }
      );
      if (!res.ok) throw new Error(`Preview failed: ${res.status}`);
      const data: MatchPreview = await res.json();
      setPreview(data);
      setStep("preview");
    } catch {
      setStep("preview");
    } finally {
      setLoading(false);
    }
  };

  const handleUpload = async () => {
    setStep("uploading");
    const formData = new FormData();
    for (const file of files) {
      formData.append("files", file);
    }
    const params = new URLSearchParams({
      rows: String(rows),
      cols: String(cols),
      start_position: corner,
      direction,
    });

    try {
      const res = await fetch(
        `${API_BASE}/api/records/${recordId}/bulk-upload?${params}`,
        { method: "POST", body: formData }
      );
      if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
      const data: UploadResult = await res.json();
      setResult(data);
      setStep("done");
      if (data.uploaded > 0) onComplete?.();
    } catch (err) {
      setResult({
        total: files.length,
        matched: 0,
        uploaded: 0,
        errors: [(err as Error).message],
      });
      setStep("done");
    }
  };

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className="cursor-pointer"
        onClick={() => {
          reset();
          setOpen(true);
        }}
      >
        一括アップロード
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>一括アップロード</DialogTitle>
          </DialogHeader>

          {/* Step 1: フォルダ選択 */}
          {step === "select" && (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                フォルダを選択してください。ファイルは NxM
                のグリッドでサブレコードにマッチングされます。
              </p>
              <input
                ref={inputRef}
                type="file"
                multiple
                className="hidden"
                onChange={handleSelect}
                /* @ts-expect-error webkitdirectory */
                webkitdirectory=""
              />
              <Button
                variant="outline"
                className="w-full cursor-pointer"
                onClick={() => inputRef.current?.click()}
              >
                フォルダを選択
              </Button>
            </div>
          )}

          {/* Step 2: グリッド設定 */}
          {step === "grid" && (
            <div className="space-y-4">
              <div className="flex gap-2 text-sm">
                <Badge variant="secondary">
                  ファイル: {files.length}
                </Badge>
                <Badge variant="secondary">
                  サブレコード: {childCount}
                </Badge>
                {rows * cols === files.length ? (
                  <Badge className="bg-green-100 text-green-800">
                    グリッドサイズ一致
                  </Badge>
                ) : (
                  <Badge className="bg-red-100 text-red-800">
                    {rows}×{cols}={rows * cols} (不一致)
                  </Badge>
                )}
              </div>

              {/* グリッドサイズ入力 */}
              <div className="flex items-center gap-3">
                <label className="text-sm font-medium w-12">行数</label>
                <Input
                  type="number"
                  min={1}
                  value={rows}
                  onChange={(e) => setRows(Number(e.target.value) || 1)}
                  className="w-20"
                />
                <label className="text-sm font-medium w-12">列数</label>
                <Input
                  type="number"
                  min={1}
                  value={cols}
                  onChange={(e) => setCols(Number(e.target.value) || 1)}
                  className="w-20"
                />
              </div>

              {/* グリッドビジュアル + コーナー選択 */}
              <GridVisual
                rows={rows}
                cols={cols}
                corner={corner}
                files={files}
                onCornerClick={setCorner}
              />

              {/* 走査方向 */}
              <div className="flex items-center gap-3">
                <p className="text-sm font-medium">走査方向:</p>
                <Button
                  variant={direction === "row-first" ? "default" : "outline"}
                  size="sm"
                  className="cursor-pointer"
                  onClick={() => setDirection("row-first")}
                >
                  行優先 →
                </Button>
                <Button
                  variant={direction === "column-first" ? "default" : "outline"}
                  size="sm"
                  className="cursor-pointer"
                  onClick={() => setDirection("column-first")}
                >
                  列優先 ↓
                </Button>
              </div>

              <Button
                className="w-full cursor-pointer"
                disabled={loading || rows * cols < files.length}
                onClick={handlePreview}
              >
                {loading ? "マッチング確認中..." : "マッチング確認"}
              </Button>
            </div>
          )}

          {/* Step 3: マッチング確認 */}
          {step === "preview" && preview && (
            <PreviewTable
              preview={preview}
              cols={cols}
              onUpload={handleUpload}
              onBack={() => setStep("grid")}
            />
          )}

          {/* Step 4: アップロード中 */}
          {step === "uploading" && (
            <div className="py-8 text-center text-muted-foreground">
              アップロード中...
            </div>
          )}

          {/* Step 5: 完了 */}
          {step === "done" && result && (
            <div className="space-y-3">
              <div className="flex gap-2">
                <Badge variant="secondary">合計: {result.total}</Badge>
                <Badge className="bg-blue-100 text-blue-800">
                  マッチ: {result.matched}
                </Badge>
                <Badge className="bg-green-100 text-green-800">
                  成功: {result.uploaded}
                </Badge>
              </div>
              {result.errors.length > 0 && (
                <div className="max-h-32 overflow-y-auto rounded border p-2 text-xs text-destructive">
                  {result.errors.map((e, i) => (
                    <div key={i}>{e}</div>
                  ))}
                </div>
              )}
              <Button
                className="w-full cursor-pointer"
                onClick={() => setOpen(false)}
              >
                閉じる
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

type PreviewSortKey = "filename" | "record_title" | "grid" | "created_at";
type PreviewSortDir = "asc" | "desc";

function PreviewTable({
  preview,
  cols,
  onUpload,
  onBack,
}: {
  preview: MatchPreview;
  cols: number;
  onUpload: () => void;
  onBack: () => void;
}) {
  const [sortKey, setSortKey] = useState<PreviewSortKey>("grid");
  const [sortDir, setSortDir] = useState<PreviewSortDir>("asc");

  const sorted = [...preview.items].sort((a, b) => {
    let va: string | number;
    let vb: string | number;
    if (sortKey === "filename") {
      va = a.filename;
      vb = b.filename;
    } else if (sortKey === "grid") {
      va = a.grid_row * cols + a.grid_col;
      vb = b.grid_row * cols + b.grid_col;
    } else if (sortKey === "created_at") {
      va = a.record_created_at || "\uffff";
      vb = b.record_created_at || "\uffff";
    } else {
      va = a.record_title || "\uffff";
      vb = b.record_title || "\uffff";
    }
    const cmp = va < vb ? -1 : va > vb ? 1 : 0;
    return sortDir === "asc" ? cmp : -cmp;
  });

  const toggleSort = (key: PreviewSortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const arrow = (key: PreviewSortKey) =>
    sortKey === key ? (sortDir === "asc" ? " ↑" : " ↓") : "";

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex gap-2">
          <Badge variant="secondary">ファイル: {preview.total_files}</Badge>
          <Badge variant="secondary">レコード: {preview.total_records}</Badge>
          <Badge className="bg-green-100 text-green-800">
            マッチ: {preview.matched}
          </Badge>
          {preview.unmatched > 0 && (
            <Badge className="bg-red-100 text-red-800">
              未マッチ: {preview.unmatched}
            </Badge>
          )}
        </div>
        <div className="flex gap-1">
          {(["grid", "filename", "record_title", "created_at"] as const).map(
            (key) => (
              <Button
                key={key}
                variant={sortKey === key ? "default" : "outline"}
                size="sm"
                className="h-7 text-xs cursor-pointer"
                onClick={() => toggleSort(key)}
              >
                {{ grid: "位置", filename: "ファイル", record_title: "名前", created_at: "作成日" }[key]}
                {arrow(key)}
              </Button>
            )
          )}
        </div>
      </div>

      <div className="max-h-80 overflow-y-auto rounded border text-sm">
        <table className="w-full">
          <thead className="sticky top-0 bg-muted">
            <tr>
              <th className="px-3 py-2 text-left font-medium w-16">位置</th>
              <th className="px-3 py-2 text-left font-medium">ファイル名</th>
              <th className="px-3 py-2 text-left font-medium">→</th>
              <th className="px-3 py-2 text-left font-medium">マッチ先</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((item, i) => (
              <tr
                key={i}
                className={item.status === "unmatched" ? "bg-red-50" : ""}
              >
                <td className="px-3 py-1.5 font-mono text-xs text-muted-foreground">
                  {item.grid_row >= 0
                    ? `[${item.grid_row},${item.grid_col}]`
                    : "-"}
                </td>
                <td className="px-3 py-1.5 font-mono text-xs">
                  {item.filename}
                </td>
                <td className="px-3 py-1.5 text-muted-foreground">→</td>
                <td className="px-3 py-1.5">
                  {item.record_id ? (
                    <span>
                      <span className="font-mono text-xs text-primary">
                        {item.record_id}
                      </span>{" "}
                      <span className="text-xs">{item.record_title}</span>
                    </span>
                  ) : (
                    <span className="text-xs text-destructive">
                      マッチなし
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex gap-2 justify-end">
        <Button
          variant="outline"
          className="cursor-pointer"
          onClick={onBack}
        >
          戻る
        </Button>
        <Button
          className="cursor-pointer"
          disabled={preview.matched === 0}
          onClick={onUpload}
        >
          {preview.matched} 件をアップロード
        </Button>
      </div>
    </div>
  );
}

function naturalSortKey(s: string): string {
  return s.replace(/(\d+)/g, (m) => m.padStart(10, "0")).toLowerCase();
}

function GridVisual({
  rows,
  cols,
  corner,
  files,
  onCornerClick,
}: {
  rows: number;
  cols: number;
  corner: Corner;
  files: File[];
  onCornerClick: (c: Corner) => void;
}) {
  const sortedNames = [...files]
    .map((f) => f.name)
    .sort((a, b) => naturalSortKey(a).localeCompare(naturalSortKey(b)));

  // 表示する行・列を決定 (端2行/列 + 省略)
  const maxShow = 6;
  const showRows = getVisibleIndices(rows, maxShow);
  const showCols = getVisibleIndices(cols, maxShow);

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium">開始位置をクリック:</p>
      <div className="overflow-x-auto">
        <table className="border-collapse text-[9px]">
          <tbody>
            {showRows.map((r, ri) => (
              <tr key={ri}>
                {r === -1 ? (
                  <td
                    colSpan={showCols.length}
                    className="text-center text-muted-foreground py-0.5"
                  >
                    ⋮
                  </td>
                ) : (
                  showCols.map((c, ci) => {
                    if (c === -1) {
                      return (
                        <td
                          key={ci}
                          className="text-center text-muted-foreground px-1"
                        >
                          ⋯
                        </td>
                      );
                    }
                    const isCorner =
                      (r === 0 && c === 0) ||
                      (r === 0 && c === cols - 1) ||
                      (r === rows - 1 && c === 0) ||
                      (r === rows - 1 && c === cols - 1);
                    const cornerName: Corner | null =
                      r === 0 && c === 0
                        ? "top-left"
                        : r === 0 && c === cols - 1
                          ? "top-right"
                          : r === rows - 1 && c === 0
                            ? "bottom-left"
                            : r === rows - 1 && c === cols - 1
                              ? "bottom-right"
                              : null;
                    const isSelected = cornerName === corner;
                    const idx = r * cols + c;
                    const fname = idx < sortedNames.length ? sortedNames[idx] : "";
                    const stem =
                      fname.lastIndexOf(".") > 0
                        ? fname.slice(0, fname.lastIndexOf("."))
                        : fname;
                    const isEdge = r === 0 || r === rows - 1 || c === 0 || c === cols - 1;

                    return (
                      <td
                        key={ci}
                        className={`border px-1 py-0.5 max-w-[80px] truncate
                          ${isCorner ? "cursor-pointer hover:bg-blue-100 font-bold" : ""}
                          ${isSelected ? "bg-blue-500 text-white" : isCorner ? "bg-yellow-100" : isEdge ? "bg-muted/30" : "bg-muted/10"}`}
                        title={fname}
                        onClick={() => cornerName && onCornerClick(cornerName)}
                      >
                        {isEdge ? stem.slice(0, 12) : ""}
                      </td>
                    );
                  })
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function getVisibleIndices(total: number, maxShow: number): number[] {
  if (total <= maxShow) {
    return Array.from({ length: total }, (_, i) => i);
  }
  const half = Math.floor(maxShow / 2);
  const head = Array.from({ length: half }, (_, i) => i);
  const tail = Array.from({ length: half }, (_, i) => total - half + i);
  return [...head, -1, ...tail]; // -1 = ellipsis
}
