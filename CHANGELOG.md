# Changelog

本リポジトリの変更は [Keep a Changelog](https://keepachangelog.com/) 形式
で記録する。バージョン番号は [Semantic Versioning](https://semver.org/) に
従う (`MAJOR.MINOR.PATCH`、SDK API or backend API の破壊的変更は MAJOR)。

## [Unreleased]

### Added

- **Web UI: 検索 query と condition filter の併用解禁** + **「自分のみ」filter
  chip** + **件数ヘッダ** + **自分の record を先頭に優先表示** —
  agent teams UX レビュー (Day-one action) と「自分のものを優先的に出したい」
  ユーザー要望の合流。
  - `/api/search` と `/api/records` に **`created_by` クエリ** を追加。同時に
    `RecordListResponse.has_more` を追加し、limit 切り捨て時に warning 表記。
  - frontend `/records` の load 経路を統合: query / conditions / created_by
    を **同時** に渡せる (これまで query があると conditions が無視されていた)
  - **「自分のみ」toggle**: ヘッダの button、URL `?mine=1` に同期。ON で
    `created_by=自分のemail` filter
  - **件数ヘッダ**: `N 件表示中` / `N+ 件以上ヒット (条件を絞り込んでください)`
  - **自分の record 優先表示**: mineOnly OFF + sort なし時、自分の作った record
    を上部に持ち上げ、テーブル row には薄い青ハイライト + `自分` バッジ
  - **クライアントページネーション**: limit 200 + pageSize 50 で
    SortableRecordTable がページ送り
- **`InMemoryMetadataBackend.list_records` に `parent_id` kwarg** を追加し、
  Firestore backend と signature を統一 (test 用に backend 経由で
  `/api/records` を叩けるように)。
- 上記のための backend test 8 件 (`test_records_filters.py`)。

- **Web UI: results card に「template 由来 / 手動入力」の視覚的区別** —
  `add_object` の auto-fill (PR #63) で template から unit/description が
  補完された値は **斜体の灰色 (slate-400 italic)** で表示、手動で入力した値は
  従来通り **青字 / 通常 muted** で表示。hover で「template から自動補完」
  または「手動で入力された」と tooltip が出る。
- **Backend `RecordDetail` に `template_result_units` /
  `template_result_descriptions`** を追加。record に紐付いた template の
  `result_fields` から取得 (template 無しの record では空 dict)。frontend が
  比較で provenance を判定する基盤。backend test 4 件追加。

## [0.4.0] - 2026-06-16

### Added

- **`labvault check-results` CLI コマンド** — 既存 record の results に
  v0.3.0 規約違反 (dict / 32 要素超 list / 100 KB 超の値 / 合計 500 KB 超)
  が無いかをスキャンする read-only コマンド。違反種別ごとの集計、
  `--verbose` で詳細、`--csv` でエクスポート可能。新規書き込みは
  `__setitem__` で hard error になるが、規約以前に書き込まれた既存
  データの棚卸し用。
- **`labvault.core.results_audit`** モジュール — `scan_record(dict)` と
  `summarize(list)` の純粋関数。CLI から呼ばれるロジックを切り出し、
  他スクリプトからも利用可能に。`_ResultsProxy` と上限値を import で同期。
- **Web UI: ファイルバッジに `original_type` を反映** — `add_object` 経由で
  保存されたファイルに「Figure」「Array」「Table」「Dict」「List」「Text」
  「Bytes」のサブバッジを表示。`add_file` / `add_bytes` 経由 (raw 取り込み)
  および旧 record (`original_type=None`) はバッジ無し、拡張子バッジは従来通り。
  hover で raw 値 (`ndarray` / `figure` / etc.) が tooltip に表示される。
- **Backend `FileInfo` schema に `original_type: str \| None`** を追加し
  `/api/records/{id}` と `/api/records/{id}/files` のレスポンスに含める
  (テスト 3 件追加)。
- **`ResultField` dataclass** — `ConditionField` と対称な template フィールド
  定義 (name / display_name / type / unit / description / required / aliases)。
  `TemplateV10.result_fields: list[ResultField]` で持つ。
- **template-driven 自動 unit / description 補完** — record が template に
  紐付いていて、bare scalar で `rec.results[key] = value` を代入した時、
  template の `result_fields` から unit / description を自動で補完する。
  ユーザーが tuple 記法 `(値, "単位", "説明")` で明示した値、および既存の
  unit / description は上書きしない。これにより script 実験で「**値だけ
  書けば検索 / 散布図 / Web UI / LLM 解析が全部効く**」状態になる。
- **builtin templates の `result_fields` 整備** — XRD は 9 fields (代表
  ピーク 2θ / 格子定数 / 相 / fit χ² など)、SEM / SQUID / TEM / Raman は
  代表 2-4 fields を unit + description 付きで定義。
- **テスト 14 件追加**: auto-fill / tuple override / 既存値保護 /
  template 無し / 不明 key / round trip / builtin の result_fields 有無。

### Backward compatibility

- 旧 `recommended_results: list[str]` フィールドは **互換 alias として残置**
  (XRD template は `result_fields` と `recommended_results` を両方持つ)。
  Web UI の suggest 機能は引き続き動く。

### Added (#12b minimal)

- **`Record.sub(template=...)`** — 子レコード作成時に template を紐付ける
  kwarg を追加。これまで `parent.sub(...)` は template を子に渡せず、子の
  results 代入で #12a の auto-fill (unit / description) が効かなかった。
  本変更で子も独立に template を持てるようになり、scan 実験 / 多測定実験 /
  孫世代まで auto-fill が全世代で効く。完全 additive (1 行追加)。
  - 親と子で **異なる template** を独立に使える (continuation NOT inherited)
  - 共通 conditions は Python の `**common` イディオムで渡す (デフォルト挙動
    として「親の conditions を子に自動継承」はしない — 明示性優先)
  - 孫世代以上もそのままネスト可能 (各世代で template を独立指定)
- テスト 9 件追加 (`tests/unit/test_sub_template.py`)。

## [0.3.0] - 2026-06-15

### Added

- **`Record.add_file()` / `add_bytes()` / `add_object()` / `put()`** —
  ファイル保存 API を役割別に分割。これまで `add` / `save` の 2 メソッドが
  汎用語のため「どれを使うのか」「どちらが先に name を取るのか」が分かり
  にくいというフィードバックへの対応:
  - `add_file(path, *, name=None)` — 既存ファイル (装置生バイナリ・ディスク
    上のファイル)
  - `add_bytes(name, data)` — 生バイト列 (HTTP レスポンス・バッファ)
  - `add_object(name, obj)` — Python オブジェクトの自動変換 (Figure→PNG,
    DataFrame→CSV, dict→JSON, etc.)
  - `put(target, *, name=None)` — 型を見て上 3 つに dispatch する統一エント
    リ。動的に型が変わるループや書き分けが面倒な時の便利関数 (`str`/`Path`
    は常に path 扱い、`bytes` 系は `add_bytes`、その他は `add_object`)
- 内部実装は `_store_bytes(name, data, content_type)` の単一合流点にリ
  ファクタ。冪等性 (同一 name + 同一 SHA256 でスキップ) と
  `auto_extract_conditions` (template の file_parsers) は全 add_* 経路で
  維持。
- `tests/unit/test_record_file_api.py` 新規 37 ケース。
- **`DataRef.original_type`** — `add_object` 経由で保存された時の
  Python 型を semantic タグとして記録 (`"ndarray"` / `"figure"` /
  `"dataframe"` / `"dict"` / `"list"` / `"str"` / `"bytes"`)。
  `add_file` / `add_bytes` 経由 (raw 取り込み) は `None`。Web UI /
  MCP / LLM 解析が「`.npy` だが本当に ndarray か」「`.png` だが Figure
  由来か装置出力か」を拡張子推測ではなくメタデータから確実に判別可能に。

### Changed (BREAKING for new writes)

- **`Record.results[k] = v`** に flat 規約を強制 (LLM 解析品質と検索 /
  散布図の一貫性のため)。違反は `ValidationError` で即時拒否、`__setitem__`
  状態は rollback。**既存 record の読み込みは無傷** (`_load` 経路は
  バイパス) — 新規書き込みのみ規約に従う:
  - **dict は禁止** — 構造体は `record.add_object("fit.json", fit)` で
    ファイル化。単位混在の係数群は flat 展開 (`fit_a`, `fit_b`,
    `fit_chi2`) してください。
  - **list は 32 要素以下** — 大配列は
    `record.add_object("spectrum.npy", arr)` でファイル化し、results
    には代表値 (peak / mean / rms など) だけ scalar で残す。
  - **1 値 100 KB / results 合計 500 KB 以下** — Firestore 1 MB 上限の
    安全圏。
  - エラーメッセージは行動を誘導する内容 (どこに何を入れるか、
    `add_object` の例示) を含む。

### Deprecated

- `Record.add()` / `Record.save()` を **「将来の minor で
  `DeprecationWarning` を入れる予定」の互換 alias** に位置付け直し
  (今回は警告を出さない、既存コードは無変更で動作)。alias の削除は
  v2.0 でも行わない方針 (装置 PC の長期運用 script を保護)。

### Fixed

- `add_dir()` 内部で旧 `add()` を呼んでいた箇所を新 `add_file()` に置換
  (挙動は不変)。
- `docs/design/REQUIREMENTS.md` / `docs/design/v10/04_sdk_cookbook.md` の
  `add_ref(size_gb=...)` を実装に合わせて `size_bytes=...` に修正。

## [0.2.3] - 2026-06-03

### Added

- **`results[]` の単位記法 (conditions と対称)**:
  `record.results["peak"] = (0.97, "V")` / `(0.97, "V", "ピーク電圧")`
  の tuple 記法を受け付けるよう `_ResultsProxy.__setitem__` を拡張。
  既存のスカラー代入 (`results["lattice_a"] = 2.873`) は引き続き動く
  ので後方互換。
- **`Record.get_result_descriptions()`** と内部 `_result_descriptions`
  辞書を追加 (conditions 側と並列の構造に)。`to_dict` / `from_dict`
  で永続化。
- **Backend `PATCH /api/records/{id}/result_units`**: condition 側の
  `/units` と対称な新エンドポイント。`_result_units` /
  `_result_descriptions` を更新する。
- **Web UI 結果カードの単位編集**: ResultsCard を ConditionsCard と
  同じ「row クリック → 単位 + 説明を編集」インラインフォームに揃え
  た。`[unit]` 青字 chip と `— 説明` の表示は両カード同形。

### Docs

- **`docs/onboarding.md`**: 4.3 単位の扱いを書き直し、conditions /
  results 両対応の tuple 記法をメインに案内。results に何を入れて
  良いか (スカラー + 小リスト) / 入れない方が良いか (画像・大配列は
  ファイル添付に) のガイドも追加。

### Notes

破壊的変更なし。0.2.2 からのアップグレードは `pip install -U` で OK。
Frontend / Backend は同タイミングのデプロイで `result_descriptions`
フィールドを認識する (古い frontend に新 backend を返しても余剰
フィールドは Pydantic で無視される)。

## [0.2.2] - 2026-06-03

### Changed

- **`Settings` に konishi-lab 本番運用の default を組み込み**:
  `gcp_project="klab-laser-process"` /
  `firestore_database="labvault"` /
  `nextcloud_url="https://arim.mdx.jp/nextcloud"` /
  `nextcloud_group_folder="large/24UTARIM004"` /
  `platform_url="https://labvault-api-355809880738.asia-northeast1.run.app"`
  を `src/labvault/core/config.py` の field default に持たせた。
  これにより `.env` は最小で `LABVAULT_TEAM=konishi-lab` +
  `LABVAULT_USER=...` の 2 行で動く。他研究室で使う場合 / 別 GCP
  project に向けたい場合は env で明示的に上書きする。
- **`labvault doctor` 表示**: PAT モード時の「GCP project: not set
  (PAT モードでは未使用)」は、default が入っていることで
  「GCP project: klab-laser-process (PAT モードでは未使用)」になる。
  値が見えても PAT モードでは使われないことが注釈で伝わる。

### Docs

- **README §2.2 / §セットアップ §2 / `docs/onboarding.md` §3-A /
  `docs/qa_checklist.md` §1.3**: ADC 用 `.env` の例を 2 行 (team /
  user) に短縮。残りは default で動くことを補足コメントで案内。

### Notes

破壊的変更なし (default 値は従来 `.env` に書いていたものと同一)。
本リポジトリで開発する限り、SDK のアップデート (`pip install -U`)
だけで OK。

## [0.2.1] - 2026-06-03

### Changed

- **`labvault auth set-token` の `--user` default** (PR #38): `--verify`
  で取れた PAT 発行者 email を `LABVAULT_USER` の default に自動採用
  する。装置 PC のように複数人で 1 つの credentials を共有する場合は
  `--user instrument-xrd-1` のように明示する運用を強く推奨 (stdout
  と docs で警告を出す)。
- **`labvault doctor` の PAT モード注釈** (PR #38): PAT モード時、
  GCP project / Nextcloud direct URL の行末に `(PAT モードでは未使用)`
  を付加し、「未設定でも正常」を視覚的に伝える。
- **`labvault doctor` の「次のステップ」hints** (PR #38): 0.2.0 で
  入りそびれていた hints セクションを改めて入れる。認証ゼロ → ADC
  推奨 + PAT 代替、Mixed → ADC に寄せる警告、team / user / nextcloud
  個別ヒント。

### Added — Web UI

- **トークン画面の使い方サンプル** (PR #36):
  - 発行成功カードに `labvault auth set-token` のコマンドを 1 番目に
    追加 (pip install / credentials は補足扱い)。
  - 「有効なトークン」リストの行をクリックすると accordion 展開し、
    使い方サンプルが表示される (raw token は再表示不可なので
    `<YOUR_TOKEN>` プレースホルダ + 「失くしたら再発行」案内)。

### Docs

- **`docs/onboarding.md`** (PR #37): 新規メンバー向けの 30 分セット
  アップガイド。Web UI 承認 → SDK install (ADC / PAT) → Notebook で
  親 + 子レコード作成 → Web UI で確認 → 詰まったら、までを 1 ファイル
  に集約。
- **README §3.3 / `docs/instrument_pc_setup.md` §3**: 「装置 PC では
  `--user` 明示」の注意ブロックを追加。

### Notes

破壊的変更なし。0.2.0 からのアップグレードは `pip install -U` で OK。
\`labvault auth set-token\` を `--user` 省略で叩いた挙動だけが変わる
(これまで書かれなかったが、これからは PAT 発行者 email が default で
書かれる)。

## [0.2.0] - 2026-06-03

### Added — オンボーディング動線

- **`labvault auth set-token` / `labvault auth status` CLI** (PR #33):
  Personal Access Token を `~/.labvault/credentials` に 1 行で書き込み、
  backend で検証 + パーミッション設定 (Unix `chmod 600` / Windows
  `icacls`) まで自動で行う。
- **PyPI proxy** (PR #31): platform backend に PEP 503 互換の
  `/api/pypi/simple/` を追加。装置 PC / CI で gcloud を持たずに
  `pip install --extra-index-url https://__token__:lv_xxx@.../api/pypi/simple/`
  で labvault SDK を install できる。
- **`labvault doctor` の「次のステップ」**: 設定状態に応じて何をすべきかを
  case 別に案内する。ADC 推奨を default とし、PAT + GCP project の両方
  がある (Mixed) 構成では「ADC のみに寄せる」推奨を出す。
- **`labvault doctor` の凡例表示** (PR #26): 末尾に
  `[OK] / [--] / [!!]` の意味を 1 行で表示。
- **Welcome 画面の PAT セットアップ手順**: 「トークン発行 → pip install →
  credentials」の 3 ステップを具体例付きでカード表示。
- **`/account/tokens` の発行直後カード**: 発行された token を埋め込んだ
  完成形コマンド (Mac/Linux pip / Windows pip / `~/.labvault/credentials`)
  をその場で表示、コピペで即動く。

### Added — Web UI

- **条件 chip での絞り込み** (PR #18 / #20): `/records` で
  `?conditions={"target":"Cu"}` のように URL 同期。`indexed_fields` の
  候補を datalist で suggest し、push down が効く key を視覚的に区別。
- **レコード詳細の空 state 表示** (PR #28): 条件・結果・ファイル・子
  レコードが全て空のときに案内カードを出す。
- **共通 `BackButton` で `← 戻る` を `router.back()` に統一** (PR #28):
  Dashboard 動線が崩れないようにする。
- **frontend dev_skip 機構** (PR #27): `NEXT_PUBLIC_DEV_SKIP_AUTH=1` で
  Firebase 認証をバイパス。ローカル開発と E2E テストの敷居を下げる。

### Added — SDK / バックエンド

- **template の `file_parsers` 経由で `Record.add()` 自動 parse** (PR #13,
  M3 part 2): Rigaku `.ras` を投入するだけで `target` / `wavelength_A` /
  `two_theta_*` / `scan_speed_*` / `sample_name` が conditions に自動
  充填される。手動入力は parser 値で上書きしない。
- **Firestore push down** (PR #14): `Lab.search` / `Lab.list` の
  conditions のうち `template.indexed_fields` に挙がっている key を
  `idx_<key>` として Firestore に push down する。
  `firestore.indexes.json` で複合 index 8 個を宣言、gcloud apply
  スクリプトも同梱。
- **`scripts/idx_backfill.py`** (PR #15): 既存 record に
  `idx_<key>` を補完するスクリプト (dry-run / `--apply`)。
- **`scripts/ar_backfill.py`** (PR #22): Artifact Registry reader 漏れ
  検出 + 一括 grant (gcloud subprocess 経由)。
- **`Lab._template_cache` / `_indexed_keys_cache`**: Record 永続化時の
  template lookup と indexed_keys 計算のキャッシュ。
- **`auth_me` の dev_skip ガード** (PR #26): `LABVAULT_DEV_SKIP_AUTH=1`
  で Firestore を引かずに固定の admin / konishi-lab を返す。

### Added — テスト基盤

- **`platform/backend/tests/`** (PR #17 / #19 / #21 / #24): TestClient
  ベースの認可境界テスト基盤。super-admin / team-admin / member /
  unauth の 4 役 fixture + 最小 FakeDB で `/api/admin/*` をカバー (45+
  ケース)。`/api/auth/request-access` / `welcome-acknowledged` と
  「自己 deactivate 不可」「最後の super-admin / team 削除不可」などの
  整合性ルールも含む。

### Changed

- **インストール手順を ADC 推奨に再構成** (PR #34): README §2 を
  ADC 方式、§3 を PAT 方式 (装置 PC / CI 等の代替) に位置付け直し。
  `docs/qa_checklist.md` §1 も同構造に揃え。
- **POST `/api/auth/tokens` に dev_skip ガード** (PR #28): ローカル
  開発で気軽に押した「発行」ボタンが本番 Firestore に `dev@local`
  名義の token を残す事故を防止 (`LABVAULT_DEV_SKIP_AUTH=1` で 403)。
- **`labvault doctor` 出力整理** (PR #8): `__version__` を pkg metadata
  から取得、`config.toml` 不在は `[--]` 扱い、`PAT` / `platform URL` /
  `mode` (PAT / Mixed / Direct) 行を追加。
- **template `indexed_fields` を top-level `idx_*` に昇格** (PR #11):
  Firestore で where filter に使えるようにする (PR #14 の前段)。
- **MetadataBackend interface 拡張**: `list_records` に
  `conditions` 引数を追加 (memory / firestore / platform 全実装)。
- **`platform/backend/CLAUDE.md`** にローカル開発の env table と
  「CORS error の真因が 500 のことがある」「dev_skip と Firestore」の
  落とし穴を追記 (PR #26)。

### Fixed

- **SearchBar の遷移先を `/records?q=` に固定** (PR #28): これまで
  `/?q=` (Dashboard) に飛んで検索結果が出なかった。
- **条件値の単位二重表示を解消** (PR #28): `two_theta_start_deg [deg]:
  10 deg` のように label と値の両方に単位が出ていた。
- **Token 発行のラベル必須化** (PR #28): 空文字で「(無題)」が量産される
  問題を防ぐ。
- **Records 一覧のタイトル truncate + 年付き日付** (PR #28): 長文
  タイトルで横スクロールが必要、日付に年がないため数年前のレコードが
  判別不能な問題を解消。

### Docs

- **`docs/qa_checklist.md`**: 人力 QA / 受入れテスト用 10 章の
  チェックリスト (PR #23) + round 後の所見トラッカー / 起動セット
  アップ手順を追加 (PR #29)。
- **`docs/qa_findings_*.md`**: round-1 / round-2 の自動 QA 所見と
  修正状況を記録 (PR #25 / #27)。
- **`docs/firestore_indexes.md`**: 複合 index の apply 手順
  (firebase deploy / gcloud) と `--only firestore` の使い方の罠を解説。

### Notes

破壊的変更なし。0.1.2 からのアップグレードは `pip install -U` で OK。

## [0.1.2] - 2026-05-12

最初のリリース系列。SDK Core / Backend / CLI / MCP / Web UI の基本
機能 + M3 テンプレート基盤 + 多テナント認証 + PAT モード。詳細は
git log を参照。
