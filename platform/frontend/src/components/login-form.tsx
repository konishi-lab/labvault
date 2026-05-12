"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/lib/auth";

type Mode = "signin" | "signup";

export function LoginForm() {
  const { signIn, signInWithEmail, signUpWithEmail } = useAuth();
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!email.trim() || !password) {
      setError("メールアドレスとパスワードを入力してください");
      return;
    }
    if (mode === "signup" && password.length < 8) {
      setError("パスワードは 8 文字以上にしてください");
      return;
    }
    setSubmitting(true);
    try {
      if (mode === "signin") {
        await signInWithEmail(email.trim(), password);
      } else {
        await signUpWithEmail(
          email.trim(),
          password,
          displayName.trim() || undefined,
        );
      }
    } catch (err) {
      // Firebase Auth のエラーコードを軽く翻訳
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes("auth/invalid-credential") || msg.includes("auth/wrong-password")) {
        setError("メールアドレスまたはパスワードが違います");
      } else if (msg.includes("auth/email-already-in-use")) {
        setError("このメールアドレスは既に登録されています");
      } else if (msg.includes("auth/invalid-email")) {
        setError("メールアドレスの形式が不正です");
      } else if (msg.includes("auth/weak-password")) {
        setError("パスワードが弱すぎます (8 文字以上推奨)");
      } else if (msg.includes("auth/operation-not-allowed")) {
        setError(
          "メールアドレス/パスワード認証が無効です。管理者に連絡してください。",
        );
      } else {
        setError(msg);
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto flex min-h-[60vh] w-full max-w-sm flex-col items-center justify-center gap-6">
      <div className="text-center">
        <div className="text-lg font-semibold">labvault にログイン</div>
        <div className="text-sm text-muted-foreground">
          許可されたアカウントのみアクセスできます
        </div>
      </div>

      <Button onClick={signIn} className="w-full" variant="outline">
        Google でログイン
      </Button>

      <div className="flex w-full items-center gap-3 text-xs uppercase text-muted-foreground">
        <div className="h-px flex-1 bg-border" />
        または
        <div className="h-px flex-1 bg-border" />
      </div>

      <div className="flex w-full gap-1 rounded-md border bg-muted/40 p-1 text-xs">
        <button
          type="button"
          onClick={() => setMode("signin")}
          className={`flex-1 rounded px-2 py-1 transition-colors ${
            mode === "signin"
              ? "bg-background font-medium text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          メールでログイン
        </button>
        <button
          type="button"
          onClick={() => setMode("signup")}
          className={`flex-1 rounded px-2 py-1 transition-colors ${
            mode === "signup"
              ? "bg-background font-medium text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          メールで新規登録
        </button>
      </div>

      <form onSubmit={handleSubmit} className="w-full space-y-3">
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs font-medium text-muted-foreground">
            メールアドレス
          </span>
          <Input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={submitting}
            autoComplete="email"
            required
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs font-medium text-muted-foreground">
            パスワード {mode === "signup" && "(8 文字以上)"}
          </span>
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={submitting}
            autoComplete={
              mode === "signin" ? "current-password" : "new-password"
            }
            required
          />
        </label>
        {mode === "signup" && (
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-xs font-medium text-muted-foreground">
              表示名 (任意)
            </span>
            <Input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              disabled={submitting}
              autoComplete="name"
              placeholder="山田 太郎"
            />
          </label>
        )}

        {error && <p className="text-sm text-destructive">{error}</p>}

        <Button type="submit" className="w-full" disabled={submitting}>
          {submitting
            ? "処理中..."
            : mode === "signin"
              ? "ログイン"
              : "新規登録"}
        </Button>
      </form>

      <p className="text-center text-xs text-muted-foreground">
        新規登録後、管理者の承認が必要です
      </p>
    </div>
  );
}
