"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { BackButton } from "@/components/back-button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchRecord, fetchChildren, fetchChildrenConditions } from "@/lib/api";
import type { FileInfo, RecordDetail, RecordSummary } from "@/lib/api";
import { useAuthedBlobUrl, downloadAuthed } from "@/lib/authed-blob";
import { BulkUploadButton } from "@/components/bulk-upload";
import { SortableRecordTable } from "@/components/sortable-record-table";
import { TagEditor } from "@/components/tag-editor";
import { NoteForm } from "@/components/note-form";
import { ConditionsCard } from "@/components/conditions-card";
import { ResultsCard } from "@/components/results-card";
import { ConditionFilterPanel } from "@/components/condition-filter";
import type { ConditionFilter } from "@/components/condition-filter";
import { ConditionScatterChart } from "@/components/scatter-chart";
import { SummaryChips } from "@/components/summary-chips";
import { CellLogSection } from "@/components/cell-log-section";
import { ShareDialog } from "@/components/share-dialog";
import { useAuth } from "@/lib/auth";
import type { NoteResponse } from "@/lib/api";

const statusColor: Record<string, string> = {
  running: "bg-blue-100 text-blue-800",
  success: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  partial: "bg-yellow-100 text-yellow-800",
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("ja-JP");
}

function fileExt(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot + 1).toUpperCase() : "FILE";
}

function fileIcon(name: string): string {
  const ext = fileExt(name).toLowerCase();
  const icons: Record<string, string> = {
    vk4: "\u{1F52C}", // 🔬 microscope
    csv: "\u{1F4CA}", // 📊
    json: "\u{1F4C4}", // 📄
    txt: "\u{1F4DD}", // 📝
    npy: "\u{1F522}", // 🔢
    png: "\u{1F5BC}", // 🖼
    jpg: "\u{1F5BC}",
    tif: "\u{1F5BC}",
    tiff: "\u{1F5BC}",
    ras: "\u{1F4C8}", // 📈
  };
  return icons[ext] || "\u{1F4CE}"; // 📎 default
}

// D1 (PR #81): 拡張子別の 7 色 / original_type 別の 4 色は、隣の絵文字
// アイコン + ラベル文字列だけで充分情報量を持つので削除。status の 4 色
// (青 / 緑 / 赤 / 黄) と意味衝突する (csv 緑 = success 緑 等) のを構造的に
// 解消し、accessibility (色覚多様性) も改善する。

// DataRef.original_type は SDK が `add_object` 経路で付与する semantic タグ。
// "ndarray" → np.ndarray, "figure" → matplotlib.Figure, ... のように
// 「何の Python オブジェクト由来か」を拡張子推測ではなく metadata から
// 判別可能にする。null の場合は raw 取り込み (add_file / add_bytes) または
// 旧 record で未付与のもの。本 PR から色なし span のヒント表示に降格。
function originLabel(original: string | null): string | null {
  if (!original) return null;
  switch (original) {
    case "ndarray":
      return "Array";
    case "figure":
      return "Figure";
    case "dataframe":
      return "Table";
    case "dict":
      return "Dict";
    case "list":
      return "List";
    case "str":
      return "Text";
    case "bytes":
      return "Bytes";
    default:
      return original; // 将来追加される type は raw 値を出す
  }
}

function previewType(name: string): "vk4" | "image" | null {
  const lower = name.toLowerCase();
  if (lower.endsWith(".vk4")) return "vk4";
  if (lower.endsWith(".png") || lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image";
  return null;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function imageUrl(recordId: string, filename: string): string {
  const ptype = previewType(filename);
  return ptype === "vk4"
    ? `${API_BASE}/api/records/${recordId}/preview/${encodeURIComponent(filename)}`
    : `${API_BASE}/api/records/${recordId}/files/${encodeURIComponent(filename)}`;
}

function ImageThumbnail({
  recordId,
  filename,
  label,
  onClickExpand,
}: {
  recordId: string;
  filename: string;
  label?: string;
  onClickExpand?: () => void;
}) {
  const { src, loading, error } = useAuthedBlobUrl(imageUrl(recordId, filename));

  return (
    <div
      className="relative rounded-lg border bg-muted/30 p-1 cursor-pointer hover:ring-2 hover:ring-primary/30 transition-all"
      onClick={onClickExpand}
    >
      {loading && <Skeleton className="h-40 w-full rounded" />}
      {error && (
        <p className="h-40 flex items-center justify-center text-xs text-muted-foreground">
          読み込めません
        </p>
      )}
      {src && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt={filename}
          className="w-full h-40 object-contain rounded"
        />
      )}
      {label && (
        <p className="text-xs text-center text-muted-foreground mt-1 truncate">
          {label}
        </p>
      )}
    </div>
  );
}

function ImageModal({
  recordId,
  filename,
  onClose,
}: {
  recordId: string;
  filename: string;
  onClose: () => void;
}) {
  const { src, loading, error } = useAuthedBlobUrl(imageUrl(recordId, filename));
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70"
      onClick={onClose}
    >
      <div className="relative max-w-[90vw] max-h-[90vh]">
        {loading && (
          <Skeleton className="h-[60vh] w-[60vw] rounded-lg bg-white/20" />
        )}
        {error && (
          <p className="text-sm text-white/80 bg-black/50 px-4 py-3 rounded">
            読み込めません
          </p>
        )}
        {src && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={src}
            alt={filename}
            className="max-w-full max-h-[90vh] rounded-lg"
          />
        )}
        <p className="absolute bottom-2 left-2 text-xs text-white/80 bg-black/50 px-2 py-1 rounded">
          {filename}
        </p>
      </div>
    </div>
  );
}

function FileSection({
  recordId,
  files,
  anchorId,
}: {
  recordId: string;
  files: FileInfo[];
  // sticky summary chip からの smooth scroll 用 anchor。
  // 2 つの Card のうち最初に存在する方 (画像 → 無ければデータ) に付ける。
  anchorId?: string;
}) {
  const [expandedImage, setExpandedImage] = useState<string | null>(null);

  const imageFiles = files.filter((f) => previewType(f.name) !== null);
  const dataFiles = files.filter((f) => previewType(f.name) === null);
  // 画像と data の 2 つの Card のうち、最初に rendering される方に anchor を付ける。
  const anchorOnImage = anchorId && imageFiles.length > 0;
  const anchorOnData = anchorId && !anchorOnImage && dataFiles.length > 0;

  return (
    <>
      {expandedImage && (
        <ImageModal
          recordId={recordId}
          filename={expandedImage}
          onClose={() => setExpandedImage(null)}
        />
      )}

      {imageFiles.length > 0 && (
        <Card
          id={anchorOnImage ? anchorId : undefined}
          className="md:col-span-2 scroll-mt-20"
        >
          <CardHeader>
            <CardTitle className="text-base">
              画像 ({imageFiles.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              {imageFiles.map((file) => (
                <ImageThumbnail
                  key={file.name}
                  recordId={recordId}
                  filename={file.name}
                  label={file.name}
                  onClickExpand={() => setExpandedImage(file.name)}
                />
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {dataFiles.length > 0 && (
        <Card
          id={anchorOnData ? anchorId : undefined}
          className="md:col-span-2 scroll-mt-20"
        >
          <CardHeader>
            <CardTitle className="text-base">
              データファイル ({dataFiles.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {dataFiles.map((file, i) => (
              <div key={file.name}>
                {i > 0 && <Separator className="mb-2" />}
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="flex items-center gap-2 min-w-0 flex-wrap">
                    <span className="shrink-0">{fileIcon(file.name)}</span>
                    <span className="font-mono truncate">{file.name}</span>
                    {/* D1: 拡張子バッジを muted + アイコン (色なし) に統一 */}
                    <Badge
                      variant="outline"
                      className="shrink-0 text-xs font-mono bg-muted text-muted-foreground border-transparent"
                    >
                      {fileExt(file.name)}
                    </Badge>
                    {/* D1: original_type は色なしの中黒 span に降格 */}
                    {originLabel(file.original_type) && (
                      <span
                        className="shrink-0 text-xs text-muted-foreground/70"
                        title={`保存元の Python 型: ${file.original_type}`}
                      >
                        · {originLabel(file.original_type)}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-muted-foreground">
                      {file.size_bytes > 0 ? formatBytes(file.size_bytes) : "-"}
                    </span>
                    <button
                      type="button"
                      onClick={() => {
                        const url = `${API_BASE}/api/records/${recordId}/files/${encodeURIComponent(file.name)}?download=1`;
                        downloadAuthed(url, file.name).catch(() => {
                          window.alert(`ダウンロードに失敗しました: ${file.name}`);
                        });
                      }}
                      className="text-xs text-primary hover:underline cursor-pointer"
                    >
                      DL
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

export default function RecordDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const { user, currentTeam, teams, isAdmin } = useAuth();
  const [record, setRecord] = useState<RecordDetail | null>(null);
  const [children, setChildren] = useState<RecordSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetchRecord(id),
      fetchChildren(id, { limit: 10000 }).catch(() => ({
        items: [],
        total: 0,
      })),
    ])
      .then(([rec, kids]) => {
        setRecord(rec);
        setChildren(kids.items);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (error || !record) {
    return (
      <div className="space-y-4">
        <BackButton />
        <p className="text-destructive">
          {error || "レコードが見つかりません"}
        </p>
      </div>
    );
  }

  const conditions = Object.entries(record.conditions);
  const results = Object.entries(record.results).filter(
    ([key]) => !key.endsWith("__analysis_id")
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4 flex-wrap">
        <BackButton />
        <h1 className="text-2xl font-bold tracking-tight">{record.title}</h1>
        <Badge variant="secondary" className={statusColor[record.status]}>
          {record.status}
        </Badge>
        {/* D1: context chip は outline + 先頭アイコンで統一 (色なし)。
            status の 4 色だけ意味色として残し、リンクであることだけを
            伝える chip は muted/outline で揃える。 */}
        {record.template_name && (
          <Link
            href={`/records?template=${encodeURIComponent(record.template_name)}`}
            title={`template "${record.template_name}" の record を一覧表示`}
          >
            <Badge
              variant="outline"
              className="text-xs cursor-pointer hover:bg-muted gap-1"
            >
              <span aria-hidden>📎</span>template: {record.template_name}
            </Badge>
          </Link>
        )}
        {record.parent_id && (
          <Link
            href={`/records/${record.parent_id}`}
            title="親 record (実験全体) の詳細へ"
          >
            <Badge
              variant="outline"
              className="text-xs cursor-pointer hover:bg-muted gap-1"
            >
              <span aria-hidden>↑</span>parent: {record.parent_id}
            </Badge>
          </Link>
        )}
        {/* S1-SEC2 (2026-06-29): record の audit identity 経路。
            "share-link" だと外部 token 由来で作成 / 最後の更新がされている
            ことを明示する。pseudo_email が実在 user の email と衝突して
            いても、ここで構造的に区別できる。
            created と updated を分けて表示するのは「最初は本物・後で
            token」のようなケースを見分けるため。 */}
        {(record.created_audit_source === "share-link" ||
          record.updated_audit_source === "share-link") && (
          <Badge
            variant="outline"
            className="text-xs gap-1 bg-amber-50 border-amber-300 text-amber-900"
            title={
              record.created_audit_source === "share-link" &&
              record.updated_audit_source === "share-link"
                ? "この record は外部共有 token (ls_*) で作成され、最後の更新も token 経由です"
                : record.created_audit_source === "share-link"
                  ? "この record は外部共有 token (ls_*) で作成されました"
                  : "この record の最後の更新は外部共有 token (ls_*) 経由です"
            }
          >
            <span aria-hidden>🔗</span>
            {record.created_audit_source === "share-link" &&
            record.updated_audit_source === "share-link"
              ? "外部 token 由来"
              : record.created_audit_source === "share-link"
                ? "外部 token で作成"
                : "外部 token で更新"}
          </Badge>
        )}
        {/* S1 Phase 1B: 共有モーダル。read 権限があれば「共有」ボタン
            自体は出す (中身で grant 主体判定 + 自分の role 表示)。 */}
        <div className="ml-auto">
          <ShareDialog
            recordId={id}
            createdBy={record.created_by}
            ownerTeam={currentTeam}
            initialShares={record.shares ?? null}
            currentUserEmail={user?.email ?? null}
            isSuperAdmin={isAdmin}
            isOwnerTeamAdmin={
              currentTeam !== null &&
              teams.some(
                (t) => t.team_id === currentTeam && t.role === "admin",
              )
            }
            onUpdated={(shares) => setRecord({ ...record, shares })}
          />
        </div>
      </div>

      <SummaryChips
        conditionsCount={conditions.length}
        resultsCount={results.length}
        filesCount={record.files.length}
        notesCount={record.notes.length}
        childrenCount={children.length}
        conditionKeys={Object.keys(record.conditions)}
        resultKeys={Object.keys(record.results)}
        requiredConditions={record.template_required_conditions ?? []}
        requiredResults={record.template_required_results ?? []}
      />

      <div className="grid gap-6 md:grid-cols-2">
        {/* 基本情報 */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">基本情報</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">ID</span>
              <span className="font-mono font-semibold">{record.id}</span>
            </div>
            <Separator />
            <div className="flex justify-between">
              <span className="text-muted-foreground">タイプ</span>
              <span>{record.type}</span>
            </div>
            <Separator />
            <div className="flex justify-between">
              <span className="text-muted-foreground">作成者</span>
              <span>{record.created_by || "-"}</span>
            </div>
            <Separator />
            <div className="flex justify-between">
              <span className="text-muted-foreground">作成日</span>
              <span>{formatDate(record.created_at)}</span>
            </div>
            <Separator />
            <div className="flex justify-between">
              <span className="text-muted-foreground">更新日</span>
              <span>{formatDate(record.updated_at)}</span>
            </div>
            <Separator />
            <div className="space-y-1">
              <span className="text-muted-foreground">タグ</span>
              <TagEditor
                recordId={id}
                tags={record.tags}
                onUpdate={(newTags) =>
                  setRecord({ ...record, tags: newTags })
                }
              />
            </div>
          </CardContent>
        </Card>

        {/* 条件 */}
        {conditions.length > 0 && (
          <ConditionsCard
            recordId={id}
            anchorId="section-conditions"
            conditions={conditions}
            units={record.condition_units || {}}
            descriptions={record.condition_descriptions || {}}
            // Copy as SDK ボタン用: title と template_name を渡して
            // lab.new(...) snippet を生成。
            recordTitle={record.title}
            templateName={record.template_name ?? null}
            onUpdate={(units, descs) =>
              setRecord({
                ...record,
                condition_units: units,
                condition_descriptions: descs,
              })
            }
          />
        )}

        {/* 結果 */}
        {results.length > 0 && (
          <ResultsCard
            recordId={id}
            anchorId="section-results"
            results={results}
            units={record.result_units || {}}
            descriptions={record.result_descriptions || {}}
            templateUnits={record.template_result_units || {}}
            templateDescriptions={record.template_result_descriptions || {}}
            allResults={record.results}
            onUpdate={(units, descs) =>
              setRecord({
                ...record,
                result_units: units,
                result_descriptions: descs,
              })
            }
          />
        )}

        {/* ファイル */}
        {record.files.length > 0 && (
          <FileSection
            recordId={id}
            files={record.files}
            anchorId="section-files"
          />
        )}

        {/* 条件 / 結果 / ファイル / 子レコードが全て空のときの案内。
            ローディングミスではなく単に未投入であることを明示する。 */}
        {conditions.length === 0 &&
          results.length === 0 &&
          record.files.length === 0 &&
          children.length === 0 && (
            <Card className="md:col-span-2 border-dashed">
              <CardContent className="py-6 text-center text-sm text-muted-foreground">
                このレコードには条件・結果・ファイル・子レコードがまだ
                投入されていません。SDK ({" "}
                <code className="rounded bg-muted px-1 py-0.5">
                  exp.conditions(...) / exp.results[...] / exp.add(...) /
                  exp.subrecord(...)
                </code>
                ) や Web UI から追加できます。
              </CardContent>
            </Card>
          )}

        {/* メモ */}
        <Card id="section-notes" className="md:col-span-2 scroll-mt-20">
          <CardHeader>
            <CardTitle className="text-base">
              メモ ({record.notes.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-sm">
            {record.notes.map((note, i) => (
              <div key={i} className="flex gap-3">
                <span className="shrink-0 text-muted-foreground text-xs">
                  {formatDate(note.created_at)}
                </span>
                <span>{note.text}</span>
              </div>
            ))}
            <Separator />
            <NoteForm
              recordId={id}
              onAdded={(note) =>
                setRecord({
                  ...record,
                  notes: [...record.notes, note],
                })
              }
            />
          </CardContent>
        </Card>

        {/* Notebook セルログ (R13 露出) — IPython hooks 自動記録の record
            のみ表示 (CellLogSection が空ならカード自体出さない) */}
        <CellLogSection recordId={id} anchorId="section-cells" />

        {/* サブレコード */}
        {children.length > 0 && (
          <ChildrenSection
            recordId={id}
            children={children}
            onRefresh={() => {
              fetchChildren(id, { limit: 10000 })
                .then((res) => setChildren(res.items))
                .catch(() => {});
            }}
          />
        )}
      </div>
    </div>
  );
}

function ColumnPicker({
  label,
  keys,
  selected,
  onChange,
}: {
  label: string;
  keys: string[];
  selected: string[];
  onChange: (cols: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  if (keys.length === 0) return null;

  const toggle = (key: string) => {
    if (selected.includes(key)) {
      onChange(selected.filter((c) => c !== key));
    } else {
      onChange([...selected, key]);
    }
  };

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <Button
        variant="outline"
        size="sm"
        className="h-7 text-xs cursor-pointer"
        onClick={() => setOpen(!open)}
      >
        {label} {selected.length > 0 ? `(${selected.length})` : ""}
      </Button>
      {open && (
        <div className="flex flex-wrap gap-1">
          {keys.map((key) => (
            <Badge
              key={key}
              variant={selected.includes(key) ? "default" : "outline"}
              className="text-xs cursor-pointer"
              onClick={() => toggle(key)}
            >
              {key}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

function ChildrenSection({
  recordId,
  children,
  onRefresh,
}: {
  recordId: string;
  children: RecordSummary[];
  onRefresh: () => void;
}) {
  const [condFilters, setCondFilters] = useState<ConditionFilter[]>([]);
  const [fieldsMap, setFieldsMap] = useState<
    Map<string, Record<string, unknown>>
  >(new Map());
  // 子レコードの全 condition_units / result_units を 1 つの map に集約。
  // scatter 軸ラベルで `key [unit]` を出すのに使う。同じ key で複数子が
  // 単位を持つ場合は最初の non-empty が勝つ (基本的に同じ template なので
  // 揃うはず)。
  const [unitsMap, setUnitsMap] = useState<Record<string, string>>({});
  const [conditionKeys, setConditionKeys] = useState<string[]>([]);
  const [resultKeys, setResultKeys] = useState<string[]>([]);
  const [dataLoaded, setDataLoaded] = useState(false);
  const [condCols, setCondCols] = useState<string[]>([]);
  const [resCols, setResCols] = useState<string[]>([]);

  // 子レコードの conditions + results を取得
  useEffect(() => {
    fetchChildrenConditions(recordId)
      .then((items) => {
        const map = new Map<string, Record<string, unknown>>();
        const units: Record<string, string> = {};
        const cKeys = new Set<string>();
        const rKeys = new Set<string>();
        for (const item of items) {
          // conditions と results をマージ
          map.set(item.id, { ...item.conditions, ...item.results });
          Object.keys(item.conditions).forEach((k) => cKeys.add(k));
          Object.keys(item.results).forEach((k) => rKeys.add(k));
          // units を集約 (最初の non-empty が勝つ)
          for (const [k, v] of Object.entries(item.condition_units || {})) {
            if (v && !units[k]) units[k] = v;
          }
          for (const [k, v] of Object.entries(item.result_units || {})) {
            if (v && !units[k]) units[k] = v;
          }
        }
        setFieldsMap(map);
        setUnitsMap(units);
        setConditionKeys(Array.from(cKeys).sort());
        setResultKeys(Array.from(rKeys).sort());
        setDataLoaded(true);
      })
      .catch(() => {});
  }, [recordId]);

  // 利用可能なキー (conditions + results)
  const availableKeys = [...conditionKeys, ...resultKeys];

  // フィルタ適用
  const filtered =
    condFilters.length === 0
      ? children
      : children.filter((rec) => {
          const fields = fieldsMap.get(rec.id);
          if (!fields) return false;
          return condFilters.every((f) => {
            const val = fields[f.key];
            if (val === undefined) return false;
            const numFilter = Number(f.value);
            if (!isNaN(numFilter) && typeof val === "number") {
              return val === numFilter;
            }
            return String(val) === f.value;
          });
        });

  return (
    <>
      {dataLoaded && fieldsMap.size > 0 && (
        <div className="md:col-span-2">
          <ConditionScatterChart
            records={filtered}
            conditionsMap={fieldsMap}
            unitsMap={unitsMap}
          />
        </div>
      )}

      <Card
        id="section-children"
        className="md:col-span-2 scroll-mt-20"
      >
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">
              サブレコード ({filtered.length}
              {condFilters.length > 0 ? ` / ${children.length}` : ""})
            </CardTitle>
            <BulkUploadButton
              recordId={recordId}
              childCount={children.length}
              onComplete={onRefresh}
            />
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {dataLoaded && (
            <ConditionFilterPanel
              filters={condFilters}
              onChange={setCondFilters}
            />
          )}
          {dataLoaded && (
            <ColumnPicker
              label="条件カラム"
              keys={conditionKeys}
              selected={condCols}
              onChange={setCondCols}
            />
          )}
          {dataLoaded && resultKeys.length > 0 && (
            <ColumnPicker
              label="結果カラム"
              keys={resultKeys}
              selected={resCols}
              onChange={setResCols}
            />
          )}
          <SortableRecordTable
            records={filtered}
            defaultSort="title"
            conditionsMap={fieldsMap}
            conditionColumns={[...condCols, ...resCols]}
            pageSize={100}
          />
        </CardContent>
      </Card>
    </>
  );
}
