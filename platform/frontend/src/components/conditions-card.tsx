"use client";

import { useState } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { updateUnits } from "@/lib/api";

export function ConditionsCard({
  recordId,
  conditions,
  units,
  descriptions,
  onUpdate,
}: {
  recordId: string;
  conditions: [string, unknown][];
  units: Record<string, string>;
  descriptions: Record<string, string>;
  onUpdate: (
    units: Record<string, string>,
    descriptions: Record<string, string>
  ) => void;
}) {
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editUnit, setEditUnit] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [saving, setSaving] = useState(false);

  const startEdit = (key: string) => {
    setEditingKey(key);
    setEditUnit(units[key] || "");
    setEditDesc(descriptions[key] || "");
  };

  const handleSave = async () => {
    if (!editingKey) return;
    setSaving(true);
    try {
      const newUnits = { ...units, [editingKey]: editUnit };
      const newDescs = { ...descriptions, [editingKey]: editDesc };
      if (!editUnit) delete newUnits[editingKey];
      if (!editDesc) delete newDescs[editingKey];
      await updateUnits(recordId, newUnits, newDescs);
      onUpdate(newUnits, newDescs);
      setEditingKey(null);
    } catch {
      // ignore
    } finally {
      setSaving(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleSave();
    } else if (e.key === "Escape") {
      setEditingKey(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">条件</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {conditions.map(([key, value], i) => (
          <div key={key}>
            {i > 0 && <Separator className="mb-2" />}
            {editingKey === key ? (
              <div className="space-y-2">
                <div className="flex justify-between">
                  <span className="text-muted-foreground font-medium">
                    {key}
                  </span>
                  <span className="font-mono">{String(value)}</span>
                </div>
                <div className="flex gap-2">
                  <Input
                    value={editUnit}
                    onChange={(e) => setEditUnit(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="単位 (例: J, um, s)"
                    className="h-7 text-xs w-24"
                    autoFocus
                    disabled={saving}
                  />
                  <Input
                    value={editDesc}
                    onChange={(e) => setEditDesc(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="説明 (任意)"
                    className="h-7 text-xs flex-1"
                    disabled={saving}
                  />
                  <Button
                    size="sm"
                    className="h-7 text-xs cursor-pointer"
                    onClick={handleSave}
                    disabled={saving}
                  >
                    保存
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 text-xs cursor-pointer"
                    onClick={() => setEditingKey(null)}
                  >
                    ×
                  </Button>
                </div>
              </div>
            ) : (
              <div
                className="flex justify-between items-start cursor-pointer hover:bg-muted/30 rounded px-1 -mx-1 py-0.5 transition-colors"
                onClick={() => startEdit(key)}
                title="クリックして単位・説明を編集"
              >
                <div>
                  <span className="text-muted-foreground">{key}</span>
                  {units[key] && (
                    <span className="text-xs text-blue-600 ml-1">
                      [{units[key]}]
                    </span>
                  )}
                  {descriptions[key] && (
                    <span className="text-xs text-muted-foreground ml-1">
                      — {descriptions[key]}
                    </span>
                  )}
                </div>
                <span className="font-mono">
                  {String(value)}
                  {units[key] && (
                    <span className="text-muted-foreground ml-1">
                      {units[key]}
                    </span>
                  )}
                </span>
              </div>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
