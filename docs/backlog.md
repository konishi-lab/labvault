# Backlog

「次に着手する候補」を優先度別に並べたキュー。完了したら `multitenant_next_steps.md` /
`design/v10/05_milestones.md` の該当エントリにも反映する。

最終更新: 2026-05-25

---

## 🔥 次に着手したい

### 1. backend endpoint-level test 基盤
**規模**: 2〜3 時間

`platform/backend/tests/` を新設。`TestClient` で:
- super-admin / team-admin / member / unauth の 4 役で各 admin endpoint を叩く
- 期待: super=全許可、team admin=自 team のみ、それ以外=403
- `_admin_team_filter` のフィルタが効いていることも確認

Firestore は emulator or `unittest.mock` で stub。多テナント認証拡張の
回帰防止網。次の重い宿題。

### 2. 既存 record の retroactive template 紐付け
**規模**: 設計 30 分 + 実装 1 時間

2026-05-25 の `idx_*` backfill で発覚: konishi-lab team の 4863 record
のうち **4860 件が template 未紐付け** (MDG import の歴史的データなど)。
これらは PR #14 の push down 高速化の対象外。

- 文字列 / 拡張子 / 既存 tag から推測して template を当てる候補抽出
- `--dry-run` で人が確認 → 一括 set
- 推測精度より「明示しないと触らない」安全性を優先

scope は別 issue で詰める。緊急ではない (現状でも検索は post-filter で
動く)。

### 3. AR 連動の運用ツール
- 既存ユーザー一括 backfill スクリプト (`scripts/ar_backfill.py`)
- admin UI に AR grant 失敗時の retry button
- AR repo cleanup ポリシー (古い patch をどうするか)

### 4. team admin による pending 承認 (2 段階フロー設計)
**規模**: 設計 30 分 + 実装 1〜2 時間

current: pending は super-admin だけが見える。  
target: super-admin が「target team を指名」した時点で、その team の admin
にも pending queue が回ってきて承認できる。

申請段階で team list を申請者に晒さない (security) のが大前提。  
設計が固まったら別 issue / PR に分割。

---

## オンボーディング / ドキュメント

### 5. README install を別 GCP アカウントで実機テスト
**人間オペレータ案件**。Claude では新規 Google account 作成 + admin 承認の
フローが踏めない。承認済 user の venv 経路は 2026-05-18/19 の smoke で確認済
(ADC モード / PAT モードどちらも end-to-end 成功)。残りは未承認 user の体験
(pip install が 403 を踏むか / 承認後すぐ通るか) のみ。

---

## 中長期 (M5 拡張)

### 6. `ProcessChain`
連鎖実験の親子 link をワンライナーで。

### 7. `nextcloud_poller`
Nextcloud の `_inbox/` を監視して自動 record 化。

### 8. 追加パーサー (低優先)
`.dm3` (TEM), `.dat` (MPMS/PPMS), `.wdf` (Raman), `bruker_raw_parser`
(.raw), `xy_parser` (.xy) など。`docs/design/v10/05_milestones.md` の
M5 セクション参照。XRD template には宣言済だが parser 本体は未実装で、
拡張子マッチ時に UserWarning でスキップされる現状を許容している。

---

## 参考: 直近マージ済

### 2026-05-25
| PR | 内容 |
|---|---|
| #13 | template の `file_parsers` 経由で `Record.add()` 自動 parse (M3 part 2、Rigaku `.ras` 実装 / `ParserRegistry` / 手動入力優先) |
| #14 | `Lab.search` / `Lab.list` の Firestore push down (`idx_<key>`) + `firestore.indexes.json` + gcloud apply スクリプト + `firebase.json` |
| #15 | `scripts/idx_backfill.py` (既存 record の `idx_*` を template から補完) |
| 本番 apply | Firestore 複合 index 8 個を gcloud で submit → 全 READY (13 個 / 5 既存 + 8 新規) |
| 本番 backfill | konishi-lab team 4863 record スキャン → template 紐付け 3 件 (うち補完対象 2 件) を `--apply` 済 |

### 2026-05-19
| PR | 内容 |
|---|---|
| #8 | `__version__` を pkg metadata 経由に + `labvault doctor` の判定見直し (PAT/Mixed/Direct モード行、`config.toml` を [--] 化) |
| #9 | Welcome の「トークンを発行」が dismiss + push を行うように + トップを Dashboard 化、records 一覧を `/records` に分離 |
| #10 | `/welcome` を永続 URL 化 |
| #11 | template の `indexed_fields` を `idx_*` で top-level に昇格 (+ `Lab._template_cache`) |
| #12 | docs/backlog.md 更新 (2026-05-19 版) |

### 2026-05-18
| PR | 内容 |
|---|---|
| #2 | team-scoped admin + UserCard 権限分岐 |
| #3 | README install 改訂 (申請→承認→install フロー / PAT vs ADC 二択 / doctor 紹介) |
| #4 | report.md 削除 |
| #5 | UserCard chip の他 team 漏れ修正 (`_resolve_teams` の restrict_to) + doc 同期 |
| #6 | M3 テンプレート基盤 (XRD full / 4 種スタブ / alias 正規化 / required 警告) |
| #7 | docs/backlog.md 作成 |
