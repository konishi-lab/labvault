# labvault 人力 QA チェックリスト

リリース前 / 大きな PR マージ後 / 装置 PC を初期設定する時の動作確認
チェックリスト。複数 OS × 複数 Python × 複数ブラウザの組合せで通すことで、
ユニットテストではカバーしきれない実環境の不具合を拾う。

各セクションは独立して走らせられる。担当 / 環境 / 日付を記録しながら
チェックボックスを埋めていく運用を想定。

---

## 0. 環境マトリクス

「最低限」と書いてある列は必ず通す。「広域」はリリース前に一巡。

| 区分 | 最低限 | 広域 |
|---|---|---|
| OS | macOS (Apple Silicon) + Windows 11 | + Ubuntu 22.04 LTS |
| Python | 3.12 | + 3.10, 3.11 |
| Node.js | 20 LTS | + 22 (latest) |
| ブラウザ (Web UI 利用者) | Chrome 最新 | + Safari, Firefox, Edge |
| GCP アカウント種別 | Google 個人 + Workspace | + Email-password サインアップ |
| 接続モード | PAT モード + ADC モード | + Mixed (env 一部だけ設定) |

実施記録テンプレート:

```
日付:        2026-XX-XX
担当:        @your-name
labvault:    v0.1.x (= pyproject.toml と __version__ 一致)
OS:          macOS 15.x / Windows 11 / Ubuntu 22.04
Python:      3.12.x
Node:        20.x.x
ブラウザ:    Chrome 1XX.x.x.x
特記事項:
```

---

## 1. インストール

### 1.1 SDK インストール (PAT モード)

未承認の新規ユーザー向け体感確認は backlog #5 (人間オペレータ案件) を
参照。ここでは **承認済ユーザーが新しい環境にセットアップする** ケース。

- [ ] **clean venv を作る**:
  ```bash
  python -m venv .venv && source .venv/bin/activate
  # Windows PowerShell: .venv\Scripts\Activate.ps1
  ```
- [ ] **AR repo を pip index に指定して install**:
  ```bash
  pip install --index-url https://_json_key_base64:... \
              --extra-index-url https://pypi.org/simple \
              labvault
  ```
  またはユーザー向け簡略コマンド (README 記載のもの)
- [ ] `pip show labvault` で installed version が pyproject.toml と一致
- [ ] `python -c "import labvault; print(labvault.__version__)"` が成功
- [ ] `labvault --version` が同じ version を表示

### 1.2 SDK インストール (ADC モード, Mac/Linux のみ)

- [ ] `gcloud auth application-default login` 済の状態
- [ ] AR repo に reader 権限がある email でログイン
- [ ] `pip install labvault` が AR 認証経由で成功
- [ ] backend を呼ぶ操作 (例: `labvault list`) が ADC 経由で動く

### 1.3 Windows 装置 PC 想定

- [ ] PowerShell で venv 作成 → `.venv\Scripts\Activate.ps1` 通る
- [ ] `pip install labvault` で wheel が取れる (sdist にフォールバックしない)
- [ ] **長いパス対応**: `C:\Users\...\OneDrive\研究\実験\...` のような
      日本語混じり deep path で `lab.new()` → `add()` → 同期が壊れない

### 1.4 doctor

- [ ] `.env` も `~/.labvault/credentials` も無い状態:
  - [ ] `labvault doctor` が `[!!] config` を 1 件報告して exit code != 0
- [ ] PAT を `~/.labvault/credentials` に置く:
  - [ ] `labvault doctor` が `[OK]` 多数 + `mode: PAT` を表示
- [ ] `LABVAULT_PLATFORM_URL` を未設定にする:
  - [ ] `Nextcloud` 行が `[!!]` ではなく `[OK] (direct)` または `[--]`
        どちらが出るか実機確認 (現状仕様の確認)
- [ ] `labvault doctor --json` が valid JSON を吐く (parseable)

---

## 2. CLI (16 コマンド)

各コマンドの `--help` が落ちないことは最低限。基本動作は以下。

### 2.1 CRUD 系

- [ ] `labvault init --team konishi-lab --user <you>` → `.env` 生成
- [ ] `labvault new "QA テスト #1" --type experiment --tag qa`
      → ID が表示される (6 文字 Crockford Base32)
- [ ] `labvault show <ID>` → tag に `qa` が含まれる
- [ ] `labvault list -t qa` → 上で作った record が含まれる
- [ ] `labvault tag <ID> --add reviewed --remove qa`
- [ ] `labvault note <ID> "QA 中"` → notes が増える
- [ ] `labvault delete <ID>` → ソフトデリート
- [ ] `labvault restore <ID>` → 復活
- [ ] `labvault delete <ID> && labvault list -t reviewed` で消えている

### 2.2 検索系

事前に異なる template / conditions の record を 5〜10 件作っておく。

- [ ] `labvault search "QA"` で部分一致が効く
- [ ] `labvault search -c "power>=50"` 範囲指定が効く
- [ ] `labvault search -C` で conditions も併記される
- [ ] `labvault aggregate power -p <PARENT>` 数値統計が出る
- [ ] `labvault overview <PARENT>` で子レコード数 + 条件サマリが出る

### 2.3 ステータス / 同期 / Export

- [ ] `labvault status` で sync 状況が表示
- [ ] `labvault export <ID> --out /tmp/x.json` で JSON が書き出される
- [ ] `labvault doctor` が全項目 `[OK]` (PAT モード前提)

---

## 3. SDK (Python / Notebook)

### 3.1 Jupyter Notebook (ローカル)

- [ ] `jupyter lab` (or `jupyter notebook`) を起動
- [ ] cell 1 で `from labvault import Lab; lab = Lab(); exp = lab.new("nb-1")`
- [ ] cell 2 で計算 (例: `import numpy as np; x = np.linspace(0, 1, 100)`)
- [ ] cell 3 で `exp.conditions(power=10, freq=1000)`
- [ ] cell 4 で `exp.results["max_x"] = float(x.max())`
- [ ] cell 5 で `exp.status = "success"`
- [ ] `labvault show <exp.id>` で:
  - [ ] conditions に power=10, freq=1000 が入っている
  - [ ] results に max_x が入っている
  - [ ] cell_logs に 5 セル分が記録 (`labvault show <id> --cells`)
- [ ] **セル再実行の冪等性**: cell 3 を再実行しても conditions が
      重複しない (上書き)
- [ ] **既存 record への追記**: 別 notebook で
      `lab.get(<exp.id>, auto_log=True)` → 新セル → cell_logs に append される

### 3.2 装置制御スクリプト (.py)

- [ ] `examples/02_instrument_script.py` を実行
- [ ] `exp.log_value("temperature", 23.4)` → events に書かれる
- [ ] `exp.log_event("laser_on")` → events に書かれる
- [ ] **長時間運転**: 30 分以上回したスクリプトでも、Buffer の
      `daemon thread` が落ちずに sync し続ける

### 3.3 大きいデータ

- [ ] `exp.save("big.npy", np.zeros((10_000, 10_000)))` (~800 MB)
      が完走、Nextcloud に upload される
- [ ] `exp.get_data("big.npy")` で取り戻せて shape が一致
- [ ] アップロード中に Ctrl+C → 中断、再開で続きが流れる (buffer 効果)

---

## 4. MCP サーバー (Claude Desktop / Claude Code)

### 4.1 Claude Desktop

- [ ] `~/.config/Claude/claude_desktop_config.json` (Mac) or
      `%APPDATA%\Claude\claude_desktop_config.json` (Win) に
      `"labvault": { "command": "labvault", "args": ["mcp"] }` が入っている
- [ ] Claude Desktop 再起動後、`mcp__labvault__*` ツールが見える
- [ ] Claude に「最近の実験を 3 件教えて」 → `search` が呼ばれて結果が返る
- [ ] 「ID `XXXXXX` の詳細を見せて」 → `get_detail` が呼ばれる
- [ ] 「target が Cu の実験」 → `search` の `conditions={"target": "Cu"}`
      で実際に push down される (Cloud Console の Firestore audit log で確認)
- [ ] 「power を集計して」 → `aggregate` が呼ばれる
- [ ] 「この親 ID 下の実験まとめて」 → `get_overview` が呼ばれる
- [ ] 7 ツール (search / get_detail / compare / data_preview / aggregate /
      get_overview / get_timeline) すべてに対応する自然言語クエリを各 1 回叩く

### 4.2 Claude Code

- [ ] `.mcp.json` をプロジェクトに置く (内容は Desktop と同じ schema)
- [ ] `claude mcp` で labvault が登録されている
- [ ] チャット中に上記 7 ツールが呼べる

### 4.3 エラー応答

- [ ] 存在しない ID で `get_detail` → 404 相当のエラーが返り、
      Claude が説明してくれる (ツールが silent fail しない)
- [ ] PAT を無効化した状態で MCP を起動 → "認証エラー" が即時返る
      (タイムアウトまで待たされない)

---

## 5. Web UI (`platform/frontend`)

### 5.1 認証フロー

- [ ] **Google ログイン (個人 gmail)**: ログイン → `/welcome` 直行
- [ ] **Google ログイン (Workspace アカウント)**: 同上
- [ ] **Email/password サインアップ**:
  - [ ] パスワード弱 → エラーメッセージが日本語で表示
  - [ ] 新規 → `/welcome` の **申請フォーム** に飛ぶ
  - [ ] 申請 → admin 承認 → ログインし直し → `/` (Dashboard)
- [ ] **既存ユーザーで再ログイン**: 直接 `/` に到達 (Welcome 飛ばない)
- [ ] **ログアウト**: header の user menu → ログアウト → `/welcome`
      (anonymously) に戻る

### 5.2 Dashboard `/`

- [ ] greeting に user.displayName が表示 (Google なら本名、email なら local part)
- [ ] team 名が表示
- [ ] QuickLink 4 つ (records / トークン / 装置 PC 手順 / ユーザー管理) が表示
  - [ ] super-admin / team-admin の場合のみ「ユーザー管理」が見える
  - [ ] member は「ユーザー管理」リンクが見えない
- [ ] 「最近のレコード」5 件が新しい順に並ぶ
- [ ] 「すべて見る →」で `/records` に遷移

### 5.3 `/records` 一覧

- [ ] テーブルに最新 50 件 (or 設定値) 表示
- [ ] 並び順 (created_at / updated_at / title) ソート切替が効く
- [ ] 検索バー: テキスト検索が `/api/search` (vector) を呼ぶ
- [ ] **条件 chip**:
  - [ ] 「条件名」入力欄を focus → datalist で template の `indexed_fields`
        候補 (target / sample_name / method / mode / measurement_mode /
        laser_wavelength_nm) が表示
  - [ ] `target=Cu` 追加 → URL が `?conditions={"target":"Cu"}` になり
        テーブルが絞り込まれる
  - [ ] chip の「×」で外せる
  - [ ] ブラウザ「戻る」で chip 操作の履歴が辿れる (URL 同期されているため)
  - [ ] indexed_fields にない key (例: `power`) を入力しても add できる
        (post-filter 経由)

### 5.4 `/records/{id}` 詳細

- [ ] タイトル / 条件カード / 結果カード / タグ / メモ / 子レコード一覧
      が表示
- [ ] 条件カードの単位編集が効く
- [ ] タグ追加・削除 → 即時反映 + リロード後も維持
- [ ] メモ追加 → 即時反映
- [ ] 子レコードがあれば散布図 (scatter chart) が出る
  - [ ] X / Y 軸切替が効く
  - [ ] 点を hover → tooltip
  - [ ] 点を click → 該当子 record に遷移
- [ ] ファイル一覧
  - [ ] CSV プレビュー (テーブル表示)
  - [ ] JSON プレビュー
  - [ ] テキストプレビュー
  - [ ] 画像 / PNG プレビュー
  - [ ] バイナリ (大きい .npy) は「ダウンロード」のみで preview しない

### 5.5 一括アップロード (`/records/{id}` の bulk upload)

- [ ] NxM グリッドでファイルをドロップ → 親 record の子として一括作成
- [ ] グリッドの行・列ラベルが各子 record の conditions に入る
- [ ] 1 件失敗しても他は完走 (atomic ではない)
- [ ] 重複ファイル (同名 + 同 hash) は skip される

### 5.6 `/account/tokens`

- [ ] 「新規発行」ボタン → ダイアログで名前入力 → token (`lv_***`) 表示
- [ ] token 文字列はその場でしか見えない (再表示不可) ことが UI で明示
- [ ] 一覧に発行済 token がメタデータだけで表示 (生 token は無い)
- [ ] 「失効」ボタン → 即時 revoke、一覧の状態が「revoked」になる
- [ ] revoke 後の token で SDK を叩く → 401 / 403 が返る

### 5.7 `/admin/pending` (super-admin)

- [ ] member でアクセス → 403 / redirect
- [ ] team-admin でアクセス → 403 / redirect
- [ ] super-admin でアクセス → pending リスト
- [ ] 承認: action=assign + 既存 team で承認 → 該当 user が allowed_users に入る
- [ ] 承認: action=create_team で新 team 作成 + assign
- [ ] AR grant が成功すれば「AR: granted」、失敗で「AR: failed」表示

### 5.8 `/admin/users`

- [ ] super-admin → 全 team の全 user が見える
- [ ] team-admin → 自 team に所属する user のみ、各 user の teams[] は
      自 team だけが見える (他 team は隠れる)
- [ ] member → 403
- [ ] UserCard の「無効化」(super-admin のみ) → AR revoke + DB active=false
- [ ] 「team を追加」/「team を外す」UI が team-admin の権限内で動く

---

## 6. クロス機能 (E2E シナリオ)

### 6.1 装置 PC → Web UI まで一気通貫

- [ ] Windows 装置 PC で venv + PAT 設定
- [ ] `examples/02_instrument_script.py` 改変で実装置データを 1 件投入
- [ ] 数秒以内に Mac の Web UI `/records` で見える
- [ ] `/records/{id}` で詳細が見える
- [ ] CSV プレビューが動く

### 6.2 Notebook → MCP → CLI

- [ ] Notebook で 5 件作成
- [ ] Claude Desktop に「最近の 5 件まとめて」→ 5 件のサマリが返る
- [ ] CLI で `labvault list -n 5` でも同じ 5 件が見える

### 6.3 セッション切替 (多 team)

- [ ] 2 つ以上の team に所属するユーザーで:
  - [ ] header の team selector が出る
  - [ ] team を切替 → Web UI の records 一覧が切り替わる
  - [ ] CLI で `--team teamB` を渡せば backend がそちらの team を見る

---

## 7. パフォーマンス / 大きいデータ

各環境で「OK」かを記録。明確な数値しきい値より、「実用上ストレスがないか」
の主観評価で十分 (定量計測は別タスク)。

- [ ] `/records` を 1000 件 record の team で開く → 初回 < 3 秒
- [ ] 条件 chip 追加 → 結果更新 < 1 秒
- [ ] 散布図: 500 点 / 5000 点でカクつかないか
- [ ] 一括アップロード 50 ファイル → 完走 < 1 分 (回線次第)
- [ ] SDK `lab.search(query, limit=100)` → < 2 秒
- [ ] CLI `labvault list -n 100` → < 2 秒

---

## 8. 異常系 / セキュリティ

### 8.1 ネットワーク / 認証

- [ ] Wi-Fi OFF 中に `exp.add(...)` → SQLite Buffer に蓄積、
      Wi-Fi ON で自動 sync
- [ ] PAT 期限切れ → SDK が認証エラーを raise (silent fail しない)
- [ ] Firebase token 期限切れ (Web UI で 1 時間放置) → 自動 refresh される
- [ ] backend が 5xx 中の SDK 操作 → リトライ / バッファに残る / ユーザーに通知
      のどれが起こるか実機確認 (現状仕様の確認)

### 8.2 認可境界 (PR #21 でテスト済だが UI レベルで再確認)

- [ ] member ロールで `/admin/users` URL を直叩き → 403 ページ
- [ ] team-admin (teamA) で teamB のユーザー詳細を URL 直叩き
      → 表示されない / 403
- [ ] team-admin で他 team の team 追加 / 削除 API を叩く → 403

### 8.3 入力

- [ ] 日本語 record タイトル: 「液体窒素温度での XRD 測定 #3」が壊れない
- [ ] **絵文字** record タイトル: 「測定🎯」がデータベース round-trip
- [ ] 4 byte UTF-8 (絵文字、漢字外字) を含むメモが化けない
- [ ] 改行を含むメモが UI で改行表示される
- [ ] 巨大文字列 (100 KB のメモ) を put しても backend が落ちない

### 8.4 ファイル名

- [ ] 半角スペースを含む `my data.csv`
- [ ] 日本語ファイル名 `測定結果.csv`
- [ ] 100 文字超のファイル名
- [ ] `..` を含む path traversal な name → 拒否される
- [ ] ZIP 爆弾的に大量小ファイル (1000 個の 1 KB ファイル) → 完走 or
      明示エラー (silent hang しない)

---

## 9. クロスブラウザ (Web UI のみ)

最低限 Chrome、リリース前は 4 ブラウザ通す。

- [ ] **Chrome** 最新: 全機能 OK
- [ ] **Safari** (macOS): Firebase auth が popup でちゃんと動く
      (Safari は popup blocker が辛い)
- [ ] **Firefox**: 散布図の SVG が崩れない
- [ ] **Edge** (Windows): IE 互換モードで開かれていない
- [ ] **モバイル** (iOS Safari): `/records` 一覧が縦スクロールで読める
      (詳細は responsive 未対応かも、最低限「壊れていない」を確認)

---

## 10. アップグレード / マイグレーション

新 version リリース時の互換性確認。

- [ ] 旧 version で作った record を新 version で読める
- [ ] 旧 version で作った PAT が新 version でも動く
- [ ] `lv_*` 形式の token が変わらない
- [ ] `~/.labvault/buffer/*.db` (SQLite WAL) のマイグレーションが必要
      なら schema migration が走る、不要なら何もしない (落ちない)
- [ ] 旧 record の `template_name` が空でも `_to_dict` が落ちない
      (PR #11 以降の `idx_*` 生成で `None` 周りの edge case を再確認)

---

## 記入欄テンプレート

実施結果は `docs/qa_results/YYYY-MM-DD_release-vX.Y.Z.md` に切り出して保管。

```markdown
# QA 実施記録 vX.Y.Z

## 環境
- 日付: 2026-XX-XX
- 担当: @your-name
- OS: macOS 15.x
- Python: 3.12.x
- ブラウザ: Chrome 1XX

## 結果
- [x] 1.1 SDK インストール (PAT) — OK
- [x] 1.2 SDK インストール (ADC) — OK
- [ ] 1.3 Windows 装置 PC — skip (環境なし、別担当)
- [ ] 5.5 一括アップロード — NG (issue #XX を起票)

## メモ
- 5.5 で 50 ファイルアップロード時に 12 件目から進捗バーが固まる
- ...
```

---

## 運用メモ

- このリストは **網羅性より「触りに行く動機」を作る道具**。
  全部やらずに「今日は §3 と §5 だけ」のような部分実施でも価値あり。
- バグを見つけたら GitHub issue に切る → このファイルの該当チェックボックスは
  そのまま残し、issue リンクをメモする
- 「これ毎回確認するのダルい」と感じる項目は、自動テストに昇格させる候補
  (例: §8.3 入力系は SDK ユニットテストで網羅できる)
