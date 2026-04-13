"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";

export interface ConditionFilter {
  key: string;
  value: string;
}

export function ConditionFilterPanel({
  filters,
  onChange,
}: {
  filters: ConditionFilter[];
  onChange: (filters: ConditionFilter[]) => void;
}) {
  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("");

  const handleAdd = () => {
    const key = newKey.trim();
    const value = newValue.trim();
    if (!key || !value) return;
    onChange([...filters, { key, value }]);
    setNewKey("");
    setNewValue("");
  };

  const handleRemove = (index: number) => {
    onChange(filters.filter((_, i) => i !== index));
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleAdd();
    }
  };

  return (
    <div className="space-y-2">
      {filters.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {filters.map((f, i) => (
            <Badge
              key={i}
              variant="secondary"
              className="gap-1 pr-1 text-xs"
            >
              {f.key}={f.value}
              <button
                className="ml-0.5 hover:text-destructive cursor-pointer text-muted-foreground"
                onClick={() => handleRemove(i)}
              >
                ×
              </button>
            </Badge>
          ))}
        </div>
      )}
      <div className="flex gap-2 items-center">
        <Input
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="条件名 (例: power)"
          className="h-8 text-xs w-32"
        />
        <span className="text-muted-foreground">=</span>
        <Input
          value={newValue}
          onChange={(e) => setNewValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="値 (例: 20)"
          className="h-8 text-xs w-32"
        />
        <Button
          size="sm"
          variant="outline"
          className="h-8 text-xs cursor-pointer"
          onClick={handleAdd}
          disabled={!newKey.trim() || !newValue.trim()}
        >
          追加
        </Button>
      </div>
    </div>
  );
}
