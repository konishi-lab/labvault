# Backlog

「次に着手する候補」を優先度別に並べたキュー。完了したら `multitenant_next_steps.md` /
`design/v10/05_milestones.md` の該当エントリにも反映する。

最終更新: 2026-06-17

---

## 🔥 アクティブ

### 1. 人力 QA / 受入れテスト
**規模**: 環境ごとに半日 / **詳細**: [`docs/qa_checklist.md`](qa_checklist.md)

複数 OS × 複数 Python × 複数ブラウザの組合せで実機動作を確認する。
SDK / CLI / MCP / WebUI / 装置 PC ワークフローの主要シナリオを網羅。
release 前 (semver タグ前) または大きな PR マージ後に通す。

### 2. team admin による pending 承認 (2 段階フロー設計)
**規模**: 設計 30 分 + 実装 1〜2 時間

current: pending は super-admin だけが見える。
target: super-admin が「target team を指名」した時点で、その team の admin
にも pending queue が回ってきて承認できる。

申請段階で team list を申請者に晒さない (security) のが大前提。
設計が固まったら別 issue / PR に分割。

### 3. CSV ダウンロード + id 一覧コピー
**規模**: 純 frontend 2〜3h

`/records` の `SortableRecordTable` の上に「CSV ダウンロード」「id 一覧コピー」
ボタン。BOM 付き UTF-8 で Excel 文字化け回避。MVP は `id, title, created_at,
status` のみ。

**期待効果**: 「UI で絞り込んだ集合 → Notebook で `lab.get_many(ids)`」の
最短動線が確立。解析者の二重労力が消える。サーバ変更不要。

(UX レビュー Top5 #5)

### 4. 条件カードに「Copy as SDK」ボタン + template/parent への 1-click 横展開
**規模**: 1 日

- (a) 条件カードヘッダに **`Copy as SDK`** ボタンを追加し、
  `lab.new(template='xrd', conditions={...})` snippet を clipboard へ
- (b) ヘッダの status badge 横に **context chip** `[template: xrd]`
  `[parent: AB3F7K]` を追加、クリックで `/records?template=xrd` 等へ遷移

**期待効果**: 再現フローの 70% を解消、半年前 record の手打ち再入力が消え、
Notebook への橋渡しが完成。

(UX レビュー Top5 #4)

### 5. レコード詳細に sticky summary chip 行
**規模**: medium (backend completeness 計算込み)

ヘッダ直下に `[条件 8 / 結果 3 / ファイル 5 / メモ 1 / 子 12]` の chip 行を
追加。クリックで該当カードへ smooth scroll。**template required の充足率**
を併記 (例: `結果 3/5 必須`)、check-results CLI と整合させる。空カテゴリは
灰色 + 「未投入」ラベル。

**期待効果**: 装置 PC から戻った実験者の「5 秒で record 確認」が成立。
記録漏れの即時可視化。

(UX レビュー Top5 #3)

---

## 戦略案 (要設計、規模 large)

### 6. `/records` 一覧上で scatter + 数値サマリ
**規模**: 2〜3 週

検索 + condition フィルタで絞った任意集合 (子レコード前提から脱却) に対し、
scatter と数値サマリ (n / min / max / mean / median) を表示。解析者の
「Web UI で一次分析 → Notebook で深掘り」往復が完成。

**前提整備**:
1. limit=50 制約の解消 (Top5 #2 で部分対応済)
2. `RecordSummary` に indexed_fields の `results.*` / `conditions.*` を flatten
3. サーバ側集約 API `/api/records/aggregate` (50 件超を扱うため)
4. vector search ルートで conditions push-down

**警告**: 前提を整えずに載せると「表示中の 50 件だけプロット」の
**嘘グラフ製造装置** になる。段階導入必須。

(UX レビュー Strategic Bet A)

### 7. ダッシュボード活動 hub 化
**規模**: 3〜4 週

`/` を最近 5 件の薄い索引から、(a) 今週/今月のサマリ (新規件数 sparkline,
status 分布, contributor top 5), (b) activity feed, (c) record 0 件時の
「最初の record を作る」3 ステップカードに格上げ。

**前提整備**:
1. `/api/stats/weekly` エンドポイント (200 件 fetch のクライアント集計は破綻)
2. users コレクションの bulk fetch + cache (avatar 表示用)
3. team scoped での 0 件判定 (複数 team 所属対応)

**判断**: `/` を作り変えると既存 bookmark / Notebook URL が陳腐化。
`/dashboard` 新設で安全側に倒す案あり。PI UX 確認が先行。

(UX レビュー Strategic Bet B)

---

## 保留 (有用性を見極めてから着手)

### `Record.scan()` ヘルパー / `shared_conditions`
**規模**: 必要になってから判断

PR #66 で `sub(template=)` を入れて子の auto-fill は解決済み。
agent teams 議論で将来候補として残ったのが:

- `TemplateV10.shared_conditions: list[str]` — 親 template に書いておくと
  `inherit_conditions=True` 指定時に子に伝播する key のホワイトリスト
- `Record.scan(field, values, *, template=...)` — 1 軸 scan の糖衣
  (内部で `sub()` を for で yield)

**保留理由**: 現状 `**common` dict + for ループで十分書ける。実運用で
「同じ pattern を 100 回書いてる」と確信してから足す方が API 表面を
無駄に膨らませない。完全 additive なので後付け可能。

### 既存 record の retroactive template 紐付け
**規模**: 設計 30 分 + 実装 1 時間

2026-05-25 の `idx_*` backfill で発覚: konishi-lab team の 4863 record
のうち **4860 件が template 未紐付け** (MDG import の歴史的データなど)。
これらは PR #14 の push down 高速化、PR #20 の chip suggest、必須条件
チェック、alias 正規化、file_parsers 自動起動 — つまり M3 関連の便利
機能全部の蚊帳の外。

ルールベース (tag / 拡張子 / title) で template を推測 → dry-run で
人が確認 → 一括 set、というスクリプトで救出可能。

**保留理由**: template 機能 (M3) そのものが実運用でどれだけ使われるか
未知数。template を新規 record に積極的に当てる運用が定着した時点で、
過去 record にも遡及する意味が出てくる。先に template の有用性検証。

### corrupt `nextcloud_path` の Firestore 棚卸し / 一度きり migration
**規模**: スクリプト 1 時間 + dry-run / apply

#52 の strip で「`{base_path}/{group_folder}/...` 形式で 2 重保存された
`nextcloud_path`」は読み出し時に救済済み。run-time fix は idempotent &
副作用なしなので恒久運用しても問題は無いが、データ側を綺麗にしたい場合:

- Firestore を scan して該当 ref を抽出 → 何件あるか把握
- dry-run でストリップ後のパスをログ
- 確認後に `--apply` で書き戻し

**保留理由**: 救済は既に動いている。スキャンコストと取り扱いリスクが
読み出し時 strip のコストを上回るか不明。次に大規模な migration を
踏む機会 (別件) でついでにやるのが効率良さそう。

---

## 人間オペレータ案件

### README install を別 GCP アカウントで実機テスト
Claude では新規 Google account 作成 + admin 承認のフローが踏めない。
承認済 user の venv 経路は 2026-05-18/19 の smoke で確認済 (ADC モード /
PAT モードどちらも end-to-end 成功)。残りは **未承認 user の体験**
(pip install が 403 を踏むか / 承認後すぐ通るか) のみ。

---

## 中長期 (M5+)

### 8. `ProcessChain`
連鎖実験の親子 link をワンライナーで。

### 9. `nextcloud_poller`
Nextcloud の `_inbox/` を監視して自動 record 化。

### 10. 追加パーサー (低優先)
`.dm3` (TEM), `.dat` (MPMS/PPMS), `.wdf` (Raman), `bruker_raw_parser`
(.raw), `xy_parser` (.xy) など。`docs/design/v10/05_milestones.md` の
M5 セクション参照。XRD template には宣言済だが parser 本体は未実装で、
拡張子マッチ時に UserWarning でスキップされる現状を許容している。

---

## 参考: 直近マージ済

### 2026-06-17
| PR | 内容 |
|---|---|
| #67 | Web UI results card に「template 由来 / 手動入力」の視覚的区別 (#13b)。template 由来は斜体 slate-400、手動は従来の青/muted。hover tooltip で由来を表示。backend `RecordDetail` に `template_result_units` / `template_result_descriptions` を追加 + tests 4 件 |
| #68 | `/records` UX 強化: agent teams UX レビュー Day-one action + ユーザー要望「自分の record を優先表示」。query × conditions の併用解禁、「自分のみ」filter toggle、件数ヘッダ + has_more、自分の record 上部優先表示 + 薄い青ハイライト & 「自分」バッジ、limit 200 + クライアントページネーション。backend `/api/records` `/api/search` に `created_by` クエリ + `has_more`。InMemory backend に parent_id kwarg 統一。tests +8 件 |
| #69 | UX Quick wins 3 つまとめ (#16): scatter 軸ラベルに `[unit]` (例: `power [W]`)、inline 編集行に pencil icon を常時薄表示 + group-hover で濃く、`/records` フィルタを `router.push` 化で戻るボタン復活。backend `/children/conditions` に units 同梱、tests +2 件 |

### 2026-06-16
| PR | 内容 |
|---|---|
| #61 | `labvault check-results` CLI 追加 (read-only audit)。既存 record の v0.3.0 規約違反 (dict / 長 list / size 超過) をスキャン、--verbose / --csv 対応。`labvault.core.results_audit` モジュールに純粋関数として切り出し |
| #62 | Web UI ファイル list バッジに `DataRef.original_type` を反映。Figure / Array / Table / Dict / List / Text / Bytes のサブバッジ、hover で raw 値 tooltip。backend `FileInfo` schema 拡張 + テスト 3 件 |
| #63 | `ResultField` dataclass + `TemplateV10.result_fields` + bare scalar 代入時の unit/description auto-fill。XRD は 9 fields、SEM/SQUID/TEM/Raman は 3-4 fields ずつ整備。tests +14 件 |
| #64 | hotfix: `FileSection` の prop 型を `FileInfo[]` に統一 (#62 でインライン型が古いままで Deploy frontend の `next build` TS strict check が fail していた) |
| #65 | CI 強化: `ci.yml` に `frontend` job (Node 22 + `tsc --noEmit` + `next build`)。#62 → #64 の再発防止、frontend の TS / Next エラーを PR 時点で fail させる |
| #66 | #12b minimal: `Record.sub()` に `template=` kwarg 追加 (1 行)。親と子で独立した template が紐付き、子 / 孫世代でも #12a auto-fill が効く。完全 additive |

### 2026-06-15
| PR | 内容 |
|---|---|
| #54 | リモート MCP Phase 4: ローカル `labvault mcp` を「上級者向け 3 ケース (オフライン / 装置 PC dev / MCP ツール開発)」と位置付け直す docs 反映 |
| #55 | ファイル DL 防御強化: `downloadAuthed` に cachebust + CLAUDE.md にキャッシュの罠を追記 |
| #56 | AR repo cleanup ポリシー設計 docs |
| #57 | AR grant retry endpoint + admin UI button、backend test 6 件 |
| #58 | backend endpoint-level test 拡充 +14 件 (request_access / welcome_acknowledged / Business rules) |
| #59 | Record file API を役割別に分割: `add_file` / `add_bytes` / `add_object` / `put`。旧 `add` / `save` は alias 残置。tests +37 件 |
| #60 | results に flat-scalar 規約を hard error で強制。`DataRef.original_type` を auto-fill。tests +36 件 |
| **v0.3.0** | release |

### 2026-06-09 (リモート MCP + Nextcloud DL 不具合連鎖)
| PR | 内容 |
|---|---|
| #46 | リモート MCP Phase 1: Cloud Run に `/mcp` mount、PAT 認証 |
| #47-#48 | リモート MCP Phase 3 (Claude / multi-LLM 設定例) |
| #49 | CORS-safe exception handler |
| #50 | `NextcloudException` の status_code/reason を response body に |
| #51 | `NextcloudStorage._full_path` で rooted 形を prepend skip |
| #52 | doubled `nextcloud_path` の読み出し時 strip |
| #53 | 410 Gone のキャッシュ焼き付き対策: 502 統一 + Cache-Control: no-store |

### より古い履歴 (2026-05〜2026-06-01)
team-scoped admin (#2), README install 改訂 (#3), M3 template 基盤 (#6),
Welcome 動線 (#9), `idx_*` push down (#14), backend test 基盤 (#17),
条件 chip + indexed_fields suggest (#18, #20), admin authz tests (#19, #21),
AR backfill script (#22), v0.2.x リリース系 (#33-#43)。詳細は git log 参照。
