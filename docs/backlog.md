# Backlog

「次に着手する候補」を優先度別に並べたキュー。完了したら `multitenant_next_steps.md` /
`design/v10/05_milestones.md` の該当エントリにも反映する。

最終更新: 2026-05-19

---

## 🔥 次に着手したい

### 1. `file_parsers` 経由の `Record.add()` 自動 parse
**規模**: 半日〜1 日 / **マイルストーン**: M3 part 2

template に宣言された `FileParserConfig` を見て、`record.add("data.ras")` の
タイミングで対応パーサーを起動 → conditions を自動充填。**手動入力は常に優先**
(parser 値で上書きしない)。M3 の本流。

- 既存実装: `parsers/vk4.py` (Keyence VK4) / `parsers/plux.py`
- 追加対象: `parsers/builtin/ras.py` (Rigaku XRD)
- `ParserRegistry` (`parsers/base.py`) の整備
- `Record.add()` から `template.file_parsers` を引いて拡張子マッチ
- テスト: 拡張子未定義は no-op / 手動 conditions が parser 値で上書きされない

### 2. Firestore composite index の登録
**規模**: 30 分 / **PR #11 のフォロー**

PR #11 で `idx_target` / `idx_method` / `idx_sample_name` 等を top-level に書く
ようにしたが、Firestore でクエリするには対応する単一/複合 index を明示作成する
必要がある。

- 単一 index: `idx_target asc` 等は自動 index でカバーされる
- 複合 index (例: `idx_target asc + status asc + updated_at desc`) は手動定義
- `firestore.indexes.json` で宣言、`gcloud firestore indexes` で apply

### 3. 既存 record の `idx_*` backfill スクリプト (任意)
**規模**: 30 分 / **PR #11 のフォロー**

`indexed_fields` 昇格は新規 / 更新 record にのみ効く。既存 record を一括で
再 set する `scripts/idx_backfill.py` を追加。当面は新規分のみで運用可。

---

## 多テナント / 認証拡張の残

### 4. backend endpoint-level test 基盤
**規模**: 2〜3 時間

`platform/backend/tests/` を新設。`TestClient` で:
- super-admin / team-admin / member / unauth の 4 役で各 admin endpoint を叩く
- 期待: super=全許可、team admin=自 team のみ、それ以外=403
- `_admin_team_filter` のフィルタが効いていることも確認

Firestore は emulator or `unittest.mock` で stub。

### 5. AR 連動の運用ツール
- 既存ユーザー一括 backfill スクリプト (`scripts/ar_backfill.py`)
- admin UI に AR grant 失敗時の retry button
- AR repo cleanup ポリシー (古い patch をどうするか)

### 6. team admin による pending 承認 (2 段階フロー設計)
**規模**: 設計 30 分 + 実装 1〜2 時間

current: pending は super-admin だけが見える。  
target: super-admin が「target team を指名」した時点で、その team の admin
にも pending queue が回ってきて承認できる。

申請段階で team list を申請者に晒さない (security) のが大前提。  
設計が固まったら別 issue / PR に分割。

---

## オンボーディング / ドキュメント

### 7. README install を別 GCP アカウントで実機テスト
**人間オペレータ案件**。Claude では新規 Google account 作成 + admin 承認の
フローが踏めない。承認済 user の venv 経路は 2026-05-18/19 の smoke で確認済
(ADC モード / PAT モードどちらも end-to-end 成功)。残りは未承認 user の体験
(pip install が 403 を踏むか / 承認後すぐ通るか) のみ。

---

## 中長期 (M5 拡張)

### 8. `ProcessChain`
連鎖実験の親子 link をワンライナーで。

### 9. `nextcloud_poller`
Nextcloud の `_inbox/` を監視して自動 record 化。

### 10. 追加パーサー
`.dm3` (TEM), `.dat` (MPMS/PPMS), `.wdf` (Raman) など。`docs/design/v10/05_milestones.md` の M5 セクション参照。

---

## 参考: 直近マージ済

### 2026-05-19
| PR | 内容 |
|---|---|
| #8 | `__version__` を pkg metadata 経由に + `labvault doctor` の判定見直し (PAT/Mixed/Direct モード行、`config.toml` を [--] 化) |
| #9 | Welcome の「トークンを発行」が dismiss + push を行うように + トップを Dashboard 化、records 一覧を `/records` に分離 |
| #10 | `/welcome` を永続 URL 化 |
| #11 | template の `indexed_fields` を `idx_*` で top-level に昇格 (+ `Lab._template_cache`) |

### 2026-05-18
| PR | 内容 |
|---|---|
| #2 | team-scoped admin + UserCard 権限分岐 |
| #3 | README install 改訂 (申請→承認→install フロー / PAT vs ADC 二択 / doctor 紹介) |
| #4 | report.md 削除 |
| #5 | UserCard chip の他 team 漏れ修正 (`_resolve_teams` の restrict_to) + doc 同期 |
| #6 | M3 テンプレート基盤 (XRD full / 4 種スタブ / alias 正規化 / required 警告) |
| #7 | docs/backlog.md 作成 |
