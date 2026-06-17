// CSV エクスポートユーティリティ
//
// - quote-always: すべてのフィールドを引用符で囲む (Excel / Notebook どちらでも
//   parse しやすい安全側)
// - BOM 付き UTF-8: Excel 日本語版で UTF-8 を文字化けなく開けるため必須
// - 改行 / 引用符 / カンマを含むフィールドも安全に encode
// - download トリガは Blob URL 経由 (Cloud Run / Next.js で server を介さない)

export function escapeCsvField(value: unknown): string {
  if (value === null || value === undefined) return '""';
  let s = String(value);
  // CSV 仕様: フィールド内の `"` は `""` に
  s = s.replace(/"/g, '""');
  return `"${s}"`;
}

export function toCsv(headers: string[], rows: unknown[][]): string {
  const lines = [
    headers.map(escapeCsvField).join(","),
    ...rows.map((row) => row.map(escapeCsvField).join(",")),
  ];
  // CRLF が Excel での挙動が一番安定。
  return lines.join("\r\n");
}

export function downloadCsv(filename: string, csv: string): void {
  // BOM を先頭に付けて Excel 日本語版で UTF-8 として認識させる
  const blob = new Blob(["﻿" + csv], {
    type: "text/csv;charset=utf-8;",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // 数秒後に revoke (Safari でクリック直後 revoke すると失敗する報告あり)
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function todayStamp(): string {
  // YYYY-MM-DD (local time)
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}
