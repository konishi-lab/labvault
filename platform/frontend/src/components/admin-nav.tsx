"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth";

export function AdminNav() {
  const { role, isAdmin, authStatus } = useAuth();
  if (authStatus !== "authorized" || !isAdmin) return null;
  // /admin/pending は super-admin (legacy role) のみ。pending は team 紐付け前なので
  // team admin には開放しない。
  const isSuperAdmin = role === "admin";
  return (
    <>
      {isSuperAdmin && (
        <Link
          href="/admin/pending"
          className="text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          申請承認
        </Link>
      )}
      <Link
        href="/admin/users"
        className="text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        ユーザー
      </Link>
    </>
  );
}
