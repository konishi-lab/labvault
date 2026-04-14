"use client";

import Link from "next/link";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

export function ResultsCard({
  results,
  units,
  allResults,
}: {
  results: [string, unknown][];
  units: Record<string, string>;
  allResults: Record<string, unknown>;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">結果</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {results.map(([key, value], i) => {
          const unit = units[key];
          const analysisId = allResults[`${key}__analysis_id`] as
            | string
            | undefined;
          return (
            <div key={key}>
              {i > 0 && <Separator className="mb-2" />}
              <div className="flex justify-between items-start rounded px-1 -mx-1 py-0.5">
                <div>
                  <span className="text-muted-foreground">{key}</span>
                  {unit && (
                    <span className="text-xs text-blue-600 ml-1">
                      [{unit}]
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <span className="font-mono">
                    {String(value)}
                    {unit && (
                      <span className="text-muted-foreground ml-1">
                        {unit}
                      </span>
                    )}
                  </span>
                  {analysisId && (
                    <Link
                      href={`/records/${analysisId}`}
                      className="text-xs text-primary hover:underline"
                      title="解析レコード"
                    >
                      {analysisId}
                    </Link>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
