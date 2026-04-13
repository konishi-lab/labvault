"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { addNote } from "@/lib/api";
import type { NoteResponse } from "@/lib/api";

export function NoteForm({
  recordId,
  onAdded,
}: {
  recordId: string;
  onAdded: (note: NoteResponse) => void;
}) {
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed) return;

    setSaving(true);
    try {
      const updated = await addNote(recordId, trimmed);
      const latest = updated.notes[updated.notes.length - 1];
      if (latest) onAdded(latest);
      setText("");
    } catch {
      // ignore
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex gap-2">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="メモを追加..."
        rows={2}
        className="flex-1 rounded-md border bg-background px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-ring"
        disabled={saving}
      />
      <Button
        type="submit"
        size="sm"
        className="self-end cursor-pointer"
        disabled={!text.trim() || saving}
      >
        {saving ? "..." : "追加"}
      </Button>
    </form>
  );
}
