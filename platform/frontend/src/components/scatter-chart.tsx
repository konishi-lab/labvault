"use client";

import { useState } from "react";
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import type { RecordSummary } from "@/lib/api";

interface ChartPoint {
  x: number;
  y: number;
  id: string;
  title: string;
}

export function ConditionScatterChart({
  records,
  conditionsMap,
}: {
  records: RecordSummary[];
  conditionsMap: Map<string, Record<string, unknown>>;
}) {
  const [xKey, setXKey] = useState("");
  const [yKey, setYKey] = useState("");
  const [showChart, setShowChart] = useState(false);

  // 利用可能なキーを収集
  const allKeys = new Set<string>();
  conditionsMap.forEach((cond) => {
    Object.entries(cond).forEach(([k, v]) => {
      if (typeof v === "number") allKeys.add(k);
    });
  });
  const keyList = Array.from(allKeys).sort();

  const handleShow = () => {
    if (xKey && yKey) setShowChart(true);
  };

  const data: ChartPoint[] = [];
  if (showChart && xKey && yKey) {
    for (const rec of records) {
      const cond = conditionsMap.get(rec.id);
      if (!cond) continue;
      const xVal = cond[xKey];
      const yVal = cond[yKey];
      if (typeof xVal === "number" && typeof yVal === "number") {
        data.push({ x: xVal, y: yVal, id: rec.id, title: rec.title });
      }
    }
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">散布図</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex gap-2 items-center flex-wrap">
          <span className="text-sm text-muted-foreground">X:</span>
          <select
            value={xKey}
            onChange={(e) => {
              setXKey(e.target.value);
              setShowChart(false);
            }}
            className="h-8 rounded-md border bg-background px-2 text-xs"
          >
            <option value="">選択...</option>
            {keyList.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          <span className="text-sm text-muted-foreground">Y:</span>
          <select
            value={yKey}
            onChange={(e) => {
              setYKey(e.target.value);
              setShowChart(false);
            }}
            className="h-8 rounded-md border bg-background px-2 text-xs"
          >
            <option value="">選択...</option>
            {keyList.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          <Button
            size="sm"
            className="h-8 text-xs cursor-pointer"
            onClick={handleShow}
            disabled={!xKey || !yKey}
          >
            表示
          </Button>
          {showChart && (
            <span className="text-xs text-muted-foreground">
              {data.length} 点
            </span>
          )}
        </div>

        {showChart && data.length > 0 && (
          <ResponsiveContainer width="100%" height={400}>
            <ScatterChart margin={{ top: 10, right: 30, bottom: 20, left: 20 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="x"
                type="number"
                name={xKey}
                label={{
                  value: xKey,
                  position: "insideBottom",
                  offset: -10,
                  style: { fontSize: 12 },
                }}
                tick={{ fontSize: 11 }}
              />
              <YAxis
                dataKey="y"
                type="number"
                name={yKey}
                label={{
                  value: yKey,
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
                  return (
                    <div className="rounded border bg-popover p-2 text-xs shadow-md">
                      <div className="font-mono text-primary">{p.id}</div>
                      <div>{p.title}</div>
                      <div className="mt-1 text-muted-foreground">
                        {xKey}: {p.x}
                      </div>
                      <div className="text-muted-foreground">
                        {yKey}: {p.y}
                      </div>
                    </div>
                  );
                }}
              />
              <Scatter data={data} fill="#3b82f6" r={3} />
            </ScatterChart>
          </ResponsiveContainer>
        )}

        {showChart && data.length === 0 && (
          <p className="text-center text-sm text-muted-foreground py-8">
            データがありません
          </p>
        )}
      </CardContent>
    </Card>
  );
}
