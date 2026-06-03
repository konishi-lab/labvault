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
  "labvault[all]"

# 4. .env をカレントディレクトリに置く (your-name は自分の名前に書き換える)
#    gcp_project / firestore_database / platform_url / nextcloud_url は
#    SDK の default に組み込まれているので書かなくて OK (0.2.2 以降)。
cat > .env << 'EOF'
LABVAULT_TEAM=konishi-lab
LABVAULT_USER=your-name
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
  "labvault[all]"

# SDK 認証 (~/.labvault/credentials を 1 行で作る)
echo $env:PAT | labvault auth set-token --token-stdin --user instrument-xrd-1

# 動作確認
labvault doctor
labvault auth status
```

**Mac / Linux** で PAT を使う場合は `` ` `` (バックティック) を `\` に
換える / `$env:PAT` を `${PAT}` にする等の差だけ。詳細は
[`docs/instrument_pc_setup.md`](instrument_pc_setup.md)。

> 0.2.2 以降、`LABVAULT_PLATFORM_URL` は SDK の default に組み込まれて
> いるので、credentials を手書きで作る場合は `LABVAULT_TOKEN=lv_xxx` +
> `LABVAULT_TEAM=konishi-lab` + `LABVAULT_USER=...` の 3 行で足ります
> (`auth set-token` 経由なら自動で書き込まれるので意識不要)。

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

peak_values: list[float] = []

for power in [5, 10, 20]:
    # 親.sub() で子レコードを作成。条件もここで渡せる
    # (値, "単位") のタプルで渡すと単位も一緒に記録される
    child = series.sub(f"power={power}W", power=(power, "W"))

    # 何か計算
    x = np.linspace(0, 1, 100)
    y = np.sin(x * power)
    peak = float(y.max())

    # ── 条件側: scan 軸 + 散布図の軸候補として残したい数値
    # 後から追加するときは conditions() メソッドを使う。複数回呼んでも OK。
    # 単位を付けたいときは (値, "単位") or (値, "単位", "説明") の tuple で渡す。
    child.conditions(
        max_y=(peak, "V", "出力電圧の最大値"),
        min_y=(float(y.min()), "V"),
    )

    # ── 結果側: 「この測定の結論はこれ」という主結果を 1〜数件だけ
    # 詳細ページの「結果」カードに並ぶ。後段の解析の入力にもなる。
    # conditions と対称に (値, "単位") / (値, "単位", "説明") の tuple
    # 記法が使える (0.2.3 以降)。
    child.results["peak_value"] = (peak, "V", "出力電圧のピーク")
    child.results["mean_y"] = (float(y.mean()), "V")

    # ファイル添付
    fig, ax = plt.subplots()
    ax.plot(x, y)
    child.save("plot.png", fig)
    plt.close(fig)

    child.status = "success"
    peak_values.append(peak)

# シリーズ全体にも代表値を結果として残す (scan の要約)
series.results["max_peak"] = (max(peak_values), "V")
series.results["best_power"] = (
    [5, 10, 20][peak_values.index(max(peak_values))],
    "W",
    "最大ピークを出した power",
)
series.status = "success"

# 子レコード一覧を確認
for c in series.children():
    print(c.id, c.title, c.get_conditions(), dict(c.results.items()))
```

### ポイント

- **`parent.sub(title, **conditions)`** で子を作る。`lab.new(...)` の
  ような top-level 呼び出しではなく **親オブジェクトから生やす**
- 子の `parent_id` には自動で親の id が入り、Web UI で「親詳細 → 子
  レコード」セクションに表示される
- 子も親と同じく `conditions() / results[...] / save() / status` が使える
- **`conditions()` は何度でも呼べる** (上書き / 追加)。`sub()` の
  キーワード引数として渡すのは初期値、後で計算した値は
  `child.conditions(max_y=..., ...)` で追記する
- **conditions と results の使い分け**:
  - **conditions** = 「scan の入力 + 散布図の軸候補にしたい数値」。
    Web UI のレコード一覧の条件カラム / 散布図の X / Y 候補に出る。
    `power` のような scan parameter + `max_y` のような「測定中に
    得られた中間値」もここに置くと一覧が見やすい
  - **results** = 「この測定の結論 / headline 値」。詳細ページの
    『結果』カードに並び、後段の解析や論文表でそのまま拾える 1〜
    数件の主結果を入れる (`peak_value`, `lattice_a`, `phase` 等)。
    入れていいのはスカラー (int / float / str / bool) + 小さな
    リスト / dict まで。**画像・大きな配列・生データはファイル添付**
    (`record.save("plot.png", fig)` / `record.save("data.npy", arr)`)
    に回す
  - 親 (series) の `results` には scan の要約 (`max_peak`,
    `best_power_W` など) を 1〜数件残しておくと、後から
    Dashboard 検索で「最大ピーク値が高いシリーズ」を絞り込める
- **使い分け**: 「1 サンプル / 1 測定 = 子」「シリーズ全体 = 親」が
  典型。条件 scan (power, target, temperature 等を変えた繰り返し測定)
  や、装置別の連続測定で重宝する

### 4.3 単位の扱い

数値には **必ず単位** を付ける癖を付けると後の比較・検索・論文化が
楽になる。0.2.3 以降、conditions / results 両方で **同じ tuple 記法**
が使えます。

| 方法 | 書き方 | 用途 |
|---|---|---|
| (a) tuple で値+単位 | `conditions(power=(20, "W"))` / `results["peak"] = (0.97, "V")` | 一番きれい |
| (b) tuple で値+単位+説明 | `(20, "W", "レーザー出力")` | hover で説明が出る |
| (c) template で auto-fill | template の `condition_fields[].unit` | 値だけ書けば template が単位を補完 (例: XRD template の `wavelength_A`) |
| (d) Web UI で後付け | 詳細ページの条件 / 結果 row をクリック → 単位 + 説明を編集 | 既存 record の単位を後から直す。両方対応 |
| (e) パーサーから自動 | `template.file_parsers` 経由で `add()` → parser output の `units` dict が `result_units` に流れ込む | `.ras` / `.vk4` 等の組み込みパーサー |

Web UI では条件 / 結果カードどちらも `key [unit]: value` の青字 chip
付きで表示され、`(b)` を使った場合は `— 説明` も並びます。

**実務的なおすすめ**:

- 数値は基本 (a) の tuple 記法で書く (`power=(20, "W")`, `results["peak"] = (0.97, "V")`)
- 後で論文表にしたい / 解析で使い回したい値は (b) で説明も付けておくと self-documenting
- template に登録した key (XRD の `target` / `wavelength_A` 等) は (c) の auto-fill で値だけ書けば OK
- 装置パーサーがある測定 (.ras / .vk4) は (e) で勝手に単位が入る
- 既存 record を後から直すのは (d) (Web UI 詳細ページで row クリック)

> **互換性メモ**: 既存の `results["lattice_a"] = 2.873` のような
> スカラー代入は引き続き動きます。tuple 記法は追加 API。

### 4.4 データの置き場所: `results` / `save` / `add` の使い分け

1 つの測定で出てくるデータは、サイズと用途で 3 つの置き場所を使い
分けます。

| 置き場所 | API | 入れるもの | フォーマット変換 |
|---|---|---|---|
| **metadata field** | `record.results["key"] = ...` | スカラー / 小リスト / 小 dict (論文表に貼れる粒度) | なし |
| **ファイル添付 (自動変換あり)** | `record.save(name, obj)` | Python オブジェクト全般 | 自動 (dict/list→JSON, ndarray→.npy, Figure→.png, DataFrame→.csv) |
| **ファイル添付 (生バイト)** | `record.add(path_or_bytes)` | 既存ファイル / 装置出力バイナリ | なし |

> `save` は **内部で `add` を呼ぶラッパー** です。違いは「型変換を
> labvault に任せる (save) か、自分で済ませる (add) か」だけ。
> `record.save("plot.png", fig)` ≈ `add(fig_to_png_bytes(fig), name="plot.png", content_type="image/png")`。

選び方 (上から順に試す):

1. **論文表の 1 行に貼れる小さな値か?** → `results["key"] = value`
   (検索 / scatter / 結果カード表示で活躍)
2. **Python オブジェクトを 1 行でファイル化したいか?** →
   `record.save("plot.png", fig)` / `record.save("data.npy", arr)` /
   `record.save("table.csv", df)` (内部で自動変換 → `add()`)
3. **すでにファイルがある (装置出力など)?** →
   `record.add("xrd_001.ras")` / `record.add("photo.jpg")`
   (内容はそのまま。template にパーサーが紐付いていれば
   add 時に自動で results に要約値が入る)

```python
# 典型例: 1 つの測定で 3 つを使い分ける
child.results["peak_value"] = (0.97, "V")            # ① 主結果
child.save("waveform.png", fig)                      # ② Figure を PNG に
child.add("instrument_log.txt")                      # ③ 装置生ログをそのまま
```

> どれもファイルは Nextcloud、metadata は Firestore に行きます。
> Firestore のドキュメントは **1 件 1 MB 上限** なので、画像や
> 大きな配列は ① に入れず必ず ② / ③ にしてください。

### 4.5 セル自動記録

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
   - **条件カード**: `power [W]: 10`, `max_y [V]: ...`, `min_y [V]: ...`
     (tuple で渡した単位が `[ ]` で表示される。`max_y` は説明が入って
     いるので名前を hover すると「出力電圧の最大値」がツールチップで
     出る)
   - **結果カード**: `peak_value_V`, `mean_y_V` (主結果として並ぶ。
     単位はキー名 suffix で表現)
   - 添付ファイル `plot.png` プレビュー表示
   - `parent_id` に親 series の id が入っている (詳細上部)
4. 親 series を開き直すと、**結果カード**に `max_peak_V` /
   `best_power_W` が並んでいるはず (scan の要約)
5. 「メモ」を追加してみる: 「初回テスト」など
6. **タグでフィルタ**: 一覧で `?tags=your-name` を試すと自分のだけ抽出

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
