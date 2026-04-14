"use client";

import { useRef, useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { fetchChildren } from "@/lib/api";
import type { RecordSummary } from "@/lib/api";

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

function naturalSortKey(s: string): string {
  return s.replace(/(\d+)/g, (m) => m.padStart(10, "0")).toLowerCase();
}

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
  const [children, setChildren] = useState<RecordSummary[]>([]);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadCurrent, setUploadCurrent] = useState("");
  const [uploadEta, setUploadEta] = useState("");
  const uploadStartRef = useRef(0);

  useEffect(() => {
    if (open) {
      fetchChildren(recordId, { limit: 5000 })
        .then((res) =>
          setChildren(
            [...res.items].sort((a, b) =>
              naturalSortKey(a.title).localeCompare(naturalSortKey(b.title))
            )
          )
        )
        .catch(() => {});
    }
  }, [open, recordId]);

  const reset = () => {
    setStep("select");
    setFiles([]);
    setPreview(null);
    setResult(null);
    setLoading(false);
    setUploadProgress(0);
    setUploadCurrent("");
    setUploadEta("");
  };

  const handleSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files || []);
    if (selected.length === 0) return;
    setFiles(selected);
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
      setPreview(await res.json());
      setStep("preview");
    } catch {
      setStep("preview");
    } finally {
      setLoading(false);
    }
  };

  const handleUpload = async () => {
    setStep("uploading");
    setUploadProgress(0);
    setUploadCurrent("ファイルを送信中...");
    setUploadEta("");
    uploadStartRef.current = Date.now();

    const formData = new FormData();
    for (const file of files) formData.append("files", file);
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

      if (!res.ok || !res.body) {
        setResult({
          total: files.length, matched: 0, uploaded: 0,
          errors: [`Upload failed: ${res.status}`],
        });
        setStep("done");
        return;
      }

      // SSE を読む
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() || "";

        for (const block of lines) {
          const eventMatch = block.match(/^event: (\w+)/m);
          const dataMatch = block.match(/^data: (.+)/m);
          if (!eventMatch || !dataMatch) continue;

          const eventType = eventMatch[1];
          const data = JSON.parse(dataMatch[1]);

          if (eventType === "progress") {
            const pct = Math.round((data.current / data.total) * 100);
            setUploadProgress(pct);
            setUploadCurrent(
              `${data.current} / ${data.total}: ${data.filename} ${data.status === "ok" ? "✓" : data.status === "error" ? "✗" : "⏭"}`
            );
            // ETA 計算
            const elapsed = (Date.now() - uploadStartRef.current) / 1000;
            if (data.current > 0 && data.current < data.total) {
              const perFile = elapsed / data.current;
              const remaining = Math.round(perFile * (data.total - data.current));
              if (remaining >= 60) {
                setUploadEta(`残り約 ${Math.floor(remaining / 60)}分${remaining % 60}秒`);
              } else {
                setUploadEta(`残り約 ${remaining}秒`);
              }
            } else {
              setUploadEta("");
            }
          } else if (eventType === "done") {
            setUploadProgress(100);
            setResult({
              total: data.total,
              matched: data.uploaded,
              uploaded: data.uploaded,
              errors: data.errors,
            });
            setStep("done");
            if (data.uploaded > 0) onComplete?.();
          }
        }
      }
    } catch (err) {
      setResult({
        total: files.length, matched: 0, uploaded: 0,
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
        <DialogContent className="max-w-5xl w-[90vw] max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="text-lg">一括アップロード</DialogTitle>
          </DialogHeader>

          {/* Step 1: フォルダ選択 */}
          {step === "select" && (
            <div className="space-y-4 py-4">
              <p className="text-sm text-muted-foreground">
                アップロードするファイルが入ったフォルダを選択してください。
                ファイルは N×M グリッドでサブレコードにマッチングされます。
              </p>
              <p className="text-sm text-muted-foreground">
                サブレコード数: <strong>{childCount}</strong>
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
                size="lg"
                className="w-full cursor-pointer h-16 text-base"
                onClick={() => inputRef.current?.click()}
              >
                フォルダを選択
              </Button>
            </div>
          )}

          {/* Step 2: グリッド設定 */}
          {step === "grid" && (
            <div className="space-y-6 py-2">
              {/* 件数バッジ */}
              <div className="flex gap-3 flex-wrap">
                <Badge variant="secondary" className="text-sm px-3 py-1">
                  ファイル: {files.length}
                </Badge>
                <Badge variant="secondary" className="text-sm px-3 py-1">
                  サブレコード: {childCount}
                </Badge>
                {rows * cols === files.length ? (
                  <Badge className="bg-green-100 text-green-800 text-sm px-3 py-1">
                    グリッド一致 ({rows}×{cols}={rows * cols})
                  </Badge>
                ) : (
                  <Badge className="bg-red-100 text-red-800 text-sm px-3 py-1">
                    不一致: {rows}×{cols}={rows * cols} ≠ {files.length}
                  </Badge>
                )}
              </div>

              {/* グリッドサイズ + 方向 */}
              <div className="flex items-center gap-4 flex-wrap">
                <div className="flex items-center gap-2">
                  <label className="text-sm font-medium">行</label>
                  <Input
                    type="number"
                    min={1}
                    value={rows}
                    onChange={(e) => setRows(Number(e.target.value) || 1)}
                    className="w-20"
                  />
                </div>
                <span className="text-muted-foreground">×</span>
                <div className="flex items-center gap-2">
                  <label className="text-sm font-medium">列</label>
                  <Input
                    type="number"
                    min={1}
                    value={cols}
                    onChange={(e) => setCols(Number(e.target.value) || 1)}
                    className="w-20"
                  />
                </div>
                <div className="border-l pl-4 flex items-center gap-2">
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
              </div>

              {/* グリッドビジュアル (子レコード名表示) */}
              <div className="space-y-2">
                <p className="text-sm font-medium">
                  開始位置を選択 (★をクリック):
                </p>
                <GridVisual
                  rows={rows}
                  cols={cols}
                  corner={corner}
                  direction={direction}
                  children={children}
                  files={files}
                  onCornerClick={setCorner}
                />
              </div>

              <Button
                size="lg"
                className="w-full cursor-pointer"
                disabled={loading || rows * cols < files.length}
                onClick={handlePreview}
              >
                {loading ? "マッチング確認中..." : "マッチング確認 →"}
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
            <div className="py-8 space-y-4">
              <div className="text-center">
                <div className="text-lg font-medium">{uploadCurrent}</div>
                <p className="text-sm text-muted-foreground mt-1">
                  {files.length} ファイル
                </p>
              </div>
              <div className="w-full bg-muted rounded-full h-3 overflow-hidden">
                <div
                  className="bg-blue-500 h-full rounded-full transition-all duration-300"
                  style={{ width: `${uploadProgress}%` }}
                />
              </div>
              <div className="flex justify-center gap-4 text-sm text-muted-foreground">
                <span className="font-mono">{uploadProgress}%</span>
                {uploadEta && <span>{uploadEta}</span>}
              </div>
            </div>
          )}

          {/* Step 5: 完了 */}
          {step === "done" && result && (
            <div className="space-y-4 py-4">
              <div className="flex gap-3 flex-wrap">
                <Badge variant="secondary" className="text-sm px-3 py-1">
                  合計: {result.total}
                </Badge>
                <Badge className="bg-blue-100 text-blue-800 text-sm px-3 py-1">
                  マッチ: {result.matched}
                </Badge>
                <Badge className="bg-green-100 text-green-800 text-sm px-3 py-1">
                  成功: {result.uploaded}
                </Badge>
              </div>
              {result.errors.length > 0 && (
                <div className="max-h-40 overflow-y-auto rounded border p-3 text-sm text-destructive">
                  {result.errors.map((e, i) => (
                    <div key={i}>{e}</div>
                  ))}
                </div>
              )}
              <Button
                size="lg"
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

/* ---- Grid Visual ---- */

function generateGridPositions(
  rows: number, cols: number, startPos: Corner, dir: Direction
): { row: number; col: number }[] {
  const rowIdx = Array.from({ length: rows }, (_, i) => i);
  const colIdx = Array.from({ length: cols }, (_, i) => i);
  if (startPos.includes("bottom")) rowIdx.reverse();
  if (startPos.includes("right")) colIdx.reverse();

  const positions: { row: number; col: number }[] = [];
  if (dir === "row-first") {
    for (const r of rowIdx) for (const c of colIdx) positions.push({ row: r, col: c });
  } else {
    for (const c of colIdx) for (const r of rowIdx) positions.push({ row: r, col: c });
  }
  return positions;
}

function GridVisual({
  rows,
  cols,
  corner,
  direction,
  children,
  files,
  onCornerClick,
}: {
  rows: number;
  cols: number;
  corner: Corner;
  direction: Direction;
  children: RecordSummary[];
  files: File[];
  onCornerClick: (c: Corner) => void;
}) {
  // ファイル名からフォルダパスを除去してソート
  const basename = (s: string) => s.split("/").pop()?.split("\\").pop() || s;
  const sortedFileNames = [...files]
    .map((f) => basename(f.name))
    .sort((a, b) => naturalSortKey(a).localeCompare(naturalSortKey(b)));

  // グリッド走査順でファイルをセルにマップ
  const positions = generateGridPositions(rows, cols, corner, direction);
  const fileAtCell: Record<string, string> = {};
  positions.forEach((pos, i) => {
    if (i < sortedFileNames.length) {
      fileAtCell[`${pos.row}-${pos.col}`] = sortedFileNames[i];
    }
  });

  const showRows = getVisibleIndices(rows, 6);
  const showCols = getVisibleIndices(cols, 6);

  const stem = (name: string) => {
    const dot = name.lastIndexOf(".");
    return dot > 0 ? name.slice(0, dot) : name;
  };

  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr className="bg-muted/50">
            <th className="border-r border-b p-1.5 text-muted-foreground font-normal w-8"></th>
            {showCols.map((c, ci) => (
              <th key={ci} className="border-b p-1.5 text-center text-muted-foreground font-normal">
                {c === -1 ? "⋯" : `列${c}`}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {showRows.map((r, ri) => (
            <tr key={ri}>
              {r === -1 ? (
                <>
                  <td className="border-r p-1.5 text-center text-muted-foreground">⋮</td>
                  {showCols.map((_, ci) => (
                    <td key={ci} className="p-1.5 text-center text-muted-foreground">⋮</td>
                  ))}
                </>
              ) : (
                <>
                  <td className="border-r p-1.5 text-center text-muted-foreground bg-muted/50 font-normal">
                    行{r}
                  </td>
                  {showCols.map((c, ci) => {
                    if (c === -1) {
                      return (
                        <td key={ci} className="p-1.5 text-center text-muted-foreground">⋯</td>
                      );
                    }
                    const idx = r * cols + c;
                    const child = idx < children.length ? children[idx] : null;
                    const fileName = fileAtCell[`${r}-${c}`] || null;
                    const isCorner =
                      (r === 0 && c === 0) ||
                      (r === 0 && c === cols - 1) ||
                      (r === rows - 1 && c === 0) ||
                      (r === rows - 1 && c === cols - 1);
                    const cornerName: Corner | null =
                      r === 0 && c === 0 ? "top-left" :
                      r === 0 && c === cols - 1 ? "top-right" :
                      r === rows - 1 && c === 0 ? "bottom-left" :
                      r === rows - 1 && c === cols - 1 ? "bottom-right" : null;
                    const isSelected = cornerName === corner;

                    return (
                      <td
                        key={ci}
                        className={`border p-1.5 align-top transition-colors
                          ${isCorner ? "cursor-pointer" : ""}
                          ${isSelected
                            ? "bg-blue-500 text-white"
                            : isCorner
                              ? "bg-amber-50 hover:bg-amber-100"
                              : "bg-white hover:bg-muted/30"
                          }`}
                        style={{ minWidth: 120, maxWidth: 160 }}
                        title={[
                          `[${r},${c}]`,
                          child && `レコード: ${child.title}`,
                          fileName && `ファイル: ${fileName}`,
                        ].filter(Boolean).join("\n")}
                        onClick={() => cornerName && onCornerClick(cornerName)}
                      >
                        {isCorner && (
                          <div className={`text-[10px] font-bold mb-0.5 ${isSelected ? "text-white" : "text-amber-600"}`}>
                            ★ 開始
                          </div>
                        )}
                        {child ? (
                          <div className="truncate">
                            <div className={`font-mono text-[10px] ${isSelected ? "text-blue-100" : "text-muted-foreground"}`}>
                              {child.id}
                            </div>
                            <div className="truncate font-medium text-[11px] leading-tight">
                              {child.title}
                            </div>
                          </div>
                        ) : (
                          <div className={`text-[10px] ${isSelected ? "text-blue-200" : "text-muted-foreground"}`}>
                            (空)
                          </div>
                        )}
                        {fileName && (
                          <div className={`mt-1 pt-1 border-t truncate text-[10px] ${
                            isSelected ? "border-blue-400 text-blue-100" : "border-dashed text-blue-600"
                          }`}>
                            ↑ {stem(fileName)}
                          </div>
                        )}
                      </td>
                    );
                  })}
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function getVisibleIndices(total: number, maxShow: number): number[] {
  if (total <= maxShow) return Array.from({ length: total }, (_, i) => i);
  const half = Math.floor(maxShow / 2);
  const head = Array.from({ length: half }, (_, i) => i);
  const tail = Array.from({ length: half }, (_, i) => total - half + i);
  return [...head, -1, ...tail];
}

/* ---- Preview Table ---- */

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
      va = a.filename; vb = b.filename;
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
    if (sortKey === key) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDir("asc"); }
  };

  const arrow = (key: PreviewSortKey) =>
    sortKey === key ? (sortDir === "asc" ? " ↑" : " ↓") : "";

  return (
    <div className="space-y-4 py-2">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex gap-2 flex-wrap">
          <Badge variant="secondary" className="text-sm px-3 py-1">
            ファイル: {preview.total_files}
          </Badge>
          <Badge variant="secondary" className="text-sm px-3 py-1">
            レコード: {preview.total_records}
          </Badge>
          <Badge className="bg-green-100 text-green-800 text-sm px-3 py-1">
            マッチ: {preview.matched}
          </Badge>
          {preview.unmatched > 0 && (
            <Badge className="bg-red-100 text-red-800 text-sm px-3 py-1">
              未マッチ: {preview.unmatched}
            </Badge>
          )}
        </div>
        <div className="flex gap-1">
          {(["grid", "filename", "record_title", "created_at"] as const).map((key) => (
            <Button
              key={key}
              variant={sortKey === key ? "default" : "outline"}
              size="sm"
              className="cursor-pointer"
              onClick={() => toggleSort(key)}
            >
              {{ grid: "位置", filename: "ファイル", record_title: "名前", created_at: "作成日" }[key]}
              {arrow(key)}
            </Button>
          ))}
        </div>
      </div>

      <div className="max-h-[50vh] overflow-y-auto rounded border">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-muted">
            <tr>
              <th className="px-3 py-2 text-left font-medium w-16">位置</th>
              <th className="px-3 py-2 text-left font-medium">ファイル</th>
              <th className="px-3 py-2 text-center font-medium w-8">→</th>
              <th className="px-3 py-2 text-left font-medium">マッチ先</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((item, i) => (
              <tr key={i} className={`border-t ${item.status === "unmatched" ? "bg-red-50" : "hover:bg-muted/30"}`}>
                <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                  {item.grid_row >= 0 ? `[${item.grid_row},${item.grid_col}]` : "-"}
                </td>
                <td className="px-3 py-2 font-mono text-xs">{item.filename}</td>
                <td className="px-3 py-2 text-center text-muted-foreground">→</td>
                <td className="px-3 py-2">
                  {item.record_id ? (
                    <span>
                      <span className="font-mono text-xs text-primary">{item.record_id}</span>{" "}
                      <span className="text-xs">{item.record_title}</span>
                    </span>
                  ) : (
                    <span className="text-xs text-destructive">マッチなし</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex gap-3 justify-end">
        <Button variant="outline" className="cursor-pointer" onClick={onBack}>
          ← 戻る
        </Button>
        <Button
          size="lg"
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
