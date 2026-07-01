# labvault 実装仕様書

**対象**: 2026-07-02 時点で main に入っている実装の網羅仕様。

**役割**:
- `docs/design/v10/*` は「これから作る」の設計思想を記録した予定図。
- 本文書は「今動いている」実装の実態を記録した現況図。
- 差分は「予定 → 現況」の乖離を意味する。

**構成**:

1. [システム概要](#1-システム概要)
2. [データモデル](#2-データモデル)
3. [認可モデル](#3-認可モデル)
4. [SDK API](#4-sdk-api)
5. [Web API](#5-web-api)
6. [MCP tools](#6-mcp-tools)
7. [CLI](#7-cli)
8. [Firestore 複合 index](#8-firestore-複合-index)
9. [運用](#9-運用)

---

## 1. システム概要

### 1.1 目的

Python / Jupyter Notebook で実験する研究室のための実験データ基盤。
Notebook セル・装置制御スクリプトから記録された条件・結果・ファイル・
コード履歴を Firestore + Nextcloud に自動蓄積し、Claude / Gemini など
MCP 対応の LLM から自然言語で横断検索・解析できるようにする。

### 1.2 構成要素

```
┌────────────┐   ┌──────────────┐   ┌───────────────────┐
│ Notebook   │──▶│ labvault SDK │──▶│ Firestore         │ メタデータ
│ 装置 PC    │   │ (Python)     │   │ (klab-laser-      │ (record / template /
└────────────┘   └──────┬───────┘   │  process/labvault)│  cell_log /
                        │           └───────────────────┘  share_events)
                        │
                        │           ┌───────────────────┐
                        ├──────────▶│ Nextcloud         │ ファイル
                        │           │ (ARIM MDX)        │ (.npz / .png /
                        │           └───────────────────┘  .vk4 / .plux 等)
                        │
                        │           ┌───────────────────┐
                        └──────────▶│ Vertex AI         │ 意味検索用
                                    │ text-embedding-004│ ベクトル
                                    └───────────────────┘

┌────────────┐   ┌──────────────┐   ┌──────────────┐
│ Claude     │──▶│ labvault MCP │──▶│ labvault SDK │  ローカル MCP
│ Gemini     │   │ (stdio)      │   │              │  (labvault mcp)
└────────────┘   └──────────────┘   └──────────────┘

┌────────────┐   ┌────────────────┐   ┌──────────────┐
│ ブラウザ   │──▶│ Next.js Web UI │──▶│ FastAPI      │──▶ SDK
│ 実験者     │   │ (labvault-web) │   │(labvault-api)│
└────────────┘   └────────────────┘   └──────────────┘
       Cloud Run (asia-northeast1)
```

### 1.3 開発規約

- **Backend Protocol は全 sync** — Notebook event loop 競合回避のため async は使わない。
- **依存軽量化** — `google-cloud-aiplatform` は使わず Vertex AI REST を直叩き。
  `mcp` パッケージはオプショナル依存で lazy import。
- **ローカルバッファ** — `_persist()` はメタデータバックエンド + SQLite バッファの
  両方に書き、データ消失を防ぐ。
- **バックエンド自動選択** — `.env` / `~/.labvault/config.toml` に GCP 設定があれば
  Firestore / Nextcloud を自動使用、無ければ InMemory。
- **例外命名** — Python builtin `PermissionError` と衝突しないよう
  `LabvaultPermissionError`。
- **テスト** — InMemoryBackend で全 unit test がオフラインで動くこと。実サーバー
  疎通は `pytest -m integration` で明示。

---

## 2. データモデル

### 2.1 コレクション階層 (Firestore)

```
teams/{team_id}                         # チーム定義
  ├── nextcloud_group_folder: str       # ファイル置き場のルート
  ├── name: str
  ├── created_at: timestamp
  └── created_by: str

  records/{record_id}                   # 実験レコード (詳細は §2.2)
    └── cell_logs/{cell_id}             # Notebook セル実行ログ

  templates/{name}                      # 装置テンプレート

  share_events/{auto_id}                # 共有 event 監査ログ (2026-07-01)

allowed_users/{email}                   # 承認済ユーザー
  ├── active: bool
  ├── role: "admin" | "member"          # legacy global (super_admin 判定)
  ├── teams: [{team_id, role}]          # 所属 team と team 内 role
  ├── default_team: str
  ├── display_name: str
  ├── created_at: timestamp
  └── ar_granted: bool | null           # Artifact Registry reader 付与状態

pending_users/{email}                   # 承認待ちの signup 申請
  ├── requested_at: timestamp
  └── display_name: str

pats/{token_id}                         # Personal Access Token
  ├── owner_email: str
  ├── token_hash: str (SHA-256 hex)
  ├── created_at: timestamp
  └── revoked_at: timestamp | null

shared_links/{token_hash}               # 外部共有トークン (ls_*)
  ├── record_id: str
  ├── team: str
  ├── role: "viewer" | "analyst"
  ├── pseudo_email: str
  ├── expires_at: timestamp | null
  ├── revoked_at: timestamp | null
  └── ...
```

### 2.2 Record ドキュメント

`teams/{team}/records/{record_id}` の全 field。`Record._to_dict()` 実測。

| field | 型 | 説明 |
|---|---|---|
| `id` | str | Crockford's Base32 6 文字 (既存 4 文字 ID との後方互換あり) |
| `team` | str | 所属 team_id |
| `title` | str | 表示名 |
| `type` | str | `experiment` \| `sample` \| `process` \| `measurement` \| `computation` \| `analysis` (フリーテキストも可) |
| `status` | str | `running` \| `success` \| `failed` \| `partial` |
| `created_by` | str | 作成者 email or SDK 経路の user 識別子 |
| `created_at` | ISO datetime | UTC |
| `updated_by` | str | 直近の書き込み主体 |
| `updated_at` | ISO datetime | UTC |
| `tags` | list[str] | 自由タグ |
| `notes` | list[Note] | `{text, created_at, author}` |
| `links` | list[Link] | `{target_id, relation, description}` — 他 record への参照 |
| `data_refs` | list[DataRef] | Nextcloud 上のファイル。§2.3 |
| `external_refs` | list[ExternalRef] | 外部 URI 参照 `{uri, location, size_bytes, description, doi}` |
| `conditions` | dict | 実験条件 `{key: scalar}` |
| `condition_units` | dict | `{key: "unit_str"}` |
| `condition_descriptions` | dict | `{key: "説明"}` |
| `results` | dict | 実験結果。§2.5 |
| `result_units` | dict | 同上 |
| `result_descriptions` | dict | 同上 |
| `events` | list[dict] | `exp.log_value()` / `exp.log_event()` で追記される event。`{type, key, value, timestamp}` or `{type, description, timestamp}` |
| `deleted_at` | ISO datetime \| null | ソフト削除。`null` = 生存 |
| `parent_id` | str \| null | 親 record ID (子孫 tree 用) |
| `template` | str \| null | 紐付いた template 名 |
| `shares` | dict | `{email: "viewer" \| "analyst"}` |
| `shared_with_emails` | list[str] | `shares` の key を派生 (Firestore の `array-contains` 用 index) |
| `created_audit_source` | str \| null | 認証経路 `"firebase"` \| `"share-link"` \| `null` (SDK 直接) |
| `updated_audit_source` | str \| null | 同上 |
| `idx_<key>` | scalar | template の `indexed_fields` を top-level に昇格したコピー (Firestore where 用) |

### 2.3 DataRef

`src/labvault/core/types.py:54`

```python
@dataclass
class DataRef:
    name: str                    # 表示名 (通常はファイル名)
    nextcloud_path: str          # {group_folder}/labvault/{team}/{record}/{name}
    content_type: str            # MIME
    size_bytes: int
    sha256: str
    original_type: str | None    # SDK 経路の semantic tag
```

`original_type` は `add_object` 経由の入力で自動付与:

- `"ndarray"` (numpy 配列 → .npy 化)
- `"figure"` (matplotlib Figure → .png 化)
- `"dataframe"` (pandas → .parquet 化)
- `"dict"` / `"list"` / `"str"` / `"bytes"` (JSON 化)
- `None` (`add_file` / `add_bytes` 経由の raw 取り込み)

### 2.4 Nextcloud パス構造

```
{group_folder}/labvault/{team_id}/{record_id}/{filename}
```

`src/labvault/backends/nextcloud.py:16`。`team_id` がサブフォルダに入るので、
複数 team が同じ `group_folder` (例: `large/24UTARIM004`) を指しても衝突しない。

### 2.5 results フィールドの規約

**v0.3.0 以降**: `results[key] = value` の値は次のいずれかに限定:

- スカラー (`int` / `float` / `str` / `bool`)
- タプル `(value, "unit", "description")` — unit / description を同時セット
- 32 要素以下のスカラーの list

**禁止**: `dict` を丸ごと入れる (Firestore の nested map 検索性能が低いため)。
係数群は `fit_a`, `fit_b`, `fit_chi2` のように flat に展開する。

大きなオブジェクト (画像・配列・構造体) は `results` ではなく `add_file` /
`add_object` / `add_bytes` で Nextcloud に逃がす。

CLI `labvault check-results` で違反 record を検出可能。

### 2.6 CellLog

`teams/{team}/records/{record}/cell_logs/{cell_id}` のサブコレクション。
`src/labvault/core/types.py:242`

```python
@dataclass
class CellLog:
    cell_id: str                       # UUID hex
    record_id: str
    cell_number: int                   # 単調増加 (session 内)
    execution_count: int               # IPython の実行回数 (再実行で上書き)
    source: str                        # セルの source code
    source_hash: str                   # SHA-256
    new_vars: dict[str, Any]           # 新規変数の digest
    changed_vars: dict[str, Any]       # 値が変わった変数の digest
    deleted_vars: list[str]
    duration_sec: float
    executed_at: datetime
    error: dict | None                 # {type, message, traceback} or None
    session_id: str
```

変数の digest は O(1) で計算 (ndarray → shape + dtype + head SHA / DataFrame →
shape + columns + head SHA / それ以外は repr[:200])。生の値は保存しない
(サイズ・PII 対策)。

### 2.7 ShareEvent

`teams/{team}/share_events/{auto_id}`。2026-07-01 PR #106 で追加。共有操作を
Cloud Logging (30 日 retention) と併せて Firestore にも永続保存する監査ログ。

| field | 型 | 説明 |
|---|---|---|
| `event_type` | str | `granted` \| `revoked` \| `link_issued` \| `link_revoked` |
| `record_id` | str | 対象 record |
| `role` | str | `viewer` / `analyst` (revoke 系は空文字) |
| `actor_email` | str | 操作者 |
| `actor_audit_source` | str | `firebase` / `share-link` |
| `at` | datetime | UTC |
| `target_email` | str \| null | grant/revoke の相手 (share-link 系では null) |
| `token_hash_prefix` | str \| null | share-link 系のみ (先頭 16 chars) |
| `pseudo_email` | str \| null | share-link 系のみ |
| `label` | str \| null | share-link 発行時のラベル |

### 2.8 テンプレート

`teams/{team}/templates/{name}` に `TemplateV10` を保存
(`src/labvault/core/types.py:138`)。

**ビルトイン** (5 種): `XRD`, `SEM`, `SQUID`, `TEM`, `Raman`。
`src/labvault/core/builtin_templates.py` の `BUILTIN_TEMPLATES` で定義され、
`lab.new(title, template="XRD")` で初参照時に backend へ lazy save。

**主要 field**:

- `condition_fields: list[ConditionField]` — 条件のスキーマ (name, type, unit, aliases, required...)
- `required_conditions: list[str]` — `status=success/failed` 時に未入力ならば warn
- `result_fields: list[ResultField]` — 結果のスキーマ (unit / description を auto-fill)
- `indexed_fields: list[str]` — Firestore 検索用に `idx_<name>` として top-level 昇格
- `file_parsers: list[FileParserConfig]` — ファイル追加時の自動条件抽出 (拡張予定)
- `default_tags: list[str]`

### 2.9 ID 生成

`src/labvault/core/id.py`

- Crockford's Base32 (`0123456789ABCDEFGHJKMNPQRSTVWXYZ`) の 6 文字
- 例: `AB3F7K`
- `Lab._generate_unique_id()` は Firestore に重複チェックしつつ ID を発行
- 既存 4 文字 ID (mdxdb 移行分) との後方互換あり

---

## 3. 認可モデル

### 3.1 主体の 3 分類

| 主体 | 認証手段 | 識別子 |
|---|---|---|
| Firebase user | Firebase Auth (Google login) | `allowed_users/{email}` |
| PAT user | `Authorization: Bearer lv_*` | `pats/{token_id}` → owner_email |
| Share-link user | `Authorization: Bearer ls_*` | `shared_links/{token_hash}` → pseudo_email + record scope |

前 2 者は Firebase user と同じ権限を得る。3 者目 (share-link) は record 1 本と
role にスコープ固定。

### 3.2 権限行列

判定は `platform/backend/app/permissions.py`。

| 操作 | 関数 | super_admin | team admin | team member | share (viewer) | share (analyst) | share-link viewer | share-link analyst |
|---|---|---|---|---|---|---|---|---|
| record 閲覧 | `can_read` | ✅ | ✅ | ✅ | ✅ | ✅ | scope 一致のみ | scope 一致のみ |
| 子 record 作成 / ファイル upload / results 追記 | `can_analyze` | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | scope 一致のみ |
| record 自体の編集 (title / tag / status / conditions / results) | `can_edit` | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| 共有 grant / revoke / share-link 発行 | `can_grant` | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |

**変更点**: `can_grant` は 2026-07-01 PR #106 で「record 作成者本人」の枝を
削除して admin only 化。監査対象を team admin の操作に集約し、実験者の
誤操作事故を防ぐ設計。

### 3.3 shares の子孫継承

2026-07-01 PR #104。実験シリーズ (親 + N 子孫 record) を丸ごと共有するユース
ケースを想定:

- 親 record に `shares = {email: role}` を付けると、子・孫の `can_read` /
  `can_analyze` も継承する
- 子に直接 `shares[email]` エントリがあれば継承より優先 (特定の子だけ role
  を下げる操作が可能)
- `can_grant` / `can_edit` は継承しない
- share-link scope は record 1 本固定 (子孫に降りない)
- 循環 / 過剰に深い chain は `_MAX_PARENT_DEPTH = 32` で切る

### 3.4 fetch helpers (uniform 404)

`permissions.py` は 3 種類の helper を提供:

- `fetch_readable_or_404(lab, record_id, user)` — record 不在 / 認可失敗の
  どちらも 404 で返す (存在オラクル隠蔽、GitHub private repo と同じ pattern)
- `fetch_analyzable_or_403(lab, record_id, user)` — read 通るが analyze 不可 → 403
- `fetch_grantable_or_403(lab, record_id, user)` — read 通るが grant 不可 → 403

read も通らない user への write endpoint は uniform 404 の方が漏れが少ないが、
「read までは通る user が write 拒否される」ケースは 403 の方が親切。

### 3.5 audit_source

`created_audit_source` / `updated_audit_source` に認証経路が記録される:

- `"firebase"` — Firebase auth / PAT / super-admin 経由
- `"share-link"` — `ls_*` トークン経由
- `null` — SDK 直接 (Notebook / 装置 PC。backend handler を通らない経路)

share-link 経由の書き込みが record に残らないと後追いできないため、audit フィルタ
の subject として使う。

### 3.6 共有 event 監査ログ

grant / revoke / share-link 発行 / share-link 失効 の 4 系統は 2 経路で記録:

- Cloud Logging: structured event (`record.share_granted` 等) — 30 日 retention、
  リアルタイム監視・アラート用
- Firestore `share_events` collection — 削除しない限り無期限、後追い調査用
  (§2.7)

Web UI の共有ダイアログに履歴パネル (`ShareEventsPanel`) を admin のみ可視で
展開可能。

---

## 4. SDK API

`from labvault import Lab` が入口。全メソッド sync。

### 4.1 Lab

| method | 用途 |
|---|---|
| `Lab(team=None, *, user=None, ...)` | 初期化。省略時は `Settings` (env / config.toml / credentials) から解決 |
| `lab.new(title, *, type=EXPERIMENT, template=None, tags=None, sample=None, auto_log=True, created_by=None, **conditions)` | 新規 record 作成 |
| `lab.get(record_id, *, auto_log=False)` | 既存 record 取得。`auto_log=True` で IPython hooks 再起動 |
| `lab.list(*, tags=None, status=None, type=None, created_by=None, parent_id="__unset__", conditions=None, limit=100, offset=0)` | 一覧。`parent_id="__unset__"` = 全 record / `None` = root only |
| `lab.search(query, *, tags=None, status=None, type=None, parent_id=None, conditions=None, limit=20)` | セマンティック検索 (Vertex AI embedding) |
| `lab.delete(record_id)` | ソフト削除 (`deleted_at` を打つ) |
| `lab.restore(record_id)` | ソフト削除の取り消し |
| `lab.recent(n=10)` / `lab.today()` / `lab.trash()` | 最近 n 件 / 今日 / 削除済み一覧 (時間軸の shortcut) |
| `lab.get_usage(*, created_by=None, max_records=20000)` | team の storage 集計 (records / files / bytes)、by_creator / by_extension / by_type |
| `lab.get_cell_logs(record_id, *, limit=100)` | Notebook セル履歴 |
| `lab.save_cell_log(record_id, data)` | 同上の書き込み (通常は Tracker が自動呼び出し) |
| `lab.define_template(template)` | テンプレート登録 |
| `lab.get_template(name)` | テンプレート取得 |
| `lab.templates()` | 登録済みテンプレート一覧 |
| `lab.close()` | SyncManager 停止 + backend 切断 |
| `lab.team` (property) | team_id |
| `lab.backend` (property) | 生の `MetadataBackend` (admin 経路のみ) |
| `lab.sync_status` (property) | pending 件数 / 直近 error などのバッファ同期状態 |

**注**: `lab.aggregate(...)` / `lab.get_overview(...)` は **Lab には無い**。集計系は
MCP tool (`aggregate` / `get_overview`) と CLI (`labvault aggregate` /
`labvault overview`) から Firestore を直接叩く実装で、SDK レベルには公開されて
いない。SDK 側から使いたい場合は `lab.list()` 結果を Python 側で集計するか、
`lab.get_usage()` を利用する。

### 4.2 Record

| method / property | 用途 |
|---|---|
| `rec.id` / `rec.title` / `rec.type` / `rec.status` / `rec.tags` / `rec.created_by` / `rec.created_at` / `rec.updated_at` / `rec.parent_id` / `rec.template_name` | property |
| `rec.conditions(**kw)` | 条件を書く (unit / description を template から自動補完) |
| `rec.get_conditions()` | 条件を dict で読む |
| `rec.get_condition_units()` / `rec.get_condition_descriptions()` | メタ情報 |
| `rec.results` | `_ResultsProxy`。`rec.results["k"] = (value, "unit", "desc")` or scalar |
| `rec.get_result_units()` / `rec.get_result_descriptions()` | メタ情報 |
| `rec.note(text, author="")` | メモ追記 (同 text 冪等) |
| `rec.tag(*tags)` / `rec.untag(*tags)` | タグ操作 |
| `rec.add(path)` — alias for `add_file` | 定義優先度は `add_file` |
| `rec.add_file(path)` | ローカルファイルを Nextcloud に upload |
| `rec.add_dir(dir_path)` | ディレクトリを再帰 upload |
| `rec.add_object(name, obj)` | Python オブジェクトを型判定して自動シリアライズ (ndarray → npy 等) |
| `rec.add_bytes(name, data, content_type="")` | 生バイト列 upload |
| `rec.add_ref(uri, *, location="", size_bytes=None, description="", doi="")` | 外部 URI 参照登録 (upload しない、ExternalRef として保存) |
| `rec.save(name, obj)` / `rec.put(name, data)` | `add_object` / `add_bytes` の syntactic sugar |
| `rec.list_data()` / `rec.data_refs` | ファイル一覧 |
| `rec.get_data(name)` | 添付ファイルを bytes で取得 (自動復元は無し。ndarray や DataFrame 等の復元は呼出側で) |
| `rec.link(target_id, relation="related_to", description="")` | 他 record への link 追加 |
| `rec.sub(title, *, type=MEASUREMENT, template=None, created_by=None, **conditions)` | 子 record 作成 (link 双方向自動貼り) |
| `rec.children()` | 直接の子 record 一覧 |
| `rec.grant_share(email, role)` / `rec.revoke_share(email)` | 共有設定 (SDK 直接呼び出し。backend の認可 check は別途) |
| `rec.shares` (property) | `{email: role}` の copy |
| `rec.cell_logs(*, limit=100)` | 紐付いた Notebook セル履歴 |
| `rec.status = Status.SUCCESS` (setter) | ステータス変更。`_persist` に反映 |
| `rec.title = "..."` / `rec.updated_by = "..."` (setter) | 対応 field を更新 |
| `rec.events` (property) | `log_value` / `log_event` で溜まった dict のリスト |
| `with rec:` | context manager。例外あれば FAILED、正常終了で SUCCESS |
| `rec.log_value(key, value)` | events に `{type:"value", key, value, timestamp}` を追記 (conditions には触らない) |
| `rec.log_event(event_type, description="")` | events に `{type:event_type, description, timestamp}` を追記 |
| `rec.pause_logging()` / `rec.resume_logging()` / `with rec.no_logging():` | Notebook セル自動記録の一時停止 |
| `rec.run_analysis(fn, *args, **kw)` | 子 analysis record を自動作成しつつ解析関数を実行 |

### 4.3 Tracker (Notebook 自動記録)

Notebook 環境で `lab.new(auto_log=True)` を叩くと `CellTracker` (IPython hooks)
が起動。`pre_run_cell` / `post_run_cell` で以下を保存:

- コードソース (`source` + SHA-256)
- 実行時刻 / duration
- 名前空間 diff (new_vars / changed_vars / deleted_vars) — O(1) digest
- エラー情報 `{type, message}` (traceback は保存されない、サイズ対策)

出力 (stdout / display) は保存しない (サイズ・PII 対策)。

再実行は `execution_count` で上書きされる (idempotent)。既存 record への
追記は `lab.get(id, auto_log=True)` で hooks 再起動。

### 4.4 装置制御スクリプト (`.py`)

Notebook 環境が無い装置 PC で `lab.new(auto_log=False)` として使う場合の推奨 API:

```python
with lab.new("2026-07-02 laser shot") as exp:
    exp.conditions(power_W=20.0)                  # 実験条件は conditions() で
    exp.log_value("temperature_C", 25.3)          # タイムスタンプ付き測定値を events に
    exp.log_event("laser_fired", "shot #001")     # イベントを events に
    result = measure()
    exp.results["intensity"] = (result, "counts", "signal peak")
```

`log_value` / `log_event` は共に `events` list に dict として追記される
(§2.2)。データ点の時系列を残す用途で、実験全体の設定値 (conditions) とは
別の記録経路。

### 4.5 Settings

`~/.labvault/config.toml` + `.env` + env var + `~/.labvault/credentials` の優先順位で
`Settings` (pydantic-settings) が値を組み立てる。主要 field:

| env | 用途 |
|---|---|
| `LABVAULT_TEAM` | team_id (default 動作) |
| `LABVAULT_USER` | Lab の `created_by` に入る識別子 |
| `LABVAULT_GCP_PROJECT` | Firestore プロジェクト (default: `klab-laser-process`) |
| `LABVAULT_FIRESTORE_DATABASE` | Firestore データベース (default: `labvault`) |
| `LABVAULT_NEXTCLOUD_URL` | Nextcloud エンドポイント |
| `LABVAULT_NEXTCLOUD_USER` / `_PASSWORD` | Nextcloud 認証 |
| `LABVAULT_NEXTCLOUD_GROUP_FOLDER` | Nextcloud のグループフォルダパス |
| `LABVAULT_PLATFORM_URL` | Platform (Cloud Run backend) URL |
| `LABVAULT_TOKEN` | PAT (`lv_*`)。設定されていれば SDK は Platform 経由で動作 (GCP ADC 不要) |
| `LABVAULT_AR_REPO` | Artifact Registry repo の full resource name (backend の `grant_reader` が叩く先) |
| `LABVAULT_AUTO_SYNC` | true (default) で SyncManager 起動 |
| `LABVAULT_SYNC_INTERVAL_SEC` | 30.0 (default) |
| `LABVAULT_AUTO_LOG` | true (default)。Notebook で `lab.new()` した時の IPython hooks 起動 |
| `LABVAULT_BUFFER_DIR` | SQLite バッファの保存先 (default: `~/.labvault/buffer/`) |
| `LABVAULT_BUFFER_CLEANUP` | true (default)。同期完了した record をバッファから削除 |
| `LABVAULT_BUFFER_RETENTION_DAYS` | 7 (default)。バッファに残しておく最大日数 |

### 4.6 Backend Protocol

`src/labvault/backends/base.py` に `MetadataBackend` / `StorageBackend` /
`SearchBackend` の 3 Protocol。実装:

| Protocol | Firestore | InMemory | Platform (PAT 経由) |
|---|---|---|---|
| MetadataBackend | `firestore.py` | `memory.py` | `platform_metadata.py` |
| StorageBackend | `nextcloud.py` | `memory.py` | `platform_storage.py` |
| SearchBackend | `firestore_search.py` | `memory.py` | `platform_search.py` |

`Lab.__init__` の自動選択:
- PAT が設定されていれば全 backend を Platform* に切替
- GCP ADC / config が揃っていれば Firestore + Nextcloud + Vertex AI
- どちらも無ければ InMemory

---

## 5. Web API

`platform/backend/app/`。FastAPI + Pydantic v2。全 endpoint は `/api/` prefix。

### 5.1 認証

| header | 用途 |
|---|---|
| `Authorization: Bearer <firebase-id-token>` | Firebase Auth (Web UI) |
| `Authorization: Bearer lv_<40 chars>` | PAT (SDK / CI) |
| `Authorization: Bearer ls_<40 chars>` | 外部共有 token |
| `X-Labvault-Team: <team_id>` | 対象 team を明示。省略時は `default_team` |

### 5.2 Auth / 管理系 (main.py 直接定義)

| method | path | 認可 | 用途 |
|---|---|---|---|
| GET | `/api/health` | 誰でも | health check |
| GET | `/api/auth/me` | Firebase auth 必須 | 承認状態 + teams + is_admin を返す (`authorized` / `deactivated` / `pending` / `unregistered`) |
| POST | `/api/auth/request-access` | Firebase auth 必須 | signup 申請 (pending_users に登録 + Slack 通知) |
| POST | `/api/auth/welcome-acknowledged` | 認可済 | `allowed_users.welcomed_at` を打つ |
| GET | `/api/auth/nextcloud-credentials` | 認可済 | team の Nextcloud group_folder + Secret Manager 経由の資格情報 |
| POST | `/api/auth/tokens` | 認可済 | PAT 発行 (`lv_*`、raw は 1 回のみ返却) |
| GET | `/api/auth/tokens` | 認可済 | 発行済 PAT 一覧 (prefix + created_at のみ) |
| DELETE | `/api/auth/tokens/{token_id}` | 認可済 | PAT revoke |
| GET | `/api/admin/pending` | admin | 承認待ち signup 一覧 |
| POST | `/api/admin/approve` | admin | signup 承認 (assign or create_team) |
| GET | `/api/admin/teams` | admin | teams 一覧 |
| GET | `/api/admin/users` | admin | allowed_users 一覧 |
| POST | `/api/admin/users/{email}/teams` | admin (対象 team の admin or super-admin) | user に team 追加 |
| DELETE | `/api/admin/users/{email}/teams/{team_id}` | 同上 | user から team 削除 |
| PATCH | `/api/admin/users/{email}` | admin | active / display_name / role 更新 |
| POST | `/api/admin/users/{email}/ar/grant` | admin | AR reader 再付与 (救済用) |

### 5.3 records 系 (routers/records.py, prefix `/api/records`)

| method | path | 認可 | 用途 |
|---|---|---|---|
| GET | `""` | Firebase auth + team | 一覧 (tags / status / type / created_by / parent_id / conditions フィルタ) |
| POST | `""` | 親記録に `analyze` (子作成時) or team member (root 作成時) | 新規 record 作成 |
| GET | `/aggregate` | team read | 数値 field の統計集計 |
| GET | `/shared-with-me` | 認可済 | 自分に共有された cross-team record 一覧 |
| GET | `/{record_id}` | `fetch_readable_or_404` | 詳細 |
| DELETE | `/{record_id}` | `can_edit` | ソフト削除 + share-link 一括 revoke |
| POST | `/{record_id}/restore` | `can_edit` | ソフト削除の取り消し |
| GET | `/{record_id}/children` | `fetch_readable_or_404` | 子 record 一覧 (per-child re-filter) |
| GET | `/{record_id}/children/conditions` | `fetch_readable_or_404` | 子の条件・結果 batch (散布図用) |
| GET | `/{record_id}/cell_logs` | `fetch_readable_or_404` | Notebook セル履歴 |
| GET | `/{record_id}/shares` | `fetch_grantable_or_403` | 共有 email 一覧 (grant 主体のみ全件) |
| POST | `/{record_id}/shares` | `fetch_grantable_or_403` | 共有追加 (Firebase user 向け) |
| DELETE | `/{record_id}/shares/{email}` | `fetch_grantable_or_403` | 共有解除 |
| GET | `/{record_id}/share-events` | `fetch_grantable_or_403` | 監査 log 履歴 (新しい順) |
| GET | `/{record_id}/share-links` | `fetch_grantable_or_403` | 外部 token 一覧 |
| POST | `/{record_id}/share-links` | `fetch_grantable_or_403` | 外部 token 発行 (raw token は 1 回のみ) |
| DELETE | `/{record_id}/share-links/{token_hash_prefix}` | `fetch_grantable_or_403` | 外部 token revoke |
| PATCH | `/{record_id}/conditions` | `can_edit` | 条件更新 |
| POST | `/{record_id}/tags` | `can_edit` | タグ追加 / 削除 |
| POST | `/{record_id}/notes` | `can_edit` | メモ追記 |
| PATCH | `/{record_id}/status` | `can_edit` | ステータス更新 |
| PATCH | `/{record_id}/units` | `can_edit` | condition unit 変更 |
| PATCH | `/{record_id}/result_units` | `can_edit` | result unit 変更 |
| POST | `/{record_id}/results` | `can_analyze` | 結果追記 (analyst 共有された外部 user も可) |

### 5.4 files / preview / search (それぞれ prefix あり)

| method | path | 認可 | 用途 |
|---|---|---|---|
| GET | `/api/records/{id}/files` | `fetch_readable_or_404` | ファイル一覧 (メタ) |
| POST | `/api/records/{id}/files` | `fetch_analyzable_or_403` | ファイル upload (multipart) |
| GET | `/api/records/{id}/files/{filename}` | `fetch_readable_or_404` | ファイル download |
| GET | `/api/records/{id}/preview/{filename}` | `fetch_readable_or_404` | CSV / JSON / テキストのプレビュー |
| GET | `/api/search` | team read | セマンティック検索 (Firestore Vector Search) |

### 5.5 bulk upload (routers/bulk_upload.py)

router prefix は `/api/records/{record_id}/bulk-upload`。親 record 配下で
NxM グリッドから子 record への一括ファイル upload を行う。

| method | path | 認可 | 用途 |
|---|---|---|---|
| POST | `/api/records/{record_id}/bulk-upload/preview` | `fetch_analyzable_or_403` | ファイル名 → 子 record マッチのプレビュー |
| POST | `/api/records/{record_id}/bulk-upload` | `fetch_analyzable_or_403` + per-child `can_analyze` | 実行 (SSE で進捗返却) |

### 5.6 metadata (routers/metadata.py, prefix `/api/metadata`)

Platform mode の SDK (`platform_metadata.py` / `platform_storage.py`) が使う
低レベル API。認証は Firebase / PAT 共通。認可は endpoint 内で
`fetch_*_or_404` 等を呼ぶ。record CRUD / template CRUD / cell_log write /
Nextcloud storage passthrough / semantic search 全般をカバー。

### 5.7 share-link (routers/share_links.py)

| method | path | 認可 | 用途 |
|---|---|---|---|
| GET | `/api/share-links/me` | `ls_*` token | 自分の scope (record_id + role + team) を返す |

### 5.8 PyPI proxy (routers/pypi_proxy.py, prefix `/api/pypi`)

Artifact Registry `labvault-pypi` を PAT 認証で proxy する。装置 PC / CI で
`pip install --extra-index-url https://__token__:lv_*@labvault-api.../api/pypi/simple/ labvault` の形。

### 5.9 例外ハンドラ

`main.py:117` の `HTTPException` handler と `main.py:141` の broad `Exception`
handler が **全レスポンスに `Cache-Control: no-store` を付与**。エラーレスポンスの
ブラウザキャッシュを構造的に防ぐ (PR #53 / #74 の教訓)。

CORS: `LABVAULT_CORS_ORIGINS` (default `localhost:3000`)。500 レスポンスにも
CORS ヘッダが付くよう global handler で処理 (PR #49)。

---

## 6. MCP tools

`src/labvault/mcp/server.py` に 9 ツール。ローカル起動:

```
labvault mcp
```

または Streamable HTTP (Cloud Run) 経由。全ツールに `team: str | None` (省略時は
`LABVAULT_TEAM` env) の共通引数。

### 6.1 ツール一覧

| tool | 引数 | 用途 |
|---|---|---|
| `search` | query, tags, status, record_type, parent_id, created_by, conditions, include_conditions, limit | レコード検索。conditions は完全一致 or 範囲 (`{"gte": 10}` 等)。created_by は email 完全一致。返却に `created_by` field 含む |
| `get_detail` | record_id | 条件・結果・メモ・ファイル一覧の詳細 dict |
| `compare` | record_ids (最大 10), fields | 横断比較。common / differences を返す |
| `data_preview` | record_id, filename, max_rows | CSV / JSON / テキストのプレビュー |
| `aggregate` | key, group_by, parent_id, record_type, status, tags | 数値 field の統計 (count / mean / std / min / max / median) |
| `get_overview` | parent_id, record_type | 実験シリーズの概要 (子数 / status / 条件ユニーク値・統計 / 結果統計) 1 shot |
| `get_notebook_log` | record_id, limit | 紐付いた CellLog (cell_number 昇順) — LLM が Notebook 履歴を辿る用 |
| `get_timeline` | record_id, tags, limit | 時系列で record 一覧 |
| `get_usage` | created_by | team の storage 集計 (records / files / bytes / by_creator / by_extension / by_type) |

### 6.2 ツール連鎖パターン (instructions で誘導)

- 探索型: `search(query="...")` → `get_detail(record_id=...)`
- 比較型: `search` → `compare(record_ids=[...])`
- 統計型: `aggregate(key=...)` or `get_overview(parent_id=...)`
- データ確認: `get_detail` → `data_preview`
- 範囲検索: `search(conditions={"power": {"gte": 50}})`

### 6.3 リモート MCP (Streamable HTTP)

Cloud Run 上で `--stateless-http` モードで起動 (`FastMCP` の
`stateless_http=True`)。Claude Desktop / Code から Streamable HTTP エンドポイントを
接続する。認証は Bearer PAT (`lv_*`) を expected。

---

## 7. CLI

`labvault` コマンド。全 18 個。`--help` で詳細:

| コマンド | 用途 |
|---|---|
| `init` | `~/.labvault/config.toml` 生成 (対話) |
| `new <title>` | 新規 record 作成 |
| `add <record_id> <files>` | ファイル追加 |
| `list` | 一覧 (tags / status / type / limit) |
| `show <record_id>` | 詳細表示 |
| `search [query]` | 検索 (`--tags` / `--status` / `--type` / `--created-by` / `--parent-id` / `--conditions` / `--show-conditions`) |
| `doctor` | 設定の健全性チェック |
| `usage` | team の storage 集計 (`--created-by` で絞り込み、`--top-creators` で上位表示数) |
| `delete <record_id>` | ソフト削除 |
| `restore <record_id>` | ソフト削除取り消し |
| `note <record_id> <text>` | メモ追記 |
| `tag <record_id> <tags>` | タグ操作 (`--remove` で削除) |
| `status <record_id> <status>` | ステータス変更 |
| `check-results` | 既存 record の results 規約違反スキャン (dict / list 長 / etc) |
| `export <output_dir>` | JSON エクスポート |
| `aggregate <key>` | 数値統計 |
| `overview <parent_id>` | 実験シリーズ概要 |
| `mcp` | MCP サーバー起動 (stdio) |

CLI は plain text 出力なので LLM の Bash 経由呼び出しでは MCP より低トークン
消費になる。

---

## 8. Firestore 複合 index

`firestore.indexes.json` で管理。deploy は `firebase deploy --only firestore:labvault`
(multi-database 環境の firebase-tools 14.x バグを踏まないよう `firestore:indexes`
は避ける)。

`tests/unit/test_firestore_indexes.py` に invariant test あり — SDK 側で叩く
query 形と declaration の zsh 整合を CI で検証する。

### 8.1 現行の index 一覧

| collection | scope | fields | 用途 |
|---|---|---|---|
| records | COLLECTION | `deleted_at + updated_at DESC + embedding VECTOR` | vector search 用 (deleted 除外) |
| records | COLLECTION | `embedding VECTOR` | vector search 用 (無条件) |
| records | COLLECTION | `deleted_at + status + updated_at DESC` | 一覧 status フィルタ |
| records | COLLECTION | `deleted_at + updated_at DESC` | 一覧 baseline |
| records | COLLECTION | `parent_id + deleted_at + updated_at DESC` | 子 record 一覧 |
| records | COLLECTION | `deleted_at + idx_target + updated_at DESC` | template indexed_fields (`target`) |
| records | COLLECTION | 同 パターンで `idx_measurement_mode` / `idx_sample_name` / `idx_laser_wavelength_nm` / `idx_mode` / `idx_method` | 各 template の indexed_fields |
| records | COLLECTION | `deleted_at + parent_id + idx_sample_name + updated_at DESC` / `deleted_at + parent_id + idx_target + updated_at DESC` | 親配下フィルタ |
| records | COLLECTION | `deleted_at + created_by + updated_at DESC` | `--created-by` フィルタ |
| records | COLLECTION | `deleted_at + parent_id + created_by + updated_at DESC` | 親配下の `--created-by` |
| records | COLLECTION | `deleted_at + tags CONTAINS + updated_at DESC` | tags 検索 (2026-07-01 追加) |
| records | COLLECTION_GROUP | `deleted_at + shared_with_emails CONTAINS + updated_at DESC` | shared-with-me cross-team |
| share_events | COLLECTION | `record_id + at DESC` | 監査 log 履歴 (2026-07-01 追加) |

### 8.2 index を必要としないパターン (invariant で documented)

- `shared_links`: `token_hash == x` の単一 equality + zigzag merge — composite 不要
  (`test_shared_links_does_not_require_composite_index`)

---

## 9. 運用

### 9.1 GCP プロジェクト

- Project: `klab-laser-process`
- Region: `asia-northeast1`
- Firestore database: `labvault` (default ではない)
- Nextcloud: `https://arim.mdx.jp/nextcloud`、group folder `large/24UTARIM004`
- Artifact Registry repo: `asia-northeast1-docker.pkg.dev/klab-laser-process/labvault`
  (backend / frontend の container image)
- PyPI 配布: Artifact Registry `asia-northeast1 / klab-laser-process / labvault-pypi`

### 9.2 Cloud Run デプロイ

自動デプロイ (`.github/workflows/`):

- `deploy-backend.yml` — main push で `platform/backend/**`, `src/**`, `pyproject.toml`
  のいずれかが変わったら `labvault-api` を deploy
- `deploy-frontend.yml` — main push で `platform/frontend/**` が変わったら
  `labvault-web` を deploy
- 両 workflow とも `workflow_dispatch` (手動 trigger) も可能

Runtime SA: `labvault-api@klab-laser-process.iam.gserviceaccount.com`
(backend / frontend 共通)。AR に `repoAdmin` を持ち、backend からの
`grant_reader` (allowed_users 承認時) を同 SA で叩く。

**公開 URL**:
- backend: `https://labvault-api-6vn6gn4iaa-an.a.run.app`
- frontend: `https://labvault-web-6vn6gn4iaa-an.a.run.app`

CI (`ci.yml`) は lint (ruff + mypy) + pytest + frontend build を回すが、deploy
workflow の前段ではない。CI red のまま main に入ると deploy も走る点に注意。

### 9.3 PyPI publish

- Semantic Versioning (`MAJOR.MINOR.PATCH`)
- リリース手順:
  1. `pyproject.toml` の `version` を上げる
  2. main に push
  3. `git tag v<version> && git push origin v<version>`
  4. `publish-pypi.yml` がタグと version の一致を検証 → wheel + sdist を AR に upload
- 同 version の再 publish は AR が reject
- `v*` タグの強制更新は禁止

### 9.4 Firestore index deploy

CI では検証されない (エミュレータは index 不要)。本番反映は手動:

```bash
firebase deploy --only firestore:labvault --project klab-laser-process
```

`--only firestore:indexes` は firebase-tools 14.x の multi-database バグに当たる
ので避ける。

### 9.5 Firebase Auth (Google login)

allowed_users で承認された Google アカウントが Web UI にログインできる。
未登録ユーザーは signup 申請フォーム (`/api/auth/request-access`) → super-admin
が `/admin/pending` で承認。approve 時 team を新規作成する場合は super-admin
権限が必須 (`action="create_team"`)。

### 9.6 PAT (Personal Access Token, `lv_*`)

- SDK が Notebook / 装置 PC / CI から Cloud Run backend を叩くための token
- Web UI `/account/tokens` から発行 (raw は 1 回のみ表示 → 以降 SHA-256 hash のみ保存)
- 発行時に AR reader も自動付与 (`grant_reader`) — `pip install labvault` を可能に
- `LABVAULT_TOKEN` env に設定すれば SDK は Platform 経由で動作 (GCP ADC 不要)

### 9.7 外部共有トークン (`ls_*`)

- team admin が record 単位で発行
- pseudo_email + pseudo_display_name が必須 (record への書き込み audit 用)
- role: `viewer` (閲覧のみ) / `analyst` (子 record 作成 + upload 可)
- expires_days: 0 (無期限) 〜 365、default 30
- URL 設計: `/share/<record_id>#<token>` (fragment)。Cloud Run access log / Referer
  に token が残らない (2026-06-30 PR #101)

### 9.8 observability

- 全 handler で structured log (JSON Lines) を Cloud Logging に emit
  (`app/observability.py`)
- `EventTimer` で slow request を WARNING 格上げ
- share grant / revoke / share-link 発行・失効は `record.share_*` event として log
- Retention: 30 日 (Cloud Logging default)。永続監査は `share_events` collection
  (§2.7)
- log 中の email は grant / revoke / bulk_upload actor 系は raw、認証失敗系は
  `safe_email_for_log` で local part を mask (`ab*** @x.com`)
- share-link token は log に載る前に `ls_*` prefix + suffix でマスクされる
  (D2 filter)

### 9.9 コスト

月額 GCP コスト **$1 以下** (Firestore + Cloud Run + Vertex AI 無料枠内)。
`docs/design/v10/01_architecture_and_cost.md` に詳細試算 (合計 $0.94/月 の
安全マージン込み)。

---

## 補足: 参照

**設計思想**:
- `docs/design/v10/00_v10_overview.md` — アーキテクチャ全体像
- `docs/design/v10/01_architecture_and_cost.md` — コスト詳細
- `docs/design/v10/02_sdk_and_mcp.md` — SDK / MCP 仕様の設計時案
- `docs/design/v10/03_experiment_workflow.md` — テンプレート・パーサー・装置投入
- `docs/design/v10/04_sdk_cookbook.md` — SDK 使い方ガイド
- `docs/design/analysis_traceability.md` — 解析トレーサビリティ設計 (解析=Record)
- `docs/design/REQUIREMENTS.md` — 要件 R01-R22
- `docs/comparison_report.md` — mdxdb + webapp との比較

**運用**:
- `docs/ar_cleanup_policy.md` — Artifact Registry の cleanup
- `docs/auth_design.md` — 認証まわりの設計時ドキュメント
- `docs/firestore_indexes.md` — index 増減の作業手順
- `docs/instrument_pc_setup.md` — 装置 PC への labvault 導入手順
- `docs/mdg_integration.md` — MDG (孤立多重放電) 装置との連携
- `docs/multitenant_next_steps.md` — 複数 team 運用の残タスク
- `docs/onboarding.md` — 新規メンバー向け

**変更履歴**: `docs/backlog.md` の「✅ 済」節に日付順で記載 (別 PR でスリム化予定)。
