"use client";

import { WelcomeScreen } from "@/components/welcome-screen";

/**
 * 永続 URL のようこそ画面。
 *
 * AuthGate は `showWelcome === true` のときも welcome を出すが、それは初回
 * ログインで 1 回だけ。装置 PC 手順やトークン発行案内をあとから見直したい
 * ユーザー向けに、いつでもアクセスできる /welcome を別途用意する。
 *
 * 表示内容は AuthGate 経由のものと同じ WelcomeScreen を再利用。
 */
export default function WelcomePage() {
  return <WelcomeScreen />;
}
