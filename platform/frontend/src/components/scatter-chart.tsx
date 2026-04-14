"use client";

import { useState } from "react";
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { RecordSummary } from "@/lib/api";

interface ChartPoint {
  x: number;
  y: number;
  id: string;
  title: string;
  group: string;
  fields: Record<string, unknown>;
}

const COLORS = [
  "#3b82f6",
  "#ef4444",
  "#22c55e",
  "#f59e0b",
  "#8b5cf6",
  "#ec4899",
  "#06b6d4",
  "#f97316",
  "#14b8a6",
  "#6366f1",
];

/**
 * フィールド値を使った数式を評価する。
 * 単純なフィールド名ならそのまま値を返し、
 * 演算子を含む場合は数式として評価する。
 */
function evalExpr(
  expr: string,
  fields: Record<string, unknown>
): number | null {
  if (!expr) return null;

  // 単純なフィールド名の場合
  if (expr in fields) {
    const v = fields[expr];
    return typeof v === "number" ? v : null;
  }

  // 数式: フィールド名を値に置換して評価
  try {
    let replaced = expr;
    // 長いキー名から先に置換（部分一致を防ぐ）
    const keys = Object.keys(fields).sort((a, b) => b.length - a.length);
    for (const k of keys) {
      const v = fields[k];
      if (typeof v !== "number") continue;
      // 単語境界でマッチ（フィールド名に使われる文字: 英数字 + _）
      const re = new RegExp(`\\b${k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "g");
      replaced = replaced.replace(re, String(v));
    }
    // 安全性: 数字・演算子・括弧・空白・小数点・e記法のみ許可
    if (!/^[\d\s+\-*/().e]+$/.test(replaced)) return null;
    const result = new Function(`return (${replaced})`)() as unknown;
    if (typeof result !== "number" || !isFinite(result)) return null;
    return result;
  } catch {
    return null;
  }
}

/** 式にフィールド参照が含まれるかを判定 */
function isExpression(expr: string): boolean {
  return /[+\-*/()]/.test(expr);
}

function AxisInput({
  label,
  value,
  onChange,
  numericKeys,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  numericKeys: string[];
}) {
  const [mode, setMode] = useState<"select" | "expr">("select");

  return (
    <div className="flex items-center gap-1">
      <span className="text-sm text-muted-foreground">{label}:</span>
      {mode === "select" ? (
        <>
          <select
            value={value}
            onChange={(e) => onChange(e.target.value)}
            className="h-8 rounded-md border bg-background px-2 text-xs"
          >
            <option value="">選択...</option>
            {numericKeys.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => {
              setMode("expr");
              onChange("");
            }}
            className="text-xs text-muted-foreground hover:text-primary px-1"
            title="数式入力に切り替え"
          >
            fx
          </button>
        </>
      ) : (
        <>
          <input
            type="text"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder="例: depth / area"
            className="h-8 rounded-md border bg-background px-2 text-xs w-40"
          />
          <button
            type="button"
            onClick={() => {
              setMode("select");
              onChange("");
            }}
            className="text-xs text-muted-foreground hover:text-primary px-1"
            title="リスト選択に切り替え"
          >
            リスト
          </button>
        </>
      )}
    </div>
  );
}

export function ConditionScatterChart({
  records,
  conditionsMap,
}: {
  records: RecordSummary[];
  conditionsMap: Map<string, Record<string, unknown>>;
}) {
  const [xExpr, setXExpr] = useState("");
  const [yExpr, setYExpr] = useState("");
  const [groupKey, setGroupKey] = useState("");

  // 数値キーを収集
  const numericKeys = new Set<string>();
  const allKeys = new Set<string>();
  conditionsMap.forEach((fields) => {
    Object.entries(fields).forEach(([k, v]) => {
      allKeys.add(k);
      if (typeof v === "number") numericKeys.add(k);
    });
  });
  const numericKeyList = Array.from(numericKeys).sort();
  const allKeyList = Array.from(allKeys).sort();

  const xLabel = xExpr || "X";
  const yLabel = yExpr || "Y";
  const ready = xExpr && yExpr;

  const groupedData: Map<string, ChartPoint[]> = new Map();
  if (ready) {
    for (const rec of records) {
      const fields = conditionsMap.get(rec.id);
      if (!fields) continue;
      const xVal = evalExpr(xExpr, fields);
      const yVal = evalExpr(yExpr, fields);
      if (xVal === null || yVal === null) continue;

      const group = groupKey
        ? String(fields[groupKey] ?? "unknown")
        : "all";

      if (!groupedData.has(group)) groupedData.set(group, []);
      groupedData.get(group)!.push({
        x: xVal,
        y: yVal,
        id: rec.id,
        title: rec.title,
        group,
        fields,
      });
    }
  }

  const groups = Array.from(groupedData.keys()).sort();
  const totalPoints = Array.from(groupedData.values()).reduce(
    (sum, g) => sum + g.length,
    0
  );

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">散布図</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex gap-3 items-center flex-wrap">
          <AxisInput
            label="X"
            value={xExpr}
            onChange={setXExpr}
            numericKeys={numericKeyList}
          />
          <AxisInput
            label="Y"
            value={yExpr}
            onChange={setYExpr}
            numericKeys={numericKeyList}
          />
          <div className="flex items-center gap-1">
            <span className="text-sm text-muted-foreground">色分け:</span>
            <select
              value={groupKey}
              onChange={(e) => setGroupKey(e.target.value)}
              className="h-8 rounded-md border bg-background px-2 text-xs"
            >
              <option value="">なし</option>
              {allKeyList.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
          </div>
          {ready && (
            <span className="text-xs text-muted-foreground">
              {totalPoints} 点
              {groups.length > 1 && ` / ${groups.length} グループ`}
            </span>
          )}
        </div>

        {ready && totalPoints > 0 && (
          <ResponsiveContainer width="100%" height={400}>
            <ScatterChart
              margin={{ top: 10, right: 30, bottom: 20, left: 20 }}
            >
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="x"
                type="number"
                name={xLabel}
                label={{
                  value: xLabel,
                  position: "insideBottom",
                  offset: -10,
                  style: { fontSize: 12 },
                }}
                tick={{ fontSize: 11 }}
              />
              <YAxis
                dataKey="y"
                type="number"
                name={yLabel}
                label={{
                  value: yLabel,
                  angle: -90,
                  position: "insideLeft",
                  offset: -5,
                  style: { fontSize: 12 },
                }}
                tick={{ fontSize: 11 }}
              />
              <Tooltip
                content={({ payload }) => {
                  if (!payload?.[0]) return null;
                  const p = payload[0].payload as ChartPoint;
                  const entries = Object.entries(p.fields).filter(
                    ([, v]) => v !== null && v !== undefined
                  );
                  return (
                    <div className="rounded border bg-popover p-2 text-xs shadow-md max-h-80 overflow-y-auto">
                      <div className="font-mono text-primary">{p.id}</div>
                      <div className="mb-1">{p.title}</div>
                      {isExpression(xExpr) && (
                        <div className="font-medium text-foreground flex justify-between gap-4">
                          <span>{xLabel}</span>
                          <span className="font-mono">{p.x.toPrecision(4)}</span>
                        </div>
                      )}
                      {isExpression(yExpr) && (
                        <div className="font-medium text-foreground flex justify-between gap-4">
                          <span>{yLabel}</span>
                          <span className="font-mono">{p.y.toPrecision(4)}</span>
                        </div>
                      )}
                      {entries.map(([k, v]) => (
                        <div
                          key={k}
                          className={`flex justify-between gap-4 ${
                            k === xExpr || k === yExpr
                              ? "font-medium text-foreground"
                              : "text-muted-foreground"
                          }`}
                        >
                          <span>{k}</span>
                          <span className="font-mono">{String(v)}</span>
                        </div>
                      ))}
                    </div>
                  );
                }}
              />
              {groupKey && groups.length > 1 && (
                <Legend
                  align="right"
                  verticalAlign="top"
                  wrapperStyle={{ fontSize: 11 }}
                />
              )}
              {groups.map((group, i) => (
                <Scatter
                  key={group}
                  name={groupKey ? group : undefined}
                  data={groupedData.get(group)!}
                  fill={COLORS[i % COLORS.length]}
                  r={3}
                />
              ))}
            </ScatterChart>
          </ResponsiveContainer>
        )}

        {ready && totalPoints === 0 && (
          <p className="text-center text-sm text-muted-foreground py-8">
            データがありません
          </p>
        )}
      </CardContent>
    </Card>
  );
}
