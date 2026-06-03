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

未承認の新規ユーザー向け体感確認は backlog #5 (人間オペレータ案件) を参照。
ここでは **承認済ユーザーが新しい環境にセットアップする** ケース。

認証方式の選び方:

| 環境 | 推奨 | 備考 |
|---|---|---|
| Mac / Linux 開発機 / Notebook | **ADC** | 監査ログが個人 Google アカウントと紐付き、token 流出時の被害が小さい。組織側で一括失効可。`gcloud` が前提 |
| Windows 装置 PC (gcloud 不可) | PAT | gcloud が入らない環境向けの代替 |
| CI で Workload Identity / SA | ADC (SA) | 同上、SA で |
| CI で gcloud が立たない | PAT | 同上 |

以下、§1.1〜1.3 が **ADC 経路 (推奨)**、§1.4〜1.6 が **PAT 経路
(装置 PC / CI 等)**。§1.7 doctor は両方で確認する。

### 1.1 ADC: pip install (Mac / Linux)

承認済 Google アカウント (Artifact Registry reader 権限あり) で
`gcloud auth application-default login` を済ませた状態から:

```bash
# clean venv
python -m venv .venv && source .venv/bin/activate

# 一度だけ: GCP 認証 (Artifact Registry にアクセスする Google アカウント)
gcloud auth login
gcloud auth application-default login

# AR 認証 helper (これが無いと pip が AR の credentials を取れない)
pip install keyring keyrings.google-artifactregistry-auth

# labvault 本体
pip install \
  --extra-index-url https://asia-northeast1-python.pkg.dev/klab-laser-process/labvault-pypi/simple/ \
  "labvault[all]"
```

- [ ] `pip show labvault` の version が pyproject.toml と一致
- [ ] `python -c "import labvault; print(labvault.__version__)"` 成功
- [ ] `labvault --version` が同じ version を表示

### 1.2 ADC: pip install (Windows / PowerShell)

PowerShell で同じ手順。改行は `` ` `` (バックティック)、角括弧はクオート
が必要。

```powershell
# clean venv
python -m venv .venv
.venv\Scripts\Activate.ps1

# 一度だけ: GCP 認証
gcloud auth login
gcloud auth application-default login

# AR 認証 helper
pip install keyring keyrings.google-artifactregistry-auth

# labvault 本体
pip install `
  --extra-index-url https://asia-northeast1-python.pkg.dev/klab-laser-process/labvault-pypi/simple/ `
  "labvault[all]"
```

- [ ] `.venv\Scripts\Activate.ps1` の実行ポリシー (Set-ExecutionPolicy) で
      止められないか確認 (止められたら `-ExecutionPolicy Bypass` で
      起動 or RemoteSigned を user スコープで許可)
- [ ] `pip install` で **wheel** が取れる (sdist にフォールバックしない)。
      ログに `Downloading labvault-X.Y.Z-py3-none-any.whl` が出るか

### 1.3 ADC: SDK ランタイム認証

カレントディレクトリの `.env`:

```bash
LABVAULT_TEAM=konishi-lab
LABVAULT_USER=your-name
# 0.2.2 以降、gcp_project / firestore_database / platform_url /
# nextcloud_url / nextcloud_group_folder は SDK 同梱 default で動く。
# 別 GCP project や別研究室に向けたいときだけ env で上書きする。
```

- [ ] `labvault doctor` で `mode: Direct mode` か `Mixed mode` と表示
- [ ] `type(lab._metadata).__name__` が `FirestoreMetadataBackend`
- [ ] `labvault list` が空でも 200 で返る (例外を吐かない)
- [ ] 試しに作った record を Web UI で確認できる
- [ ] ADC 期限切れ時に挙動が安定 (`labvault list` がはっきりした
      エラーメッセージで落ちる、フリーズしない)

### 1.4 PAT: Web UI で発行 (装置 PC / CI 等)

ブラウザで Web UI を開く: <https://labvault-web-355809880738.asia-northeast1.run.app>

- [ ] ログイン → 右上のヘッダー or Dashboard QuickLink で
      **「API トークン」 (`/account/tokens`)** に移動
- [ ] **ラベル必須** (PR #28 で必須化): 「装置 PC: XRD A 号機」など
      識別可能な名前を入れる
- [ ] 「発行」を押す → `lv_xxxx...` が表示される。**この画面を離れると
      再表示できない** ので必ずコピー or 安全な場所にメモ
- [ ] 発行成功カードに pip install サンプル + credentials サンプルが
      埋め込み表示される (PR #32)

### 1.5 PAT: pip install (gcloud 不要)

PyPI proxy (PR #31) 経由で同じ PAT で install できる。

**Mac / Linux**:

```bash
PAT=lv_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
PROXY=https://__token__:${PAT}@labvault-api-355809880738.asia-northeast1.run.app/api/pypi/simple/

python -m venv .venv && source .venv/bin/activate
pip install \
  --index-url https://pypi.org/simple/ \
  --extra-index-url "${PROXY}" \
  "labvault[all]"
```

**Windows (PowerShell)**:

```powershell
$env:PAT = "lv_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
$PROXY = "https://__token__:${env:PAT}@labvault-api-355809880738.asia-northeast1.run.app/api/pypi/simple/"

python -m venv .venv
.venv\Scripts\Activate.ps1
pip install `
  --index-url https://pypi.org/simple/ `
  --extra-index-url "$PROXY" `
  "labvault[all]"
```

- [ ] gcloud / keyring_helper を入れずに install できる
- [ ] **wheel** が取れる (sdist にフォールバックしない)
- [ ] **長いパス対応 (Windows)**: `C:\Users\...\OneDrive\研究\実験\...` の
      ような OneDrive 同期下 + 日本語混じり deep path で `lab.new()` →
      `add()` → buffer 同期が壊れない
- [ ] Windows Defender / Antivirus 除外 (`.venv` 配下) で pip が極端に
      遅くなっていないか

### 1.6 PAT: SDK ランタイム認証

`labvault auth set-token` で 1 行設定。OS 差分 (chmod / icacls) と
backend verify を CLI 側で吸収する。

```bash
# Mac / Linux / Windows 共通。--token-stdin で shell 履歴に残らない:
echo "lv_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" | labvault auth set-token --token-stdin

# 装置 PC では識別子を付ける:
echo "$PAT" | labvault auth set-token --token-stdin --user instrument-xrd-1
```

- [ ] `labvault auth status` で credentials 内容が表示される (token は伏字)
- [ ] `labvault doctor` で `mode: PAT mode` が表示される
- [ ] `python -c "from labvault import Lab; lab = Lab();
      print(type(lab._metadata).__name__)"` が `PlatformMetadataBackend`
      を返す
- [ ] 試しに作った record を Web UI で確認できる
- [ ] PAT を revoke した後に `labvault list` が即座に 401 で失敗する
      (発行画面 → 失効ボタン → 別シェルで実行)

### 1.7 doctor

- [ ] `.env` も `~/.labvault/credentials` も無い状態:
  - [ ] `labvault doctor` の末尾「次のステップ:」が **「推奨は ADC」+
        装置 PC 向け PAT 代替** の両案内を出す (PR #33)
- [ ] ADC 設定済 (LABVAULT_GCP_PROJECT セット):
  - [ ] `[OK] GCP project: ...` + `mode: Direct mode` or `Mixed mode`
  - [ ] 「次のステップ」は動作確認 1-liner のみ
- [ ] PAT 設定済:
  - [ ] `[OK] PAT: configured` + `mode: PAT mode`
- [ ] PAT と GCP project の両方ある (Mixed):
  - [ ] 「次のステップ」に「ADC のみに寄せる方が推奨」の警告
- [ ] 凡例の `[OK] / [--] / [!!]` 1 行が末尾に出る (PR #26)

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

---

## 11. 自動 QA セットアップ (ローカル)

2026-06-02 の round-2 QA で得た知見をベースに、Playwright で踏み込んだ
観察ができる起動構成を 1 セットにまとめた。本番 Firestore に少しだけ
接続するので注意事項も合わせて。

### 11.1 backend (dev_skip + 本番 Firestore)

```bash
cd platform/backend
env $(grep -v '^#' /Users/.../labvault/.env | xargs) \
  LABVAULT_DEV_SKIP_AUTH=1 \
  LABVAULT_CORS_ORIGINS="http://localhost:3765" \
  uvicorn app.main:app --port 8765 --no-access-log
```

- `LABVAULT_DEV_SKIP_AUTH=1` で `/api/auth/me` だけ Firestore を引かず
  固定の admin / konishi-lab を返す ([§3.1 / PR #26](#3-web-ui-frontend))
- `LABVAULT_CORS_ORIGINS` に frontend dev port を追加 (default は
  `localhost:3000` のみ)。`.env` 注入手順は
  `platform/backend/CLAUDE.md` に書いてある。
- それ以外の handler (records / admin) は **依然として本番 Firestore に
  接続する** ので、dev 中の操作が本番に反映されることに注意。
  特に `POST /api/auth/tokens` は dev_skip では 403 で塞いだ (PR #28)。

### 11.2 frontend (dev_skip)

```bash
cd platform/frontend
NEXT_PUBLIC_API_URL=http://localhost:8765 \
NEXT_PUBLIC_DEV_SKIP_AUTH=1 \
npx next dev --port 3765
```

- `NEXT_PUBLIC_DEV_SKIP_AUTH=1` で `AuthProvider` が Firebase に
  一切触らず `dev@local` (admin / konishi-lab) を context に注入する
  (PR #27 で導入)。
- 本番 build では env を立てないこと (`next build` 時に bundle される)。

### 11.3 Playwright で踏み込む

- [ ] `http://localhost:3765/` で Dashboard が出る
- [ ] header に「申請承認」「ユーザー」が出る (dev は admin 扱い)
- [ ] `/records` の検索バーが `/records?q=...` に遷移する (§12.1.1)
- [ ] `/account/tokens` で「発行」ボタンを押すと **403 が返る** (PR #28)。
      レスポンス body の文言に "dev_skip" が入っているか確認
- [ ] `← 戻る` ボタンが history.back の挙動 (PR #28)
- [ ] 空 record (条件・結果・ファイル・子なし) で破線カード「未投入です」
      表示 (PR #28)

### 11.4 注意事項

- **本番 Firestore に書き込まれ得る操作**:
  - 条件・結果・タグ・メモ編集
  - tag 追加 / 削除
  - admin の team add/remove、ユーザー無効化
  - 一括アップロード (Nextcloud にもファイルが上がる)
- これらは原則 dev_skip 中は触らないこと。読み取りのみで観察する。
- やむを得ず触る場合は対象 record を `[smoke-test]` 等の prefix で
  作成し、QA 終了後に削除する。

---

## 12. 過去所見の追跡 (round-1 → round-2 で見つかったもの)

各項目の最後に **修正状態** を記す:
- ✅ = 修正済 (PR # 記載)
- 🟡 = 修正済だがフォロー要
- 🔵 = backlog / 設計議論待ち
- ❌ = 未対応

### 12.1 round-1 (2026-06-02 午前)

| 所見 | 状態 |
|---|---|
| §3.2 invalid Authorization で 500 (実は dev_skip + Firestore 不可) | ✅ PR #26 (`auth_me` に dev_skip ガード) |
| §3.3 CORS default が `localhost:3000` 固定 (docs に未記載) | ✅ PR #26 (CLAUDE.md に env table 追記) |
| §1.5 `labvault doctor` の `[--]` 凡例が分かりにくい | ✅ PR #26 (出力末尾に凡例を追加) |
| §3.4 ヘッダー「レコード」リンクが未ログインでも押せる | 🔵 設計議論 (今は AuthGate で内側だけ block) |
| §3.5 ログアウト後も form に email/password が残る | 🔵 (autocomplete 適正化要、未着手) |
| §3.7 `/welcome` 永続 URL を未ログインで踏むと login form | 🔵 設計議論 |
| §1.1 `labvault init` に PAT / platform URL オプション無し | 🔵 backlog |
| §1.3 各 CLI サブコマンドの `--help` が薄い | ❌ |
| §1.2 `-t` / `-T` の慣習違い | 🔵 (破壊的変更注意) |

### 12.2 round-2 (2026-06-02 午後、frontend dev_skip 投入後)

| 所見 | 状態 |
|---|---|
| §1.1 `/records` 検索バーが `/?q=` に飛んで結果が出ない (Critical) | ✅ PR #28 |
| §3.2 dev_skip で token 発行すると本番 Firestore に dev@local 名義 (Critical) | ✅ PR #28 (backend 403 ガード) |
| §2.1 条件値の単位二重表示 (`10 deg`) (Major) | ✅ PR #28 |
| §3.1 token 発行ラベル空で「(無題)」 (Major) | ✅ PR #28 |
| §1.4 タイトル超長文で横スクロール (Major) | ✅ PR #28 (truncate + tooltip) |
| §1.3 一覧の日付に年なし (Minor) | ✅ PR #28 (`2024/11/17`) |
| §5.1 「← 一覧」が Records 固定 (Minor) | ✅ PR #28 (`BackButton` + history.back) |
| §2.2 子なし record で空白表示 (Minor) | ✅ PR #28 (案内カード) |
| **§4.2 destructive action に確認なし** (Minor) | ✅ **誤検知** (実は `confirm()` 実装済、Playwright が auto-cancel で snapshot に出なかった) |
| §1.2 record ID 桁数混在 (4/6) | 🔵 視覚整え未着手 |
| §1.5 条件 chip パネル説明文が常時表示 | 🔵 折り畳み未着手 |
| §2.3 「クリックして単位・説明を編集」が tooltip だけ | 🔵 アイコン化未着手 |
| §2.4 / §4.4 status / role が badge 化されていない | 🔵 |
| §4.1 `/admin/pending` 空メッセージが技術寄り | 🔵 |
| §4.3 `default: konishi-lab` 表記が冗長 (1 team のみ) | 🔵 |
| §5.2 header の `Dev User` が clickable に見えない | 🔵 |
| §6.1 dev_skip でも records / admin handler は本番 Firestore を引く (Major DX) | 🔵 InMemoryBackend / read-only モードの検討 |
| §6.2 `.env` が backend dir で読まれない | 🟡 PR #26 で docs 記載済 (実装上の対応は別途) |

---

## 13. 未検証エリア (次回 round)

round-2 で deep dive できなかった画面 / 機能:

- [ ] **散布図 (scatter chart)**: 子レコード持ち record (MDG 移行データの
      `MDG carbide1 kkonishi` 等) で X / Y 軸切替・点 hover tooltip・点
      クリックで子 record に遷移
- [ ] **ファイルプレビュー**: CSV (テーブル表示) / JSON / テキスト /
      PNG / 大きい .npy はダウンロードのみ
- [ ] **一括アップロード** (`/records/{id}` の bulk upload): NxM グリッド
      でファイルをドロップ、グリッドの行・列ラベルが各子 record の
      conditions に入る
- [ ] **multi-team selector**: header の team 切替が出るのは 2 team
      以上に所属するユーザーだけ。実機テスト用に dev_skip でも
      multi-team モードに切替えられる手段が欲しい
- [ ] **welcome 1 回だけ表示**: 新規 user が初回ログインで `welcomed_at`
      が無い → welcome 画面 → 「始める」で push → 2 回目以降は飛ばす
- [ ] **mobile (iOS Safari)**: `/records` 一覧が縦スクロール、詳細
      ページが responsive (現状 desktop only と思われる)
- [ ] **長時間 SDK ワークフロー**: 装置制御スクリプトを 30 分以上回した
      ときの buffer + sync の挙動
- [ ] **同時アクセス**: 2 名が同じ record の condition を同時編集
      した時の race condition (last-write-wins か optimistic locking か)

---

## 14. 次回 round の流れ (推奨)

1. 開発が止まっているタイミングで `LABVAULT_DEV_SKIP_AUTH=1` で
   両 server を起動 (§11)
2. Playwright で §13 の未検証エリアに踏み込む
3. 観察した所見を `docs/qa_findings_YYYY-MM-DD.md` に書き出す
   (深刻度別 + 修正提案)
4. Critical / Major は 1 PR でまとめて修正、Minor / Nit は backlog に
5. 本 checklist の §12 に状態 (✅ / 🟡 / 🔵 / ❌) を更新

「触りに行く動機」を maintain するため、round ごとの実施記録は
`docs/qa_results/YYYY-MM-DD_round-N.md` 等で軽く残すと、次回の重複
作業を減らせる。
