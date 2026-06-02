# 自動 QA 所見 — 2026-06-02

`docs/qa_checklist.md` を手動で通す前に、ローカルで CLI / SDK / Web UI を
動かして見つけたフロー / UX / 開発者体験の引っかかりを書き出す。

実施環境:
- macOS (Apple Silicon)
- Python 3.12.11 / labvault 0.1.2
- 本番 Firestore (konishi-lab) を直叩きする設定
- WebUI は `LABVAULT_DEV_SKIP_AUTH=1` で backend を起動、frontend は
  そのまま (Firebase 認証は通常通り)

深刻度の凡例:
- **Critical**: 機能が動かない / セキュリティ問題
- **Major**: ユーザーが詰まる / 大きな混乱
- **Minor**: 違和感はあるが回避可能
- **Nit**: 細かい改善案

---

## 1. CLI

### 1.1 [Major] `labvault init` に PAT / platform URL のオプションが無い

```
Usage: labvault init [OPTIONS]
Options:
  --team / --user / --nextcloud-* / --gcp-project
```

装置 PC セットアップ (PAT モード) で一番欲しい
`--platform-url` と `--token` が無く、`.env` を手書きしないと
`labvault doctor` が `mode: Direct` のままになる。

**提案**: `--platform-url`, `--token` を追加し、PAT モードを `init` で
完結できるようにする。または PAT 専用の `labvault init-pat` を追加。

### 1.2 [Minor] `labvault search` と `labvault list` の short flag が衝突的

| | search | list |
|---|---|---|
| `-t` | type | type |
| `-T` | tags | tags |

慣習的に「`-t` がタグ」と感じる人が多そう (例: `git tag`, `docker tag`)。
さらに `labvault new` も `-T, --tags` で `-t` は予約。一方 `labvault tag`
は無印 (positional)。**全コマンドで揃っていない**。

**提案**: 全体で `-T tags`, `-t type` で統一されているなら docs に書く。
もしくは `-t` を tags に振り直す (破壊的変更注意)。

### 1.3 [Minor] サブコマンドの `--help` が薄い

```
labvault add --help
Options:
  --help  Show this message and exit.
```

`add` / `note` / `show` / `export` の help が説明文 1 行 + `--help` のみ。
- `add` のファイルは複数指定可能か / 重複時の挙動 (上書き/skip) は?
- `note` の TEXT は改行を含められるか?
- `show` に `--cells` / `--json` 等の切替はあるか?

**提案**: 各コマンドの help に「例」と「振る舞いメモ (冪等、上書き)」を
1〜2 行追加する。Click なら `epilog=` で書ける。

### 1.4 [Nit] `labvault list` に `-c, --conditions` が無い

`search` には conditions フィルタがあるが `list` には無い。同じ
push down (PR #14) を `list` でも使いたいケースがある (UI の絞り込み
chip 相当)。

### 1.5 [Minor] `labvault doctor` の `[--]` の意味が初見で不安

```
[--] config.toml: not present (env / .env / credentials で代替可)
[--] credentials: not present (PAT モードを使う場合のみ必要)
[--] platform URL: not set (direct backend モード)
[--] PAT: not set (ADC を使用)
```

`[--]` が「未設定だが代替で動く」「無くて正常」の意味であることは
括弧書きを読めば分かるが、一見「3 項目欠落?」と読まれる。

**提案**: `[--]` → `[..]` または `[--]` のままで `(info)` ラベルを添える。
あるいは `--verbose` でないと表示しない。

---

## 2. SDK / Python

### 2.1 [Minor] `help(labvault.Lab)` の docstring が薄い

```
>>> help(Lab.__init__)
__init__(self, team=None, *, user=None, metadata_backend=None, ...)
    Initialize self.  See help(type(self)) for accurate signature.
```

class docstring はあるが `__init__` のシグネチャ説明と例が無い。
Notebook ユーザーは `?Lab` や `help(Lab)` で探索するため、ここに最低限
1 例があると親切。

**提案**: `Lab.__init__` に「team は省略すれば `LABVAULT_TEAM` env から」
「PAT を使うなら token を Settings に置く」など 3 行入れる。

### 2.2 [Nit] `examples/02_instrument_script.py` の `simulate_sputtering`

「実際の装置制御スクリプトでは…」のコメントがあるのは良い。ただし
**装置 PC からの import path** が docs / README に明示されていない。
`pip install labvault` 後の典型コードを 1 箇所にまとめた snippet が
欲しい。

---

## 3. Web UI (Frontend)

backend を `LABVAULT_DEV_SKIP_AUTH=1` で起動して `localhost:3765` で
frontend を立てた状態で観察。

### 3.1 [Critical (DX)] frontend に dev_skip 機構が無い

backend は `LABVAULT_DEV_SKIP_AUTH=1` で認証を一切バイパスできるが、
**frontend にはそれに対応する仕組みが無い**。Firebase の login flow を
強制的に踏むので:

- ローカル開発者は Firebase API key を持ち、何らかの test user で
  ログインしないと UI を起動できない
- 結合テスト (Playwright 等) を CI で回す敷居が高い

**提案**: `NEXT_PUBLIC_DEV_SKIP_AUTH=1` (env build-time) で AuthGate
を bypass する開発専用モードを追加。bypass 時は固定の dev user を
context に入れる。本番 build では env が立っていなければ無視。

### 3.2 [Major] CORS error が「実は backend 500」を覆い隠す

`localhost:3765` から API を叩いて CORS で蹴られたが、実は backend が
**`Authorization: Bearer <invalid token>` で 500** を返しており、
FastAPI の `CORSMiddleware` が 500 に origin ヘッダを付けないため、
ブラウザに「CORS error」と表示される。

```
[ERROR] Access to fetch at 'http://localhost:8765/api/auth/me' from origin
'http://localhost:3765' has been blocked by CORS policy: No
'Access-Control-Allow-Origin' header is present on the requested resource.
```

開発者は何時間も CORS 設定を疑うはめになる。

**提案**:
1. `app/auth.py` の `current_authenticated_user` で invalid token は
   401 を返す (500 にしない)。
2. backend に **CORS exception middleware** を入れて、500 でも
   Access-Control-Allow-Origin が付くようにする (FastAPI 公式の手筋あり)。

### 3.3 [Major] ログイン画面の port 既定値が `localhost:3000` 固定

`platform/backend/app/main.py:76-80`:
```python
_default_origins = [
  "http://localhost:3000",
  "http://127.0.0.1:3000",
  "https://labvault-web-...-asia-northeast1.run.app",
]
```

`npx next dev --port 3001` のような並行起動だと CORS で蹴られる。
`LABVAULT_CORS_ORIGINS` で拡張可能だが、**docs に書かれていない**。

**提案**: `platform/backend/CLAUDE.md` および README に
「別 port を使うなら `LABVAULT_CORS_ORIGINS=http://localhost:XXXX` を
立てる」と明示。あるいは `localhost:*` をデフォルト許可。

### 3.4 [Major] ヘッダーの「レコード」リンクが未ログイン状態でも表示・押下できる

未ログインで `/` を開くと:
- main 部分: ログインフォーム (`AuthGate` で blocking)
- header: `labvault` ロゴと「レコード」リンクが表示

「レコード」をクリックすると URL は `/records` に変わるが、表示は
ログインフォームのまま。同じ画面が出てクリック前後で URL だけ変わる
ため「何も起こらなかった?」と感じる。

**提案**:
- 未ログイン時はヘッダーの nav links を隠す or `disabled` 表示
- もしくはクリック時に「先にログインしてください」のトーストを出す

### 3.5 [Major] ログアウト後もログインフォームに前ユーザーの email/password が残る

`qa-test@example.com` でログイン → ログアウト → ログイン画面に戻る
→ メールアドレス欄に `qa-test@example.com`、パスワード欄に `password123`
が**残っている** (ブラウザ標準の autocomplete か、明示的に保持か未確認)。

共用 PC では他人が前回ログイン情報を見れる状態。

**提案**:
- フォーム要素に `autocomplete="off"` (とくにパスワードは
  `autocomplete="new-password"` or `current-password` を意図的に分ける)
- ログアウト時に form を明示的に reset

### 3.6 [Minor] 空欄で「新規登録」を押してもエラー表示が出ない

新規登録タブで全フィールド空のまま submit ボタンを押したが、UI 上は
何も変化なく submit が走らなかった (おそらく HTML5 `required` の
ブラウザ標準 popup が出ているが、Playwright snapshot に映らない)。

**提案**: HTML5 required に頼らず、JS で「必須項目です」を form 内に
表示する。i18n 観点でも自前 message の方が日本語 UI と整合。

### 3.7 [Minor] `/welcome` 永続 URL を未ログインで踏んでも login form

PR #10 で「`/welcome` を永続化」したが、AuthGate の制約で未ログイン
ユーザーは welcome の中身を見られない。Welcome screen に書いてある
「労務管理者連絡先」「PAT 説明」を**未ログインの未承認希望者にも
読ませる**ことが意図なら、AuthGate の例外にする必要がある。

**提案**: `/welcome` を未ログインでも表示可能にする (中身を 2 段階に
分ける: 未ログインでも見える「サービス概要」/ ログイン後だけ見える
「PAT 発行リンク」)。

### 3.8 [Nit] ログイン画面の primary button 配置

3 つの選択肢が縦に並ぶ:
1. Google でログイン (primary)
2. または
3. メールでログイン / メールで新規登録 (横並びタブ)
4. メール+パスワード form
5. ログインボタン / 新規登録ボタン
6. 「新規登録後、管理者の承認が必要です」

新規ユーザーの動線は「メールで新規登録」を押す → form 切替 → 入力 →
ボタン → ?。`/welcome` (申請フォーム) に行くまで何回操作するのか
最初は分からない。

**提案**: 新規ユーザー向けセクションを上に分ける (「初めての方は →
申請ボタン」「既に承認済みの方は ↓」)。

---

## 4. backend / 開発者体験

### 4.1 [Major] invalid Authorization で 500

§3.2 と関連。`Authorization: Bearer <文字列>` でテストすると 500。
ブラウザの CORS error の真因がこれ。

```
$ curl -i -H "Origin: http://localhost:3765" \
       -H "Authorization: Bearer dummy" http://localhost:8765/api/auth/me
HTTP/1.1 500 Internal Server Error
```

**提案**: `current_authenticated_user` を try/except で囲んで、verify
失敗時は `HTTPException(401)` を raise する。500 は内部バグ用に温存。

### 4.2 [Major] CORS middleware が 500 / 401 にヘッダを付けない

FastAPI の `CORSMiddleware` は exception 経由のレスポンスに origin
ヘッダを付けない (既知の挙動)。これも §3.2 の悪さに寄与。

**提案**: starlette の `Middleware` で wrap して exception 経路にも
CORS ヘッダを付与するか、exception handler 内で明示的に付ける。

---

## 5. 共通

### 5.1 [Minor] `examples/` README が古い可能性

`examples/README.md` を読み比べて、最新の `Lab(team=...)` 初期化
記法 / PAT モード / template 機能が反映されているか確認 (本 QA では
未確認、別途追跡)。

### 5.2 [Major] `LABVAULT_DEV_SKIP_AUTH=1` でも `current_user` 経由で
固定 dev user (`dev@local`) が返るため、admin 系のテストはできるが、
`current_authenticated_user` 経路 (`/api/auth/request-access`) は
バイパスされない。frontend dev_skip と組合せたときに「申請フォーム」
シナリオが手動でしか試せない。

**提案**: §3.1 と合わせて、frontend dev_skip と backend dev_skip の
両モードを揃える。

---

## 推奨アクション (優先順)

### 直近 1 PR で済む系
1. **invalid Authorization で 401 を返す** (§3.2, §4.1) — 1 行で済む可能性
2. **frontend に dev_skip 機構** (§3.1, §5.2) — ローカル開発と E2E
   テストの敷居を下げる
3. **ログアウト時に form reset + `autocomplete="new-password"`** (§3.5)

### docs 更新のみ
4. **`LABVAULT_CORS_ORIGINS`** を `platform/backend/CLAUDE.md` に追記 (§3.3)
5. **CLI 各サブコマンドの help に例** を追加 (§1.3)
6. **`labvault doctor` の `[--]` 凡例** を末尾に表示 (§1.5)

### 設計議論
7. `/welcome` を未ログインでも見せるか (§3.7)
8. ヘッダー nav の未ログイン挙動 (§3.4)
9. `labvault init` の PAT サポート (§1.1)

---

## 未確認 / 続きの QA で見たい所

frontend dev_skip がなく深く入れなかったため、以下は次回:

- Dashboard `/` の表示内容 (QuickLink、最近のレコード)
- `/records` の検索 chip
- `/records/[id]` の散布図 / プレビュー
- `/account/tokens` の token 発行 + 失効
- `/admin/pending` の承認フロー
- `/admin/users` の team admin restrict_to の UI 露出
- 一括アップロード
