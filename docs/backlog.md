# Backlog

「次に着手する候補」を優先度別に並べたキュー。完了したら `multitenant_next_steps.md` /
`design/v10/05_milestones.md` の該当エントリにも反映する。

最終更新: 2026-05-18

---

## 🔥 すぐ着手したい (smoke test で見えた付随 issue)

### 1. `labvault doctor` の判定を実態に合わせる
**規模**: 30 分

`docs/install_onboarding` で「動作確認に doctor を使ってください」と書いたが、
実機 smoke で以下の過剰判定が露呈:

- `~/.labvault/config.toml` が無いだけで `[!!]` (failed) になる
  → `.env` / `~/.labvault/credentials` / 環境変数で設定できるのに足切り
  → `[--]` (optional, info) に格下げ
- `LABVAULT_PLATFORM_URL` を見ていない
  → PAT モードの主軸なので、設定/未設定を `[OK]`/`[--]` で表示
- `LABVAULT_NEXTCLOUD_URL` が未設定 = `[--] Nextcloud: not configured`
  → 実は `LABVAULT_PLATFORM_URL` がある場合は platform 経由で取得するので
    「Nextcloud は platform 経由 (`[OK]`)」と区別表示したい
- `LABVAULT_TOKEN` の有無もチェック (PAT モード判定)
- (任意) `Lab()` を 1 回作って `_metadata` の型名を表示すれば backend
  判別行を doctor 内で完結できる

**ファイル**: `src/labvault/cli/main.py:245` (`def doctor`)

### 2. `labvault.__version__` を `pyproject.toml` と同期
**規模**: 10 分

現状:
- `labvault --version` → 0.1.2 (正)
- `labvault.__version__` → 0.1.0 (古い hardcoded)

修正案: `src/labvault/__init__.py` で

```python
from importlib.metadata import version as _v
__version__ = _v("labvault")
```

`__version__` 直書きは pyproject と二重管理で必ずズレるので、
`importlib.metadata` 経由にすれば一本化される。

### 3. PAT 経路の venv smoke
**規模**: 5 分 (PAT 発行を Web UI で 1 つもらえれば)

今回の smoke は ADC モードだけ。PAT モードも本番で動くか同じ手順で確認:

1. Web UI `/account/tokens` で「装置 PC smoke (Token 2026-05-18)」等を発行
2. 一時的に `~/.labvault/credentials` に書く (`LABVAULT_TOKEN` + `LABVAULT_PLATFORM_URL`)
3. venv で `python -c "from labvault import Lab; lab=Lab(); print(type(lab._metadata).__name__)"`
   → `PlatformMetadataBackend` と出ること
4. record 1 件作成→削除
5. 終わったら token を `/account/tokens` で revoke

---

## M3 続編 (template 基盤の上に乗せる)

### 4. `file_parsers` 経由の `Record.add()` 自動 parse
**規模**: 半日〜1 日

template に宣言された `FileParserConfig` を見て、`record.add("data.ras")` の
タイミングで対応パーサーを起動 → conditions を自動充填。**手動入力は常に優先**。

- 既存実装: `parsers/vk4.py` (Keyence VK4) / `parsers/plux.py`
- 追加対象: `parsers/builtin/ras.py` (Rigaku XRD)
- `ParserRegistry` (`parsers/base.py`) の整備
- `Record.add()` から `_template.file_parsers` を引いて拡張子マッチ
- テスト: parser 未定義の拡張子は no-op、手動 conditions が parser 値で上書きされないこと

### 5. `indexed_fields` の Firestore top-level 昇格
**規模**: 1〜2 時間

`TemplateV10.indexed_fields` (例: XRD なら `["target", "method", "sample_name"]`)
の値を、`FirestoreMetadataBackend.create_record` / `update_record` 時に
`idx_<field>` として top-level に複製。Firestore の where filter / 複合 index
で使えるようにする。

- `record._to_dict()` に `_template_indexed_fields()` のような hook
- 既存 record の backfill scriptは別途検討 (やる場合)

---

## 多テナント / 認証拡張の残

### 6. backend endpoint-level test 基盤
**規模**: 2〜3 時間

`platform/backend/tests/` を新設。`TestClient` で:
- super-admin / team-admin / member / unauth の 4 役で各 admin endpoint を叩く
- 期待: super=全許可、team admin=自 team のみ、それ以外=403
- `_admin_team_filter` のフィルタが効いていることも確認

Firestore は emulator or `unittest.mock` で stub。

### 7. AR 連動の運用ツール
- 既存ユーザー一括 backfill スクリプト (`scripts/ar_backfill.py`)
- admin UI に AR grant 失敗時の retry button
- AR repo cleanup ポリシー (古い patch をどうするか)

### 8. team admin による pending 承認 (2 段階フロー設計)
**規模**: 設計 30 分 + 実装 1〜2 時間

current: pending は super-admin だけが見える。  
target: super-admin が「target team を指名」した時点で、その team の admin
にも pending queue が回ってきて承認できる。

申請段階で team list を申請者に晒さない (security) のが大前提。  
設計が固まったら別 issue / PR に分割。

---

## オンボーディング / ドキュメント

### 9. README install を別 GCP アカウントで実機テスト
**人間オペレータ案件** (Claude では新規 Google account 作成 + admin 承認の
フローが踏めない)。今回の venv smoke で承認済 user 経路は確認済なので、
未承認 user の体験 (pip install が 403 を踏むか / 承認後すぐ通るか) だけが残り。

### 10. M5 拡張 (中長期)
- `ProcessChain` (連鎖実験の親子 link をワンライナーで)
- `nextcloud_poller` (`_inbox/` 監視 → 自動 record 化)
- 追加パーサー (`.dm3`, `.dat` (MPMS/PPMS), `.wdf` (Raman))

`docs/design/v10/05_milestones.md` の M5 セクション参照。

---

## 参考: 直近マージ済 (2026-05-18)

| PR | 内容 |
|---|---|
| #2 | team-scoped admin + UserCard 権限分岐 |
| #3 | README install 改訂 |
| #4 | report.md 削除 |
| #5 | UserCard chip の他 team 漏れ修正 + doc 同期 |
| #6 | M3 テンプレート基盤 (XRD full / 4 種スタブ / alias 正規化 / required 警告) |
