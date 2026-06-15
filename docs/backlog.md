# Backlog

「次に着手する候補」を優先度別に並べたキュー。完了したら `multitenant_next_steps.md` /
`design/v10/05_milestones.md` の該当エントリにも反映する。

最終更新: 2026-06-09

---

## 🔥 次に着手したい

### 1. 人力 QA / 受入れテスト
**規模**: 環境ごとに半日 / **詳細**: [`docs/qa_checklist.md`](qa_checklist.md)

複数 OS × 複数 Python × 複数ブラウザの組合せで実機動作を確認する。
SDK / CLI / MCP / WebUI / 装置 PC ワークフローの主要シナリオを網羅。
release 前 (semver タグ前) または大きな PR マージ後に通す。

### 2. backend endpoint-level test 拡充
**規模**: 各 30 分

PR #17/#19/#21 で主要 admin endpoint (pending / teams / users /
approve / users/{e}/teams / users/{e}) はカバー済。残り:

- `/api/auth/request-access` / `/api/auth/welcome-acknowledged`
- ビジネスルール検証 (最後の super-admin deactivate 不可、最後の team
  remove 不可など — 認可ではなく整合性)

### 3. team admin による pending 承認 (2 段階フロー設計)
**規模**: 設計 30 分 + 実装 1〜2 時間

current: pending は super-admin だけが見える。  
target: super-admin が「target team を指名」した時点で、その team の admin
にも pending queue が回ってきて承認できる。

申請段階で team list を申請者に晒さない (security) のが大前提。  
設計が固まったら別 issue / PR に分割。

### 4. AR 連動の運用ツールの残り
PR #22 で `scripts/ar_backfill.py` (gcloud subprocess 経由) 完了。残り:

- admin UI に AR grant 失敗時の retry button (1〜1.5 時間)
- AR repo cleanup ポリシー (古い wheel/sdist をどうするか — 設計のみ 30 分)

### 9. リモート MCP Phase 4: ローカル `labvault mcp` の位置付け整理
**規模**: 30〜60 分

#46/#47/#48 でリモート MCP (Cloud Run `/mcp` + PAT) は本番稼働済 + onboarding /
`/account/tokens` / README に登録手順あり。ただし設計メモ
[`docs/design/mcp_remote_hosting.md`](design/mcp_remote_hosting.md)
の Phase 4「ローカル `labvault mcp` (stdio) は装置 PC / 上級者向けに残す」を
docs に反映できていない。`docs/instrument_pc_setup.md` と onboarding §3
の文言を「通常はリモート、装置 PC 直結だけローカル」に揃える。

### 10. ファイル DL の防御強化 (今回の罠の再発防止)
**規模**: 30 分

#49〜#53 で「410 Gone がブラウザに焼き付いて修正後も古いレスポンスが
返り続ける」罠を踏んだ (結局 502 + Cache-Control: no-store で解決)。
二重保険として:

- frontend `downloadAuthed` 側で DL URL に cachebust クエリ
  (`&_t=${Date.now()}`) を足す
- CLAUDE.md (project + backend) に「エラーレスポンスには無条件で
  `Cache-Control: no-store`」「同じ症状が直らない時は Network タブの
  `(from disk cache)` を疑う」を追記

---

## 保留 (有用性を見極めてから着手)

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

### 2026-06-09
| PR | 内容 |
|---|---|
| #46 | リモート MCP Phase 1: `platform/backend` に `/mcp` (FastMCP Streamable HTTP) を mount、PAT 認証 ASGI middleware、stateless モード + lifespan rebuild |
| #47 | リモート MCP Phase 3 (Claude): `/account/tokens` UsageSnippets / onboarding §3-B / README に Claude Desktop / Code 用設定例。`auth set-token` を pip install の後に並べ直し |
| #48 | リモート MCP Phase 3 (multi-LLM): Cursor / Gemini CLI / ChatGPT Developer Mode / 汎用 block を追加 + 各 client の公式 docs リンク + 「設定書式は変わる」注意書き |
| #49 | CORS-safe exception handler (handler 内の未捕捉例外を CORS ヘッダ付き 500 に変換 — CLAUDE.md 既知ハマりの安全網) |
| #50 | `NextcloudException` の `status_code`/`reason` を response body の `message` に出して devtools から原因を読めるように。`download_file` で 410 / 502 のマッピング (後で #53 で 502 統一) |
| #51 | `NextcloudStorage._full_path` で rooted 形 (`{group_folder}/...`) の入力を prepend skip (ARIM MDX import 経路の救済) |
| #52 | Firestore に既に doubled で保存された `nextcloud_path` を読み出し時 strip (idempotent loop)。本命の DE9Z/condition.json DL が動いた |
| #53 | 410 Gone のデフォルトキャッシュ可能性で焼き付いた失敗レスポンス対策。`download_file` を 502 統一 + 全エラーレスポンスに `Cache-Control: no-store` |

### 2026-06-01
| PR | 内容 |
|---|---|
| #21 | admin write endpoints の authz テスト 21 ケース (approve / users/{e}/teams POST/DELETE / users/{e} PATCH; AR mock fixture autouse) |
| #22 | `scripts/ar_backfill.py` (allowed_users と AR reader binding の照合 + 漏れ補完、gcloud subprocess 経由)、Settings に `ar_repo` 追加、backend `_modify_policy` に `X-Goog-User-Project` header 対応 |

### 2026-05-26
| PR | 内容 |
|---|---|
| #17 | backend test 基盤 (`platform/backend/tests/conftest.py` + 4 役 fixture + FakeDB) + `/api/admin/pending` `/api/admin/teams` の authz テスト (8 ケース) |
| #18 | `/api/records` に conditions パラメータ追加 + WebUI `/records` に条件 chip 露出 |
| #19 | `/api/admin/users` の authz テスト (super=全 user / team admin=自 team + `restrict_to` で他 team を隠す, 5 ケース) |
| #20 | 条件 chip の key 入力に template の `indexed_fields` を `<datalist>` で suggest + 補足説明 |

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
