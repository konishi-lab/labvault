"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth";

export function AdminNav() {
  const { role, authStatus } = useAuth();
  if (authStatus !== "authorized" || role !== "admin") return null;
  return (
    <>
      <Link
        href="/admin/pending"
        className="text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        申請承認
      </Link>
      <Link
        href="/admin/users"
        className="text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        ユーザー
      </Link>
    </>
  );
}
