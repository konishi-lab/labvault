"use client";

import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";

export interface ConditionFilter {
  key: string;
  value: string;
}

/**
 * 条件 chip 入力パネル。
 *
 * `keySuggestions` を渡すと key 入力欄に HTML `<datalist>` で候補が出る
 * (template の `indexed_fields` を想定; これらは Firestore に push down
 * される)。自由入力も可能だが、suggest にない key は post-filter 経由
 * になる点に注意。
 */
export function ConditionFilterPanel({
  filters,
  onChange,
  keySuggestions,
}: {
  filters: ConditionFilter[];
  onChange: (filters: ConditionFilter[]) => void;
  keySuggestions?: string[];
}) {
  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("");
  const listId = useId();

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

  const hasSuggestions = (keySuggestions?.length ?? 0) > 0;

  return (
    <div className="space-y-2">
      {filters.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {filters.map((f, i) => (
            <Badge key={i} variant="secondary" className="gap-1 pr-1 text-xs">
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
          placeholder={
            hasSuggestions
              ? "条件名 (候補から選択)"
              : "条件名 (例: power)"
          }
          className="h-8 text-xs w-40"
          list={hasSuggestions ? listId : undefined}
          autoComplete="off"
        />
        {hasSuggestions && (
          <datalist id={listId}>
            {keySuggestions!.map((k) => (
              <option key={k} value={k} />
            ))}
          </datalist>
        )}
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
      {hasSuggestions && (
        <p className="text-[10px] text-muted-foreground">
          候補は template の indexed_fields です。これらの key は Firestore
          に push down されて高速に絞り込まれます。それ以外の自由入力 key
          は post-filter 経由になります。
        </p>
      )}
    </div>
  );
}
