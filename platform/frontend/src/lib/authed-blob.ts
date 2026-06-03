"use client";

import { useEffect, useState } from "react";

import { authFetch } from "./api";

type FetchState =
  | { kind: "idle" }
  | { kind: "loading"; url: string }
  | { kind: "loaded"; url: string; src: string }
  | { kind: "error"; url: string };

/**
 * 認証必須のバイナリ URL を fetch して `URL.createObjectURL` で blob URL
 * を返す hook。`<img src={...}>` や `<a href={...} download>` はブラウザ
 * が `Authorization` ヘッダを送らないので、認証付き backend のエンド
 * ポイントを直接渡すと 401 になる。本 hook で blob 化したものを渡せば
 * 認証は fetch 時に解決される。
 *
 * unmount / url 変更時に `revokeObjectURL` でメモリを返す。
 */
export function useAuthedBlobUrl(url: string | null): {
  src: string | null;
  loading: boolean;
  error: boolean;
} {
  const [state, setState] = useState<FetchState>({ kind: "idle" });

  useEffect(() => {
    if (!url) return;
    let cancelled = false;
    let objectUrl: string | null = null;
    authFetch(url)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setState({ kind: "loaded", url, src: objectUrl });
      })
      .catch(() => {
        if (cancelled) return;
        setState({ kind: "error", url });
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url]);

  // url 変更時、effect 同期に setState せず、render 中の derived 値で
  // 「次の URL がまだ loaded じゃない」を loading として扱う。
  if (!url) {
    return { src: null, loading: false, error: false };
  }
  if (state.kind === "loaded" && state.url === url) {
    return { src: state.src, loading: false, error: false };
  }
  if (state.kind === "error" && state.url === url) {
    return { src: null, loading: false, error: true };
  }
  return { src: null, loading: true, error: false };
}

/**
 * 認証必須の URL からファイルを取得し、ブラウザのダウンロードダイアログを
 * 起動する。`<a href download>` だと Authorization ヘッダが付かず 401 に
 * なるので、いったん blob 化してから object URL でダウンロードする。
 */
export async function downloadAuthed(
  url: string,
  filename: string,
): Promise<void> {
  const res = await authFetch(url);
  if (!res.ok) {
    throw new Error(`download failed: HTTP ${res.status}`);
  }
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = objectUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    // Safari は click 直後に revoke すると落ちることがあるので少し遅らせる。
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }
}
