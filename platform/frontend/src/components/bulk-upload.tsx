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

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface BulkUploadResult {
  total: number;
  matched: number;
  uploaded: number;
  errors: string[];
}

export function BulkUploadButton({
  recordId,
  onComplete,
}: {
  recordId: string;
  onComplete?: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<BulkUploadResult | null>(null);

  const handleSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files || []);
    setFiles(selected);
    setResult(null);
  };

  const handleUpload = async () => {
    if (files.length === 0) return;
    setUploading(true);
    setResult(null);

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
      const data: BulkUploadResult = await res.json();
      setResult(data);
      if (data.uploaded > 0) onComplete?.();
    } catch (err) {
      setResult({
        total: files.length,
        matched: 0,
        uploaded: 0,
        errors: [(err as Error).message],
      });
    } finally {
      setUploading(false);
    }
  };

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className="cursor-pointer"
        onClick={() => setOpen(true)}
      >
        一括アップロード
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>一括アップロード</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">
          フォルダ内のファイルをサブレコードに自動マッチングしてアップロードします。
          ファイル名の番号 (例: _1, _38) でサブレコードの順番にマッチします。
        </p>

        <input
          ref={inputRef}
          type="file"
          multiple
          className="hidden"
          onChange={handleSelect}
          /* @ts-expect-error webkitdirectory is not in types */
          webkitdirectory=""
        />

        <div className="space-y-3">
          <Button
            variant="outline"
            className="w-full cursor-pointer"
            onClick={() => inputRef.current?.click()}
          >
            フォルダを選択
          </Button>

          {files.length > 0 && (
            <div className="rounded border p-3 text-sm">
              <p className="font-medium">{files.length} ファイル選択済み</p>
              <div className="mt-1 max-h-32 overflow-y-auto text-xs text-muted-foreground">
                {files.slice(0, 10).map((f) => (
                  <div key={f.name}>{f.name}</div>
                ))}
                {files.length > 10 && (
                  <div>... 他 {files.length - 10} ファイル</div>
                )}
              </div>
            </div>
          )}

          <Button
            className="w-full cursor-pointer"
            disabled={files.length === 0 || uploading}
            onClick={handleUpload}
          >
            {uploading ? "アップロード中..." : "アップロード開始"}
          </Button>

          {result && (
            <div className="rounded border p-3 text-sm space-y-1">
              <div className="flex gap-2">
                <Badge variant="secondary">合計: {result.total}</Badge>
                <Badge variant="secondary" className="bg-blue-100 text-blue-800">
                  マッチ: {result.matched}
                </Badge>
                <Badge variant="secondary" className="bg-green-100 text-green-800">
                  成功: {result.uploaded}
                </Badge>
              </div>
              {result.errors.length > 0 && (
                <div className="mt-2 max-h-32 overflow-y-auto text-xs text-destructive">
                  {result.errors.map((e, i) => (
                    <div key={i}>{e}</div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </DialogContent>
      </Dialog>
    </>
  );
}
