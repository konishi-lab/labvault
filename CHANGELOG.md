# Changelog

本リポジトリの変更は [Keep a Changelog](https://keepachangelog.com/) 形式
で記録する。バージョン番号は [Semantic Versioning](https://semver.org/) に
従う (`MAJOR.MINOR.PATCH`、SDK API or backend API の破壊的変更は MAJOR)。

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
