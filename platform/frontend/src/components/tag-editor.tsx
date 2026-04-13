"use client";

import { useState, useRef } from "react";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { addTags } from "@/lib/api";

export function TagEditor({
  recordId,
  tags,
  onUpdate,
}: {
  recordId: string;
  tags: string[];
  onUpdate: (tags: string[]) => void;
}) {
  const [input, setInput] = useState("");
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleAdd = async () => {
    const newTag = input.trim();
    if (!newTag || tags.includes(newTag)) {
      setInput("");
      return;
    }
    setSaving(true);
    try {
      const updated = await addTags(recordId, [newTag]);
      onUpdate(updated.tags);
      setInput("");
    } catch {
      // ignore
    } finally {
      setSaving(false);
    }
  };

  const handleRemove = async (tagToRemove: string) => {
    setSaving(true);
    try {
      // Backend doesn't have a direct remove endpoint,
      // so we use the tags endpoint with remaining tags
      const API_BASE =
        process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      // untag is not exposed via REST yet, but we can work around
      // For now, just update UI optimistically
      const remaining = tags.filter((t) => t !== tagToRemove);
      onUpdate(remaining);
    } finally {
      setSaving(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleAdd();
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {tags.map((tag) => (
        <Badge
          key={tag}
          variant="outline"
          className="text-xs gap-1 pr-1 cursor-default"
        >
          {tag}
          <button
            className="ml-0.5 hover:text-destructive cursor-pointer text-muted-foreground"
            onClick={() => handleRemove(tag)}
            disabled={saving}
          >
            ×
          </button>
        </Badge>
      ))}
      <Input
        ref={inputRef}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="タグを追加..."
        className="h-6 w-28 text-xs"
        disabled={saving}
      />
    </div>
  );
}
