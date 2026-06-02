"use client";

import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";

/**
 * ページ左上に置く戻りボタン。
 *
 * 以前は各画面 (token / admin / record 詳細) に「← 一覧」として
 * `/records` への Link が直書きされていたが、Dashboard から来た人が
 * Records 一覧に飛ばされて混乱するため、`router.back()` で履歴を 1 つ
 * 戻る挙動に統一する。
 *
 * 履歴がない直接アクセスの場合は Dashboard (`/`) にフォールバックする。
 */
export function BackButton({
  label = "← 戻る",
  fallbackHref = "/",
}: {
  label?: string;
  fallbackHref?: string;
}) {
  const router = useRouter();
  const handleClick = () => {
    if (typeof window !== "undefined" && window.history.length > 1) {
      router.back();
    } else {
      router.push(fallbackHref);
    }
  };
  return (
    <Button
      variant="ghost"
      className="cursor-pointer"
      onClick={handleClick}
      type="button"
    >
      {label}
    </Button>
  );
}
