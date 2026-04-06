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
import { Separator } from "@/components/ui/separator";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface MatchItem {
  filename: string;
  record_id: string | null;
  record_title: string | null;
  status: string;
}

interface MatchPreview {
  total: number;
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

type Step = "select" | "preview" | "uploading" | "done";

export function BulkUploadButton({
  recordId,
  onComplete,
}: {
  recordId: string;
  onComplete?: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<Step>("select");
  const [files, setFiles] = useState<File[]>([]);
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

  const handleSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files || []);
    if (selected.length === 0) return;
    setFiles(selected);
    setLoading(true);

    // マッチングプレビューを取得
    try {
      const res = await fetch(
        `${API_BASE}/api/records/${recordId}/bulk-upload/preview`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(selected.map((f) => f.name)),
        }
      );
      if (!res.ok) throw new Error(`Preview failed: ${res.status}`);
      const data: MatchPreview = await res.json();
      setPreview(data);
      setStep("preview");
    } catch (err) {
      setPreview(null);
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

    try {
      const res = await fetch(
        `${API_BASE}/api/records/${recordId}/bulk-upload`,
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
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>一括アップロード</DialogTitle>
          </DialogHeader>

          {/* Step 1: フォルダ選択 */}
          {step === "select" && (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                フォルダを選択すると、ファイル名でサブレコードに自動マッチングします。
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
                disabled={loading}
                onClick={() => inputRef.current?.click()}
              >
                {loading ? "マッチング確認中..." : "フォルダを選択"}
              </Button>
            </div>
          )}

          {/* Step 2: マッチング確認 */}
          {step === "preview" && preview && (
            <PreviewTable
              preview={preview}
              onUpload={handleUpload}
              onReset={reset}
            />
          )}

          {/* Step 3: アップロード中 */}
          {step === "uploading" && (
            <div className="py-8 text-center text-muted-foreground">
              アップロード中...
            </div>
          )}

          {/* Step 4: 完了 */}
          {step === "done" && result && (
            <div className="space-y-3">
              <div className="flex gap-2">
                <Badge variant="secondary">合計: {result.total}</Badge>
                <Badge
                  variant="secondary"
                  className="bg-blue-100 text-blue-800"
                >
                  マッチ: {result.matched}
                </Badge>
                <Badge
                  variant="secondary"
                  className="bg-green-100 text-green-800"
                >
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

type PreviewSortKey = "filename" | "record_title";
type PreviewSortDir = "asc" | "desc";

function PreviewTable({
  preview,
  onUpload,
  onReset,
}: {
  preview: MatchPreview;
  onUpload: () => void;
  onReset: () => void;
}) {
  const [sortKey, setSortKey] = useState<PreviewSortKey>("filename");
  const [sortDir, setSortDir] = useState<PreviewSortDir>("asc");

  const sorted = [...preview.items].sort((a, b) => {
    let va: string;
    let vb: string;
    if (sortKey === "filename") {
      va = a.filename;
      vb = b.filename;
    } else {
      va = a.record_title || "\uffff";
      vb = b.record_title || "\uffff";
    }
    const cmp = va.localeCompare(vb, "ja");
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
      <div className="flex items-center justify-between">
        <div className="flex gap-2">
          <Badge variant="secondary">合計: {preview.total}</Badge>
          <Badge
            variant="secondary"
            className="bg-green-100 text-green-800"
          >
            マッチ: {preview.matched}
          </Badge>
          {preview.unmatched > 0 && (
            <Badge
              variant="secondary"
              className="bg-red-100 text-red-800"
            >
              未マッチ: {preview.unmatched}
            </Badge>
          )}
        </div>
        <div className="flex gap-1">
          <Button
            variant={sortKey === "filename" ? "default" : "outline"}
            size="sm"
            className="h-7 text-xs cursor-pointer"
            onClick={() => toggleSort("filename")}
          >
            ファイル名{arrow("filename")}
          </Button>
          <Button
            variant={sortKey === "record_title" ? "default" : "outline"}
            size="sm"
            className="h-7 text-xs cursor-pointer"
            onClick={() => toggleSort("record_title")}
          >
            マッチ先{arrow("record_title")}
          </Button>
        </div>
      </div>

      <div className="max-h-80 overflow-y-auto rounded border text-sm">
        <table className="w-full">
          <thead className="sticky top-0 bg-muted">
            <tr>
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
          onClick={onReset}
        >
          やり直す
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
