# 自動 QA 所見 (深掘り編) — 2026-06-02 round 2

PR #26 で `auth_me` の dev_skip ガード、本 PR (前段) で frontend dev_skip
機構が入ったので、Playwright で Web UI を実際に触って観察した結果。

実施環境:
- backend: `LABVAULT_DEV_SKIP_AUTH=1` + `.env` から `LABVAULT_GCP_PROJECT=
  klab-laser-process` 等を経由 (本番 Firestore に接続)
- frontend: `NEXT_PUBLIC_DEV_SKIP_AUTH=1`
- 固定 dev user: `dev@local` (admin / konishi-lab)
- Playwright MCP (Chromium)

凡例: **Critical** / **Major** / **Minor** / **Nit**

---

## 1. レコード一覧 / 検索

### 1.1 [Critical] `/records` の検索バーが `/?q=` に飛んで結果が出ない

`/records` ページ右上の検索バーで `XRD` を submit すると、URL が
`/records?q=XRD` ではなく **`/?q=XRD` (= Dashboard)** に遷移する。
Dashboard は「最近のレコード 5 件」しか出さないので、検索結果はどこにも
表示されない。

検索コンポーネント (`SearchBar`) が遷移先を hardcode しているか、
`router.push("/")` で書いている可能性。

**提案**: 検索 submit 時の遷移先を `/records?q=...` に固定 (または現在の
パスを保ったまま query を追加)。

### 1.2 [Major] レコード ID の桁数が混在 (`ZQP3` 4文字 vs `BDNPQS` 6文字)

CLAUDE.md には「Crockford's Base32 (6 文字)、既存の 4 文字 ID との互換あり」
とあるが、UI には桁数の説明がない。4 文字 ID をクリックすると詳細に
遷移できるので機能上の問題はないが、`code` 列の幅が揃わずテーブルが
凸凹になる。

**提案**: テーブルの ID 列を等幅 + 6 文字以上に固定幅で割付け。

### 1.3 [Minor] 一覧の日付フォーマットが「11月17日 13:09」(年なし)

タイトルだけ見ても何年のレコードか分からない。`2024-11-17 13:09` のように
ISO 風 (もしくは「2024/11/17」) で表示する方が分かりやすい。

### 1.4 [Minor] タイトルが長すぎてテーブルが横スクロール状態

`35fs_300mW_100kHz_lasor_processing_zP_b: 35fs 300mW 100kHz` のような
長文タイトルが折り返さずに 1 行表示。横スクロールが必要。

**提案**: タイトル列に `max-width` + `truncate` (省略記号) を適用、
ホバーで全文 tooltip。

### 1.5 [Minor] 条件 chip パネルの説明文が常時表示

「候補は template の indexed_fields です。これらの key は Firestore に
push down されて高速に絞り込まれます…」という説明が、テーブルの上に
常に表示されている。chip を 1 度も使わないユーザーには邪魔。

**提案**: アコーディオン or `?` アイコンの tooltip にする。

### 1.6 [Nit] 「条件名 (候補から選択)」の datalist 動作確認できず

Playwright snapshot では `<datalist>` の中身が見えなかったので、フォーカス
時に候補が出るかは未確認。手動 QA で要再検証。

---

## 2. レコード詳細

### 2.1 [Major] 条件の値表示で単位が二重に出る

`P2BV1M` の条件:
```
two_theta_start_deg [deg]   10deg
two_theta_end_deg   [deg]   80deg
```

ラベルに `[deg]` が、値に `10deg` (=「10」+「deg」) と単位が二重表示。
backend が `value=10.0, unit="deg"` で保存しているが、UI が `${value}${unit}`
で連結しているため。

**提案**: 値表示は `{value}` だけにする (ラベルの `[deg]` で単位を示す)。
もしくは `${value} ${unit}` のように **半角スペースで分離**。

### 2.2 [Minor] 子なし record で「子レコード」セクションが消える (空 state なし)

`4VGTKC` (analysis:analyze_crater) を開くと条件・結果・子レコード・
ファイル・イベントの全カードが見えなくなり、基本情報とメモだけが残る。
「データなし」「ファイルなし」の **明示が無い** ため、ユーザーは「読み込み
失敗?」と疑う可能性。

**提案**: 空でも各カードを残し、「データなし」表示を出す。

### 2.3 [Minor] 「クリックして単位・説明を編集」が条件行ホバーで tooltip

条件行のどこをクリックすると編集モードに入るのかが、tooltip 表示でしか
分からない。アイコン (`✎`) を行末に出すと操作可能性が一目で分かる。

### 2.4 [Nit] heading 横の status 表示が文字のまま

「[smoke-test] M3 template venv」の隣に `success` 文字が並ぶ。badge style
(緑背景に白文字など) にすると視認性が上がる。

---

## 3. Token 画面 (`/account/tokens`)

### 3.1 [Major] ラベル空でも発行できて「(無題)」になる

何の検証もなく発行ボタンが押せて、一覧に「(無題)」として並ぶ。後で
revoke する時にどれが何の用途か分からなくなる。

**提案**: ラベル必須にする (button disable + 「ラベルを入力してください」
hint)。または placeholder の「例: 装置 PC, ノート PC, CI」に default 値を
入れる。

### 3.2 [Critical (DX)] dev_skip でトークン発行すると **本番 Firestore に dev@local 名義で書かれる**

ローカル開発で気軽に「発行」ボタンを押すと、本番 Firestore の `tokens`
collection に `dev@local` 名義で永続化される。`/account/tokens` で
revoke しても dev@local の history は残り、`scripts/ar_backfill.py` などの
他スクリプトに混入する可能性。

**提案**:
- dev_skip 時は token 発行 API も dev_skip 分岐させて、Firestore に
  書き込まず in-memory に留める
- もしくは dev_skip 時は UI で「これは dev モードです。発行できません」
  と明示する

**今回 QA で発行した dev token はそのまま残しているので、後で revoke
が必要** (`lv_mcauceon4vqsfgzc7l64p7rtxmsw753h5te7iu7dsmv3rvmy5rzq` を
本番で revoke)。

### 3.3 [Nit] 「← 一覧」ボタンが Records list に戻る

Token 画面は Dashboard 系の機能なので、戻り先は「← Dashboard」の方が
意味が通る。Records list と並列の機能ではない。

---

## 4. Admin 画面

### 4.1 [Minor] `/admin/pending` の空 state 説明が技術寄り

```
ユーザーが /api/auth/request-access を叩くとここに表示されます。
```

API endpoint を直接書いているが、admin が見るメッセージなので
「Welcome ページから申請があると…」のような UX 言い回しの方が自然。

### 4.2 [Minor] `/admin/users` の「Remove konishi-lab」「ユーザーを無効化」ボタンに確認なし

破壊的操作なのに confirm modal や赤色 accent が見えない。誤クリック
リスクあり。

**提案**:
- 確認モーダル (「○○ さんを teamA から外しますか?」)
- 「ユーザーを無効化」を destructive variant (赤系) にする
- 押した時に inline undo (`Snackbar` 系) が出てもよい

### 4.3 [Minor] 「default: konishi-lab」が team 1 つしかないユーザーで冗長

team が複数あるユーザーで意味を持つ表示なので、1 つのときは省略可能。

### 4.4 [Nit] super-admin / member の表記が badge ではなく文字

`米窪博祐 [✎] super-admin` のように、role 表示が単なる文字。badge 化
すると視認性が上がる。

---

## 5. ヘッダー / ナビゲーション全般

### 5.1 [Minor] 各ページの「← 一覧」が Records へ戻る固定

`/account/tokens` / `/admin/pending` / `/admin/users` のすべてで
「← 一覧」が `/records` を指している。Dashboard から token に来た人は
Dashboard に戻りたいはず。

**提案**: 「← 戻る」(`history.back()`) もしくは「← Dashboard」に変更。

### 5.2 [Nit] header の `Dev User` が clickable に見えない

`Dev User` テキストの隣にログアウトボタン。`Dev User` をクリックして
profile に飛べると期待するが、無反応。

**提案**: 名前を dropdown trigger にして「プロフィール / ログアウト」
メニューを出す。または避けたいなら non-clickable に見せる (色を muted に)。

---

## 6. 開発者体験 (dev_skip 関連)

### 6.1 [Major] dev_skip でも records / tokens / admin の handler は本番 Firestore を引く

`auth_me` だけ dev_skip 分岐を入れた (PR #26) が、他の handler は引き続き
Firestore を本物で叩く。`.env` に `LABVAULT_GCP_PROJECT` が無いと 500 + CORS
error になる。

逆に `.env` を渡すと本番 Firestore に dev_skip ユーザーで書き込み・読み込み
できてしまう (§3.2 の事故源)。

**提案**: dev_skip 時には:
- (A) Lab を InMemoryBackend に切替える env (`LABVAULT_DEV_USE_INMEMORY=1`)
- もしくは (B) dev_skip 時は read-only モードにする (POST/PATCH/DELETE を
  401 で蹴る)

§3.2 と合わせて検討。

### 6.2 [Major] `.env` をリポジトリ root に置いても backend が読まない

`uvicorn` を `platform/backend/` 配下で起動すると cwd が backend dir に
なり、リポジトリ root の `.env` が読まれない。今回は `env $(grep ...)` で
手動注入した。

**提案**: backend 起動時に `--env-file` で root の `.env` を指定する手順
を `platform/backend/CLAUDE.md` に書く、もしくは backend の `Settings`
に `env_file=("../../.env", ".env", ...)` を追加する。

---

## 推奨アクション

### 直近 1 PR で済む系
1. **SearchBar の遷移先を `/records?q=` に固定** (§1.1) — 検索が機能する
2. **条件値の単位 "10deg" → "10 deg" or "10"** (§2.1) — 表示の冗長性解消
3. **token 発行のラベル必須化** (§3.1) — 「(無題)」量産防止
4. **「← 一覧」を「← 戻る」** (§5.1) — Dashboard 動線改善

### 中規模
5. **dev_skip 時の token 発行 + Firestore 書き込み防止** (§3.2, §6.1) —
   ローカル開発の事故防止
6. **records list のタイトル truncate + 日付に年付け** (§1.3, §1.4)
7. **destructive action に確認モーダル** (§4.2)

### docs / 細部
8. backend 起動時の `.env` 注入手順 (§6.2)
9. badge 化 (status / role) (§2.4, §4.4)
10. 空 state 表示 (§2.2, §4.1)

---

## 残課題

- **本番 Firestore に dev token (lv_mcauceon4...) が残っている** → revoke 必要
- record 詳細の散布図 / file preview は子持ち record で要確認
- 一括アップロード (`bulk_upload`) は未確認
- multi-team ユーザーでの team selector 挙動は未確認 (今は 1 team のみ)
- 装置 PC からの実投入経路は今回未対象
