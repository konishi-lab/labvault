# labvault オンボーディング (新規メンバー向け)

研究室で初めて labvault を使う人向けの、最短セットアップ + 最初の操作
ガイド。**30 分で「自分の record が Web UI で見える」状態を目指す**。

詳細仕様は [README](../README.md) / [docs/](.) を参照。ここでは
「とにかく動かす」ところまでに絞る。

---

## このツールでできること (1 分)

実験を 1 件 = 1 record として記録する。

- **Notebook / 装置スクリプトから自動で記録**: コード・条件・結果・
  ファイルがまとめて 1 record に
- **横断検索**: 「target = Cu の XRD 実験」「power が 50W 以上の照射」
  などを Web UI / CLI / LLM (MCP) から検索
- **Web UI で閲覧**: 表 + 散布図 + ファイルプレビュー + メモ
- **チームで共有**: 同じ team の record は全員で見える / 検索できる

---

## 30 分で済ますロードマップ

| 時間 | やること | 場所 |
|---|---|---|
| 5 分 | アカウント作成 + 承認 | Web UI (ブラウザ) |
| 5 分 | Web UI を眺める | Web UI |
| 10 分 | SDK を install | 自分の PC (ターミナル) |
| 5 分 | 最初の record を 1 つ作る | Notebook |
| 5 分 | Web UI でそれを確認 | Web UI |

---

## 1. アカウント作成 + 承認 (5 分)

Web UI を開く → **<https://labvault-web-355809880738.asia-northeast1.run.app>**

1. **Google でログイン** (個人 gmail or 研究室の Workspace アカウント)。
   ない場合は「メールで新規登録」。
2. 「申請」フォームに **所属希望の team 名** (基本 `konishi-lab`) と
   ひとことメモ (例: 「学部 4 年、レーザー加工で参加します」) を入れて
   送信。
3. **admin に Slack 等で「承認お願いします」と連絡**。Slack に申請通知も
   自動で飛ぶが、見落とされることがあるので一声かけると確実。
4. 承認されたら同じ Web UI を再ログイン → Dashboard が出れば成功。
5. **Welcome 画面** (初回のみ) が出るので 1 回読んで「始める」を押す。
   後でも `/welcome` から見直せる。

困ったら: § 6 「詰まったら」。

---

## 2. Web UI を眺める (5 分)

ログイン後の Dashboard (`/`) から:

- **「レコード一覧」** をクリック → 既存メンバーが入れた実験データが
  一覧で出る。タイトル / status / 作成日 / 条件 column が見える
- 適当に 1 行クリック → 詳細ページ:
  - 条件・結果カード (`target=Cu`, `power=20 W` 等)
  - タグ / メモ
  - 添付ファイル (CSV プレビュー、PNG 表示等)
  - 子レコードの散布図 (親 record の場合)
- 検索バーで `XRD` 等を入力 → 部分一致 + ベクトル検索でヒット
- **条件 chip** (一覧の上): `target=Cu` を chip 化すると URL に同期、
  絞り込み結果がそのまま共有できる URL になる

> 既存メンバーの命名を真似ると後で検索しやすい。タイトルに装置名や
> サンプル名を入れる、`smoke-test` のような目印 tag を使う、など。

---

## 3. SDK を install (10 分)

Mac / Linux 開発機なら **ADC 方式** (推奨)、Windows 装置 PC など
gcloud が入らない環境では **PAT 方式** を選ぶ。

### 3-A. ADC 方式 (Mac / Linux 開発機・Notebook)

```bash
# 1. 一度だけ: GCP ログイン
gcloud auth login
gcloud auth application-default login

# 2. clean venv (好きな場所で)
python -m venv .venv && source .venv/bin/activate

# 3. AR 認証 helper + labvault 本体
pip install keyring keyrings.google-artifactregistry-auth
pip install \
  --extra-index-url https://asia-northeast1-python.pkg.dev/klab-laser-process/labvault-pypi/simple/ \
  "labvault[gcp,nextcloud]"

# 4. .env をカレントディレクトリに置く
cat > .env << 'EOF'
LABVAULT_TEAM=konishi-lab
LABVAULT_USER=your-name
LABVAULT_GCP_PROJECT=klab-laser-process
LABVAULT_FIRESTORE_DATABASE=labvault
LABVAULT_PLATFORM_URL=https://labvault-api-355809880738.asia-northeast1.run.app
EOF

# 5. 動作確認
labvault doctor
```

`labvault doctor` で `mode: Direct mode` or `Mixed mode` が表示されて
`[!!]` が無ければ OK。

### 3-B. PAT 方式 (Windows 装置 PC / gcloud が入らない環境)

Web UI で **PAT を発行** してから install する。gcloud は不要。

1. **Web UI** → Dashboard 右上「トークン」 (`/account/tokens`)
2. ラベル (例: `装置 PC: XRD A 号機`) を入れて「発行」
3. 表示された `lv_xxxxxxxxx...` をコピー (**この画面を離れると再表示
   不可**)

**Windows PowerShell**:

```powershell
$env:PAT = "lv_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
$PROXY = "https://__token__:${env:PAT}@labvault-api-355809880738.asia-northeast1.run.app/api/pypi/simple/"

python -m venv .venv
.venv\Scripts\Activate.ps1

pip install `
  --index-url https://pypi.org/simple/ `
  --extra-index-url "$PROXY" `
  "labvault[gcp,nextcloud]"

# SDK 認証 (~/.labvault/credentials を 1 行で作る)
echo $env:PAT | labvault auth set-token --token-stdin --user instrument-xrd-1

# 動作確認
labvault doctor
labvault auth status
```

**Mac / Linux** で PAT を使う場合は `` ` `` (バックティック) を `\` に
換える / `$env:PAT` を `${PAT}` にする等の差だけ。詳細は
[`docs/instrument_pc_setup.md`](instrument_pc_setup.md)。

### つまずきポイント

- **`pip install` で 403**: アカウントがまだ承認されていない。§ 1 へ
  戻る。
- **`pip install` で `not allowed`**: gcloud のログインアカウントが
  AR reader 権限を持っていない。承認 admin に問い合わせる。
- **`PlatformMetadataBackend`** が出てきたら PAT モード、
  **`FirestoreMetadataBackend`** が出てきたら ADC モード。どちらでも
  動作上は OK。
- **Windows で `.venv\Scripts\Activate.ps1` が止められる**:
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` で許可するか、
  `pwsh -ExecutionPolicy Bypass` で起動。

---

## 4. 最初の record を作る (5 分)

Notebook を起動 (`jupyter lab` など) して、**実験シリーズ = 親 record**
+ **各測定 = 子 record** を作ってみる。labvault では「同じテーマの
複数測定」をこの親子関係で表現する。

### 4.1 親 record (シリーズ)

```python
from labvault import Lab

lab = Lab()

# 親 record (実験シリーズ全体)
series = lab.new(
    "はじめての record (パラメータ scan)",
    tags=["onboarding", "your-name"],
)
print(series.id)  # 例: P2BV1M
```

### 4.2 子 record を 3 つ (パラメータ scan)

```python
import numpy as np
import matplotlib.pyplot as plt

for power in [5, 10, 20]:
    # 親.sub() で子レコードを作成。条件もここで渡せる
    child = series.sub(f"power={power}W", power=power)

    # 何か計算
    x = np.linspace(0, 1, 100)
    y = np.sin(x * power)

    # 結果 + ファイル添付
    child.results["max_y"] = float(y.max())
    child.results["min_y"] = float(y.min())

    fig, ax = plt.subplots()
    ax.plot(x, y)
    child.save("plot.png", fig)
    plt.close(fig)

    child.status = "success"

# シリーズ全体も完了マーク
series.status = "success"

# 子レコード一覧を確認
for c in series.children():
    print(c.id, c.title, c.results.to_dict())
```

### ポイント

- **`parent.sub(title, **conditions)`** で子を作る。`lab.new(...)` の
  ような top-level 呼び出しではなく **親オブジェクトから生やす**
- 子の `parent_id` には自動で親の id が入り、Web UI で「親詳細 → 子
  レコード」セクションに表示される
- 子も親と同じく `conditions / results / save / status` が使える
- **使い分け**: 「1 サンプル / 1 測定 = 子」「シリーズ全体 = 親」が
  典型。条件 scan (power, target, temperature 等を変えた繰り返し測定)
  や、装置別の連続測定で重宝する

セルを順番に実行すると **各セルのコードと出力も自動で記録される**
(IPython hooks が動いている)。

---

## 5. Web UI で確認 (5 分)

Web UI を開く (or リロード) →

1. Dashboard 「最近のレコード」に **「はじめての record (パラメータ
   scan)」** が新着で出る (= 親 series)
2. クリック → 詳細:
   - タグ `onboarding`, `your-name`
   - **「子レコード」セクション** に 3 件並ぶ
     (`power=5W` / `power=10W` / `power=20W`)
   - **散布図** が自動表示: X 軸 = `power`、Y 軸 = `max_y` を選ぶと
     子の結果が点として並ぶ
   - 点を hover でラベル表示、クリックで子の詳細に飛べる
3. 子の 1 つ (`power=10W`) を開く:
   - 条件 (`power: 10`)
   - 結果 (`max_y`, `min_y`)
   - 添付ファイル `plot.png` プレビュー表示
   - `parent_id` に親 series の id が入っている (詳細上部)
4. 「メモ」を追加してみる: 「初回テスト」など
5. **タグでフィルタ**: 一覧で `?tags=your-name` を試すと自分のだけ抽出

ここまで来れば一通り回ったことになる 🎉

---

## 6. 詰まったら

### まず叩く 2 コマンド

```bash
labvault doctor       # 設定の状態と「次のステップ」が出る
labvault auth status  # PAT 設定済か、どこに置かれているか
```

`doctor` は問題があれば「次のステップ:」セクションに具体的な対処法を
出すので、それに従う。

### よくある症状

| 症状 | 原因 / 対処 |
|---|---|
| `pip install` で `403 Forbidden` | アカウント未承認、または gcloud ログインが別アカウント |
| `Lab()` で `Settings 読み込み失敗` | `.env` の location が違う (Notebook の cwd を確認) |
| `Token verification failed` | PAT 失効 or 間違い → `/account/tokens` で再発行 → `labvault auth set-token --force` |
| 一覧に出ない record がある | status を `running` のまま放置 / sync 中。`labvault status` で確認 |
| Web UI でログインしても Dashboard に出ない | admin がまだ承認していない or 別 team を指定された |

### 助けを呼ぶ

- **admin に直接連絡** (Slack DM): アカウント承認 / team 変更 / 権限の
  問題はここ
- **Slack `#labvault` チャンネル**: 使い方 Q&A、バグ報告、便利な技
  共有
- [README](../README.md) / [docs/](.) も参照

---

## 7. 次に読むもの (目的別)

| 興味 | docs |
|---|---|
| 装置 PC に常設するセットアップ | [`docs/instrument_pc_setup.md`](instrument_pc_setup.md) |
| 全 CLI / SDK API の reference | [README](../README.md) |
| 設計思想 / 内部 backend の仕組み | [`docs/design/`](design/) |
| Claude / Gemini からの操作 (MCP) | [README](../README.md) の MCP セクション |
| QA / リリース前チェック | [`docs/qa_checklist.md`](qa_checklist.md) |
| 既知の運用ノート | [`docs/firestore_indexes.md`](firestore_indexes.md), [`docs/auth_design.md`](auth_design.md) |

---

## おまけ: その日のうちにやっておくと幸せなこと

- 自分の **PAT を 1 つ発行** して `~/.labvault/credentials` に置いておく
  (ADC モードでもバックアップとして)
- Notebook の **テンプレ snippet** を VSCode / Jupyter に登録
  (`from labvault import Lab; lab = Lab(); exp = lab.new("___")`)
- `.gitignore` に `.env`, `~/.labvault/credentials` を追加
  (個人 git repo を使う場合)
- **どの装置 PC は誰の PAT で動いているか** を Slack / Notion に
  メモ (失効時にトレースできるように)
