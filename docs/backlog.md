# Backlog

「次に着手する候補」を優先度別に並べたキュー。完了したら `multitenant_next_steps.md` /
`design/v10/05_milestones.md` の該当エントリにも反映する。

最終更新: 2026-06-23 (PR #78 反映 — C1 aggregate モジュール抽出完了)

---

## 🔥 戦略 (差別化に直結 — 7 月中に決断)

Roadmap レビューで明らかになった「差別化資産が宙に浮いている」問題。

### B1. CellLog (R13) の Web / MCP 露出 ✅ **済 (PR #77)**

Web 詳細に CellLog セクション + MCP `get_notebook_log` tool + SDK
`Record.cell_logs()` accessor + Backend `/api/records/{id}/cell_logs`
公開 endpoint + Pydantic schema を 1 PR で完備。比較資料の「LLM が
Notebook 履歴を辿る」がついに現実に。**ただし実利用評価は未**
(Notebook 経由の record 作成試験は本日以降 hirosuke が実機で実施)。
副次で InMemory backend の get_cell_logs が cell_number 昇順を返す
contract に揃った。

### B2. template 利用率の判断 (浸透 or M3 凍結)
**規模**: 1 日 + 1 ヶ月観察

konishi-lab 4863 record のうち **4860 件 (99.9%) が template 未紐付け**。
M3 の便利機能 (push-down / chip suggest / required check / auto-fill /
parser auto-trigger) は事実上空回り。判断手順:

1. 保留枠の「retroactive template 紐付け」を**人力でなく自分で 1 日で書く**
2. ルールベース (tag / 拡張子 / title) で推測 → dry-run 確認 → apply
3. Web UI で「未紐付け」バッジを出す (新規 record にも認知圧をかける)
4. 1 ヶ月運用して採用率が伸びるか観察

伸びなければ **M3 関連改善は全停止、追加 parser (#10) も deprecation**、
M5 の execute_code (R16) に予算移管。

---

## 🛠️ 構造的負債 (Phase B 前後で 1 つずつ)

backend レビュー独自の指摘。今すぐ落ちないが、本番安定性と開発速度に
直結。

### C1. `labvault.core.aggregate` モジュール抽出 ✅ **済 (PR #78)**

`is_numeric` / `merge_fields` / `compute_stats` / `compute_aggregate` /
`numeric_values_only` を 1 ファイルに集約。backend / MCP / CLI の 3 経路
を delegate に書き換えた。これで PR #74 の A2 のような「ガード仕様の
3 重実装ズレ」が構造的に再発しない。tests +19 (SDK 612→631)。

### C2. `Lab.list()` の API 拡張で `_metadata` 直アクセス撤廃
**規模**: 2 日

`records.py:171, 336, 466, 502` で `hasattr(lab._metadata, "list_records")`
分岐があり、Backend Protocol を逆参照している。`Lab.list(parent_id=...,
parent_id_unset=False, conditions=..., created_by=...)` を SDK 側に
昇格し、backend は `lab.list()` だけを使う形に。同時に `lab._team` →
`lab.team` プロパティ化 (30+ 箇所)。

### C3. observability (structured log) 投入
**規模**: 半日

`records.py` / `metadata.py` 全体で `logger` インスタンスが存在しない。
最低 `aggregate` / `bulk_upload` / `list_records` に Cloud Logging 互換
の JSON ログを入れる。slow query や push-down 失敗が完全ブラックボックス。

### C4. Firestore client lifecycle (broken pipe 対策)
**規模**: 半日

`get_lab` シングルトンが broken pipe で永続 500 になりうる
(Cloud Run 24h 連続稼働で発現)。FastAPI lifespan で client を再生成
できる経路を作る。

### C5. (Stretch) async backend ラッパ
**規模**: 1〜2 日

`platform/backend` は FastAPI なので本来 async が自然。`metadata.py:273`
の `storage_upload` 等で Nextcloud 障害時に uvicorn worker が全滅する
可能性。`run_in_threadpool` 経由のラッパを挟む短期解。Backend Protocol
に async 変種を追加する長期解は M5 以降。

---

## 💡 Phase B 前に潰したい UX (まとめて 1 PR)

UX レビュー独自の指摘。詳細ヘッダ整理 + ホーム 3 chip までを「Phase B
前作業」として 1 PR (4〜6h)。残りは Phase B 内で対応。

### D1. 詳細ヘッダのバッジ色数を 15 → 4 に削減
- status のみ色 (青 / 緑 / 赤 / 黄)
- `template:` / `parent:` は outline + 先頭アイコン (`📎` / `↑`) で
  「これはリンク」とだけ伝える
- `FileSection` の拡張子別 7 色 + `originLabel` 4 色は mono-tone + アイコンに

### D2. `SummaryChips` に異常値 chip を追加
**規模**: 1〜2 日 (backend Δ 計算が要る)

子 record の場合、親シリーズの median ± 2σ を超える `results.*` があれば
`⚠ pulse_energy +2.4σ` chip を生やす。「ちゃんと記録できたか」の本質は
「異常な値になっていないか」なので、件数 chip だけでは不十分。Phase B
で扱う `/api/records/fields` の前段として、子の `results` 統計を親 record
レスポンスに同梱する設計が要る。

### D3. 「自分のみ」+ 暗黙ソートの二重を解消
**規模**: 30 分

`/records` で「自分の record を上部にソート」が暗黙 ON だが、UI 操作子
無し。**「なぜ俺の record が上にあるんだ」を聞きに来るパターンが発生
している**。`bg-blue-50/40` + 「自分」バッジで識別は十分なので、暗黙
ソートは廃止 or 明示トグル化。

### D4. StatsPanel の初見ゼロ状態を埋める
**規模**: 1 時間

PI が初見で開くと localStorage 空で何も出ない。template フィルタ確定中
なら、その template の `required_results` を初期表示にして「Phase A が
動いている」ことを示す。

### D5. ホームを最小コストで dashboard 化 (#7 を縮小)
**規模**: 半日

`/` を full dashboard hub (#7, 3〜4 週) に作り変えると bookmark 破壊で
ROI 劣後。最小コスト版として 3 chip だけ追加:

- 「今週投入された record 件数」
- 「成功 / 失敗 ratio」
- 「team メンバー別投入件数」

`fetchRecords({limit:200})` で frontend 集計可能。Cloud 集計 endpoint は
Phase C と同時にまとめて作るのが効率良し。

---

## 🎯 戦略案 #6: `/records` scatter + 集計の段階導入

(Phase A は PR #73 で出荷済み)

検索 + condition フィルタで絞った任意集合 (子レコード前提から脱却) に
対し、scatter と数値サマリを表示。解析者の「Web UI で一次分析 →
Notebook で深掘り」往復が完成。

- **Phase A** ✅ **済 (PR #73)**: 数値サマリ panel + `/api/records/aggregate`
- **Phase B**: scatter chart を `/records` に。既存 `ConditionScatterChart`
  を流用、`/api/records/fields` 一括 fetch (上限 1000、超過は警告 + 抽出)。
  D1〜D5 の UX 修正と前後する
- **Phase C**: `RecordSummary.flat_fields` + Firestore push-down 強化で
  500 / 1000 件の上限を撤廃。indexed_fields の入った key は sub-second
- **Phase D**: aggregate に `keys: list[str]` で複数同時取得 + GROUP BY UI。
  Firestore N+1 解消

**残課題 (PR #73 review より)**:
- StatsPanel は default で 5 key 並列 fetch + フィルタ変更ごとに再走査。
  Firestore コストが見え始めたら Phase D を前倒し
- localStorage の保存 key は team 横断 — Phase B 前に team-prefix 化 (B1 と同 PR で済)

(UX レビュー Strategic Bet A)

### ⛔ #7. ダッシュボード活動 hub 化 → 凍結
**判断**: Roadmap レビュー提言に従い**今期は凍結**。代わりに D5 (3 chip
だけホームに足す) で最小コスト価値出し。full hub は 3〜4 週かかり、
bookmark / Notebook URL 破壊リスクを背負って ROI が劣後。Phase B 完了後に
PI から再要望が来たら判断。

(UX レビュー Strategic Bet B — 据え置き)

---

## 既存 アクティブ (規模 small)

### #2. team admin による pending 承認 (2 段階フロー設計)
**規模**: 設計 30 分 + 実装 1〜2 時間

current: pending は super-admin だけが見える。target: super-admin が
「target team を指名」した時点で、その team の admin にも pending queue が
回ってきて承認できる。申請段階で team list を申請者に晒さない (security)
のが大前提。設計が固まったら別 issue / PR に分割。

### #1. 人力 QA / 受入れテスト
**規模**: 環境ごとに半日 / **詳細**: [`docs/qa_checklist.md`](qa_checklist.md)

複数 OS × 複数 Python × 複数ブラウザの組合せで実機動作を確認。
release 前 (semver タグ前) または大きな PR マージ後に通す。直近で
PR #67〜#73 を続けて入れたので、Phase B 着手前に 1 回回しておきたい。

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

### 10. 追加パーサー
`.dm3` (TEM), `.dat` (MPMS/PPMS), `.wdf` (Raman), `bruker_raw_parser`
(.raw), `xy_parser` (.xy) など。

**B2 (template 文化判断) の結果次第**: template 利用率が伸びなければ
M3 関連改善とともに **deprecation 検討対象**。XRD template に宣言済だが
parser 本体は未実装、拡張子マッチ時に UserWarning でスキップされる
現状を許容している。

### 11. R16 `execute_code` (LLM コード実行)
M3 凍結判断 (B2) で予算移管対象。`run_analysis` の骨格はあるが sandbox 無し。
比較資料で重要差別化を謳う割に手付かず。

---

## 参考: 直近マージ済

### 2026-06-23
| PR | 内容 |
|---|---|
| #78 | 🛠 構造負債 C1: aggregate ロジックを `labvault.core.aggregate` に 1 本化。`is_numeric` / `merge_fields` / `compute_stats` / `compute_aggregate` / `numeric_values_only` の pure 関数群 + `StatsResult` / `AggregateResult` dataclass。backend / MCP / CLI の 3 経路を delegate に書き換え。公開シグネチャ完全互換、PR #74 A2 の bool ガード漏れのような「3 重実装ズレ」が構造的に再発しなくなる。tests +19 件 (SDK 612→631) |
| #77 | 🔥戦略 B1: CellLog (R13) を Web UI + MCP に露出。これまで backend に save/get の実装は揃っていたが消費経路が無く実質死蔵 (0 名利用) だった差別化資産が初めて利用可能に。SDK `Record.cell_logs()` accessor / Backend `GET /api/records/{id}/cell_logs` + `CellLogEntry` / `CellLogListResponse` Pydantic schema / Frontend `CellLogSection` (折り畳み + 変数 diff バッジ + 上限 200 件 amber 警告) / MCP `get_notebook_log` tool。副次で InMemory backend の get_cell_logs が cell_number 昇順を返す contract に揃った (Firestore との不整合解消)。tests +9 件 (SDK 609→612, backend 111→117) |

### 2026-06-22
| PR | 内容 |
|---|---|
| #74 | 🚨 緊急 trio: (A1) `firestore.indexes.json` に `created_by` 複合 index 2 件追加 (PR #68 由来の本番 500 を解消、`firebase deploy --only firestore:indexes` 待ち)。(A2) MCP / CLI の aggregate / get_overview に `bool` 除外を 4 箇所追加 (`True/False` が 1.0/0.0 として mean に混入するバグ)。(A3) `@app.exception_handler(HTTPException)` を新設して全 4xx/5xx HTTPException に `Cache-Control: no-store` を強制付与 (30+ 箇所の個別 fix を一掃、#53 教訓の構造的解決)。tests +7 件 (SDK 605→609, backend 108→111) |
| #73 | 戦略案 #6 Phase A: `/records` ページに数値サマリ panel + backend `/api/records/aggregate` 新設 (current filter 集合の n / mean / std / min / max / median、走査上限 500、超過時 truncated フラグ + 「⚠ 500 件サンプル」amber バッジ + stats 灰色化で標本値と明示)。`StatsBlock` / `AggregateResponse` schema、key 入力 localStorage 永続化 + indexed_fields suggest chip、results-key も 1st-class 集計対象 (`merged = {**cond, **res}`)、`/{record_id}` ルーティング順 regression test。tests +10 件 |
| #72 | UX Top5 #3: レコード詳細にヘッダ直下 sticky summary chip 行 `[条件 X / 結果 Y / ファイル A / メモ B / 子 C]`。chip クリックで該当カードへ smooth scroll、template 紐付きは required の充足率 (`結果 3/9 必須`) を併記、未投入カテゴリは灰色 + 「未投入」、未充足は ⚠ + 黄色。backend `RecordDetail` に `template_required_{conditions,results}` 追加。tests +4 件。同 PR で numpy 2.5 stub の PEP 695 `type` 文に対応するため mypy `python_version` を 3.12 に bump |

### 2026-06-17
| PR | 内容 |
|---|---|
| #67 | Web UI results card に「template 由来 / 手動入力」の視覚的区別 (#13b)。template 由来は斜体 slate-400、手動は従来の青/muted。hover tooltip で由来を表示。backend `RecordDetail` に `template_result_units` / `template_result_descriptions` を追加 + tests 4 件 |
| #68 | `/records` UX 強化: agent teams UX レビュー Day-one action + ユーザー要望「自分の record を優先表示」。query × conditions の併用解禁、「自分のみ」filter toggle、件数ヘッダ + has_more、自分の record 上部優先表示 + 薄い青ハイライト & 「自分」バッジ、limit 200 + クライアントページネーション。backend `/api/records` `/api/search` に `created_by` クエリ + `has_more`。InMemory backend に parent_id kwarg 統一。tests +8 件 |
| #69 | UX Quick wins 3 つまとめ (#16): scatter 軸ラベルに `[unit]` (例: `power [W]`)、inline 編集行に pencil icon を常時薄表示 + group-hover で濃く、`/records` フィルタを `router.push` 化で戻るボタン復活。backend `/children/conditions` に units 同梱、tests +2 件 |
| #70 | UX Top5 #5: CSV ダウンロード + ID 一覧コピー toolbar を `SortableRecordTable` に追加 (`/records` 一覧と record 詳細の子レコード表両方)。BOM 付き UTF-8 で Excel 文字化け回避、quote-always escape、ID 改行区切りで Notebook の `lab.get_many([...])` に直貼り可能。`src/lib/csv.ts` 新規 |
| #71 | UX Top5 #4: 再現フロー 70% 解消。**Copy as SDK** ボタン (条件カードヘッダ、`lab.new(...)` snippet を clipboard へ、Python リテラル escape 込み)、**context chip** `[template: XRD]` `[parent: AB3F]` (レコード詳細ヘッダ、クリックで `/records?template=XRD` or 親詳細へ)、`/records?template=XXX` フィルタ + 解除 chip。backend `RecordSummary.template_name` + `template` クエリ。tests +6 件 |

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
