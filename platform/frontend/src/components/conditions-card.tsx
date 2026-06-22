"use client";

import { useState } from "react";
import { Edit2 } from "lucide-react";
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
  recordTitle,
  templateName,
  onUpdate,
  anchorId,
}: {
  recordId: string;
  conditions: [string, unknown][];
  units: Record<string, string>;
  descriptions: Record<string, string>;
  // Copy as SDK ボタン用 (任意): record の title と template_name を渡すと
  // `lab.new(title, template=..., **conditions)` snippet を生成する。
  // 省略時はボタンを表示しない (再現対象を持たない context での誤誘導防止)。
  recordTitle?: string;
  templateName?: string | null;
  onUpdate: (
    units: Record<string, string>,
    descriptions: Record<string, string>
  ) => void;
  // sticky summary chip からの smooth scroll 用 anchor。
  anchorId?: string;
}) {
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editUnit, setEditUnit] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [saving, setSaving] = useState(false);
  const [copiedAt, setCopiedAt] = useState<number | null>(null);
  const copyJustNow = copiedAt && Date.now() - copiedAt < 2000;

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

  // Python リテラルへの変換。conditions の値は flat scalar 規約により
  // str / int / float / bool / None / 短い list のみ (v0.3.0 規約)。
  const toPyLiteral = (value: unknown): string => {
    if (value === null || value === undefined) return "None";
    if (typeof value === "boolean") return value ? "True" : "False";
    if (typeof value === "number") return String(value);
    if (Array.isArray(value)) {
      return `[${value.map(toPyLiteral).join(", ")}]`;
    }
    // str: シングルクオート、内部の \ と ' を escape
    const s = String(value).replace(/\\/g, "\\\\").replace(/'/g, "\\'");
    return `'${s}'`;
  };

  const buildSnippet = (): string => {
    const titleLiteral = toPyLiteral(recordTitle || "");
    const lines = [`lab.new(`, `    ${titleLiteral},`];
    if (templateName) {
      lines.push(`    template=${toPyLiteral(templateName)},`);
    }
    for (const [key, value] of conditions) {
      // Python identifier safe な key のみ kwarg に。それ以外は念のため
      // **{} 形式で出すのが安全だが、conditions の key は alias 正規化
      // 済で英数 _ のみのはず。検証のみ。
      if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) {
        lines.push(`    ${key}=${toPyLiteral(value)},`);
      }
    }
    lines.push(`)`);
    return lines.join("\n");
  };

  const handleCopySnippet = async () => {
    const snippet = buildSnippet();
    try {
      await navigator.clipboard.writeText(snippet);
      setCopiedAt(Date.now());
      setTimeout(() => setCopiedAt(null), 2000);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = snippet;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        setCopiedAt(Date.now());
        setTimeout(() => setCopiedAt(null), 2000);
      } catch {
        // 何もできない
      }
      ta.remove();
    }
  };

  return (
    <Card id={anchorId} className="scroll-mt-20">
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-base">条件</CardTitle>
          {recordTitle && (
            <Button
              variant="outline"
              size="xs"
              onClick={handleCopySnippet}
              title="この record の条件を `lab.new(...)` snippet として clipboard にコピー (Notebook に貼り付けて再現)"
            >
              {copyJustNow ? "✓ コピーしました" : "Copy as SDK"}
            </Button>
          )}
        </div>
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
                className="group flex justify-between items-start cursor-pointer hover:bg-muted/30 rounded px-1 -mx-1 py-0.5 transition-colors"
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
                {/* 単位は label の [unit] 側で表示済なので、値は数字だけ。
                    以前は値の隣にも単位を付けていたが、"two_theta_start_deg
                    [deg]: 10 deg" のように二重に見えるため削除。 */}
                <div className="flex items-center gap-2">
                  <span className="font-mono">{String(value)}</span>
                  {/* 編集 affordance: 常時薄表示 (hover-only は iPad / 装置 PC
                      で発見不能なため、薄く見せて hover で濃く)。 */}
                  <Edit2
                    className="h-3 w-3 text-muted-foreground/40 group-hover:text-muted-foreground transition-colors"
                    aria-hidden
                  />
                </div>
              </div>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
