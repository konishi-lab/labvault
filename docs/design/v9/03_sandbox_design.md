# v9 サンドボックス実行環境設計

## 概要

MCPツール `execute_code` / `batch_execute` で使用するPythonコード実行環境の詳細設計。
LLM（Claude）が生成したPythonコードを、実験データに対してセキュアに実行し、結果を自動保存する。

---

## 目次

1. [アーキテクチャ（Cloud Run Jobs ベース）](#1-アーキテクチャcloud-run-jobs-ベース)
2. [セキュリティモデル](#2-セキュリティモデル)
3. [プリインストールパッケージ](#3-プリインストールパッケージ)
4. [データアクセスフロー](#4-データアクセスフロー)
5. [画像生成・保存フロー](#5-画像生成保存フロー)
6. [解析履歴の自動保存](#6-解析履歴の自動保存)
7. [batch_executeの並列実行設計](#7-batch_executeの並列実行設計)
8. [エラーハンドリング・タイムアウト](#8-エラーハンドリングタイムアウト)
9. [Dockerfileサンプル](#9-dockerfileサンプル)
10. [コスト見積もり](#10-コスト見積もり)

---

## 1. アーキテクチャ（Cloud Run Jobs ベース）

### 1.1 全体構成

```
MCPサーバー (Cloud Run Service)
    |
    | (1) execute_code リクエスト受信
    v
+----------------------------------------------+
|  MCPサーバー内の処理                          |
|  a. コード安全性検査 (AST解析)                |
|  b. 入力ファイル取得 (Nextcloud -> /tmp)      |
|  c. Cloud Run Jobs 実行トリガー               |
+----------------------------------------------+
    |
    | (2) Jobs API で実行をディスパッチ
    v
+----------------------------------------------+
|  Cloud Run Jobs (asia-northeast1)            |
|  +-- コンテナ: gcr.io/labvault-project/      |
|  |   code-executor:latest                    |
|  +-- CPU: 2 vCPU                             |
|  +-- メモリ: 2 GiB                           |
|  +-- タイムアウト: 120秒                      |
|  +-- ネットワーク: VPC内のみ                  |
|  +-- gVisor (自動適用)                        |
|  +-- サービスアカウント:                      |
|      code-executor@labvault-project.iam      |
+----------------------------------------------+
    |
    | (3) 実行結果を返却
    v
MCPサーバー
    |
    | (4) 結果保存 (Firestore + Nextcloud)
    v
レスポンス返却
```

### 1.2 実行フロー（詳細）

```
1. MCPサーバーが execute_code リクエストを受信
2. コード安全性検査（ASTベースの禁止import検出）
3. 入力ファイルをNextcloudからダウンロード → Cloud Storage一時バケットにアップロード
4. Cloud Run Jobs を実行:
   - 環境変数: EXECUTION_ID, INPUT_BUCKET, OUTPUT_BUCKET
   - Cloud Storage から入力ファイルをダウンロード
   - ユーザーコードを実行
   - 結果JSON + 生成画像を Cloud Storage にアップロード
5. MCPサーバーが Cloud Storage から結果を取得
6. 画像をNextcloudにアップロード
7. 解析履歴をFirestoreに保存
8. ExecuteResult を返却
```

### 1.3 MVP段階の簡易実装（subprocess方式）

本番のCloud Run Jobs実装までの間、subprocess方式で実行する。

```
MCPサーバー (Cloud Run Service)
    |
    | (1) execute_code リクエスト
    v
+-- 同一コンテナ内 subprocess --+
|  +-- tmpdir にファイル配置    |
|  +-- wrapper.py 経由で実行    |
|  +-- gVisor (Cloud Run標準)   |
|  +-- タイムアウト制御         |
+-------------------------------+
    |
    | (2) stdout/stderr + 生成ファイル
    v
結果保存・返却
```

---

## 2. セキュリティモデル

### 2.1 多層防御

| 層 | 対策 | 説明 |
|----|------|------|
| L1: コード検査 | AST解析 | 禁止importの検出、危険なパターンの検出 |
| L2: ランタイム分離 | gVisor | Cloud Run/Cloud Run Jobs はgVisorサンドボックス上で動作 |
| L3: ネットワーク遮断 | VPCコネクタ | 外部インターネットアクセスを完全遮断 |
| L4: リソース制限 | CPU/メモリ/時間上限 | 2 vCPU, 2 GiB, 120秒 |
| L5: ファイルシステム | tmpdir限定 | エフェメラルストレージ、実行後自動削除 |
| L6: 権限最小化 | IAM | 必要最小限のGCPリソースアクセスのみ |

### 2.2 禁止importリスト

```python
BANNED_IMPORTS = {
    # OS操作
    "os", "subprocess", "shutil", "pathlib",
    # ネットワーク
    "socket", "http", "urllib", "requests", "httpx", "aiohttp",
    # システム
    "ctypes", "multiprocessing", "threading",
    "signal", "resource", "gc",
    # ファイル操作（file_path変数で代替）
    "glob", "fnmatch",
    # セキュリティ
    "pickle", "shelve", "marshal",
    "importlib", "runpy",
}
```

### 2.3 AST検査の実装

```python
import ast
from typing import NamedTuple


class CodeViolation(NamedTuple):
    line: int
    message: str


def validate_code(code: str) -> list[CodeViolation]:
    """コードの安全性を検査する。"""
    violations = []

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [CodeViolation(line=e.lineno or 0, message=f"構文エラー: {e.msg}")]

    for node in ast.walk(tree):
        # 禁止import
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name.split(".")[0]
                if module in BANNED_IMPORTS:
                    violations.append(CodeViolation(
                        line=node.lineno,
                        message=f"禁止されたモジュール: {module}"
                    ))

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                module = node.module.split(".")[0]
                if module in BANNED_IMPORTS:
                    violations.append(CodeViolation(
                        line=node.lineno,
                        message=f"禁止されたモジュール: {module}"
                    ))

        # eval / exec の直接呼び出し
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec", "compile", "__import__"):
                violations.append(CodeViolation(
                    line=node.lineno,
                    message=f"禁止された関数: {node.func.id}"
                ))

        # open() は読み取りのみ許可（書き込みモードを検出）
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            if len(node.args) >= 2:
                mode_arg = node.args[1]
                if isinstance(mode_arg, ast.Constant) and "w" in str(mode_arg.value):
                    violations.append(CodeViolation(
                        line=node.lineno,
                        message="ファイル書き込みは禁止されています（結果はresult変数に格納してください）"
                    ))

    return violations
```

### 2.4 ネットワーク遮断の設定

```bash
# VPCコネクタ作成（Cloud Run Jobs用）
gcloud compute networks vpc-access connectors create labvault-vpc-connector \
  --region=asia-northeast1 \
  --range=10.8.0.0/28

# ファイアウォールルール: 外部通信を全て遮断
gcloud compute firewall-rules create deny-executor-egress \
  --network=default \
  --direction=EGRESS \
  --action=DENY \
  --rules=all \
  --target-service-accounts=code-executor@labvault-project.iam.gserviceaccount.com \
  --priority=100

# ただし内部GCPサービス（Cloud Storage, Firestore）へのアクセスは許可
gcloud compute firewall-rules create allow-executor-gcp-internal \
  --network=default \
  --direction=EGRESS \
  --action=ALLOW \
  --rules=tcp:443 \
  --destination-ranges=199.36.153.8/30 \
  --target-service-accounts=code-executor@labvault-project.iam.gserviceaccount.com \
  --priority=90
```

### 2.5 リソース制限

| リソース | 制限値 | 根拠 |
|----------|--------|------|
| CPU | 2 vCPU | scipy等の科学計算に必要 |
| メモリ | 2 GiB | 中規模のnumpy配列操作に十分 |
| 実行時間 | 120秒（ハード） / 60秒（デフォルト） | ユーザー指定可、最大120秒 |
| エフェメラルストレージ | 1 GiB | 一時ファイル用 |
| 同時実行 | 1（Jobにつき） | 分離のため |

---

## 3. プリインストールパッケージ

### 3.1 パッケージ一覧

| パッケージ | バージョン | 用途 |
|-----------|-----------|------|
| numpy | >= 2.0.0 | 数値計算 |
| scipy | >= 1.13 | 科学技術計算（フィッティング、FFT、統計） |
| matplotlib | >= 3.9 | グラフ描画 |
| pandas | >= 2.2 | データフレーム操作 |
| scikit-learn | >= 1.5 | 機械学習基礎 |
| lmfit | >= 1.3 | 高度なカーブフィッティング |
| Pillow | >= 11.0 | 画像処理 |
| h5py | >= 3.11 | HDF5ファイル読み書き |
| openpyxl | >= 3.1 | Excelファイル読み込み |

### 3.2 材料科学特化パッケージ

| パッケージ | バージョン | 用途 |
|-----------|-----------|------|
| pymatgen | >= 2024.6 | 結晶構造解析 |
| ase | >= 3.23 | 原子シミュレーション環境 |
| periodictable | >= 1.7 | 元素周期表データ |

### 3.3 禁止パッケージ（インストールしない）

以下はセキュリティ上の理由でインストールしない:

- `requests`, `httpx`, `aiohttp` (ネットワーク通信)
- `flask`, `fastapi` (Webサーバー)
- `paramiko`, `fabric` (SSH)
- `boto3` (AWS)
- `azure-*` (Azure)

---

## 4. データアクセスフロー

### 4.1 入力データの流れ

```
Nextcloud (永続ストレージ)
    |
    | (1) MCPサーバーがファイルをダウンロード
    v
MCPサーバーの一時ディレクトリ (/tmp)
    |
    | --- MVP: そのままsubprocessに渡す ---
    | --- 本番: Cloud Storageにアップロード ---
    v
Cloud Storage 一時バケット (gs://labvault-executor-tmp/)
    |
    | (2) Cloud Run Jobs がダウンロード
    v
コンテナ内 /workspace/ ディレクトリ
    |
    | (3) ユーザーコードから file_path 変数でアクセス
    v
ユーザーコード実行
```

### 4.2 ユーザーコードからのファイルアクセス

ユーザーコードには以下の変数が自動注入される:

```python
# 自動注入される変数（ユーザーには見えない前処理で設定）

# 単一ファイルの場合
file_path = "/workspace/xrd_raw.csv"

# 複数ファイルの場合
xrd_raw_csv_path = "/workspace/xrd_raw.csv"
SEM_50000x_tif_path = "/workspace/SEM_50000x.tif"

# 前の解析結果を入力にする場合
analysis_AN7K_json_path = "/workspace/analysis_AN7K.json"
```

### 4.3 出力データの流れ

```
ユーザーコード実行
    |
    +-- (a) result 変数 -> JSON化 -> stdout経由で返却
    |
    +-- (b) matplotlib Figure -> 自動保存 -> /workspace/_img_*.png
    |
    +-- (c) 明示的保存 -> /workspace/output_*.{csv,json,npy}
    v
MCPサーバー
    |
    +-- 画像 -> Nextcloud: {record}/_analyses/{analysis_id}_*.png
    +-- 結果 -> Firestore: analyses/{analysis_id}/results
    +-- stdout -> Firestore: analyses/{analysis_id}/stdout
```

### 4.4 前の解析結果の参照

```python
# LLMが生成するコード例:
# input_analyses=["AN7K"] を指定した場合

import json

# 前の解析結果を読み込む
with open(analysis_AN7K_json_path) as f:
    prev_result = json.load(f)

center = prev_result["center"]  # 28.4
sigma = prev_result["sigma"]    # 0.18

# この結果を使って追加解析...
```

---

## 5. 画像生成・保存フロー

### 5.1 matplotlib自動キャプチャ

ユーザーコードで `plt.show()` や `plt.savefig()` を呼ばなくても、全てのFigureを自動保存する。

```python
# ラッパースクリプト内の画像自動保存ロジック

import matplotlib
matplotlib.use("Agg")  # 非対話型バックエンド
import matplotlib.pyplot as plt

# --- ユーザーコード実行 ---
exec(user_code)
# --- ここまで ---

# 全Figureを自動保存
_images = []
for i, fig_num in enumerate(plt.get_fignums()):
    fig = plt.figure(fig_num)
    img_path = f"/workspace/_img_{i}.png"
    fig.savefig(img_path, dpi=150, bbox_inches="tight", facecolor="white")
    _images.append(img_path)
    plt.close(fig)
```

### 5.2 画像の保存先

```
Nextcloud:
  {record_nextcloud_path}/_analyses/{analysis_id}_{img_name}

例:
  large/konishi-lab/labvault/v1/experiments/AB3F/_analyses/AN7K_img_0.png
  large/konishi-lab/labvault/v1/experiments/AB3F/_analyses/AN7K_img_1.png
```

### 5.3 画像フォーマット設定

```python
# デフォルトのmatplotlib設定（ラッパーで事前設定）
import matplotlib
matplotlib.rcParams.update({
    "figure.figsize": (8, 6),
    "figure.dpi": 150,
    "savefig.dpi": 150,
    "savefig.bbox": "tight",
    "savefig.facecolor": "white",
    "font.size": 12,
    "axes.unicode_minus": False,  # マイナス記号の文字化け防止
})
```

---

## 6. 解析履歴の自動保存

### 6.1 Firestoreドキュメント構造

```
teams/{team_id}/records/{record_id}/analyses/{analysis_id}
{
    "id": "AN7K",
    "name": "gaussian_fit",
    "code": "import numpy as np\nfrom scipy.optimize import curve_fit\n...",
    "input_files": ["xrd_raw.csv"],
    "input_analyses": [],
    "results": {
        "center": 28.443,
        "sigma": 0.182,
        "fwhm": 0.429,
        "amplitude": 12500.0,
        "r_squared": 0.9987
    },
    "images": ["AN7K_img_0.png"],
    "stdout": "Fitting converged in 12 iterations\nR² = 0.9987",
    "executed_at": "2026-03-17T10:30:00Z",
    "executed_by": "claude",
    "prompt": "XRDデータの最強ピークをガウスフィットして",
    "duration_sec": 3.2,
    "packages": {"numpy": "2.1.0", "scipy": "1.14.0"},
    "error": null
}
```

### 6.2 解析チェーン（DAG）

解析は `input_analyses` フィールドで前の解析を参照でき、DAG（有向非巡回グラフ）を形成する。

```
AN7K (gaussian_fit)
  |
  +-- input: xrd_raw.csv
  |
  v
BM2P (peak_comparison)
  |
  +-- input_analyses: ["AN7K"]
  +-- input: reference.csv
  |
  v
CQ4R (visualization)
  |
  +-- input_analyses: ["AN7K", "BM2P"]
```

### 6.3 result変数の規約

ユーザーコードで `result` 変数に dict を代入すると、自動的に解析結果として保存される。

```python
# ユーザーコード例
from scipy.optimize import curve_fit
import numpy as np
import pandas as pd

# データ読み込み
df = pd.read_csv(file_path)
x, y = df.iloc[:, 0].values, df.iloc[:, 1].values

# ガウスフィット
def gaussian(x, amp, center, sigma):
    return amp * np.exp(-(x - center)**2 / (2 * sigma**2))

popt, pcov = curve_fit(gaussian, x, y, p0=[y.max(), x[y.argmax()], 1.0])

# result変数に代入 -> 自動保存される
result = {
    "amplitude": float(popt[0]),
    "center": float(popt[1]),
    "sigma": float(popt[2]),
    "fwhm": float(2.355 * popt[2]),
    "r_squared": float(1 - np.sum((y - gaussian(x, *popt))**2) / np.sum((y - y.mean())**2)),
}
```

---

## 7. batch_executeの並列実行設計

### 7.1 アーキテクチャ

```
batch_execute(record_ids=[A, B, C, D, E, F])
    |
    v
asyncio.Semaphore(5)  # 同時実行数制限
    |
    +-- [slot 1] execute_code(A) -----> 完了
    +-- [slot 2] execute_code(B) -----> 完了
    +-- [slot 3] execute_code(C) -----> 完了
    +-- [slot 4] execute_code(D) -----> 完了
    +-- [slot 5] execute_code(E) -----> 完了
    |                                    |
    +-- [slot 1] execute_code(F) <------+ (スロット再利用)
    |
    v
全結果を集約 -> BatchExecuteResult
```

### 7.2 同時実行数の決定基準

| 方式 | 同時実行数 | メモリ消費 | 適用条件 |
|------|-----------|-----------|----------|
| subprocess (MVP) | 5 | ~10 GiB (2GiB x 5) | MCPサーバーのメモリが十分な場合 |
| Cloud Run Jobs (本番) | 10 | 各Jobが独立 | Job並列実行 |

### 7.3 エラー分離

```python
# 1つのレコードが失敗しても他は続行
results = await asyncio.gather(
    *[execute_one(rid) for rid in record_ids],
    return_exceptions=True,  # 例外を結果として収集
)

# 結果の分類
for i, result in enumerate(results):
    if isinstance(result, Exception):
        # エラーとして記録
        final_results.append({
            "record_id": record_ids[i],
            "error": str(result),
            "results": {},
            "images": [],
        })
    else:
        final_results.append(result)
```

### 7.4 集約結果テーブル

batch_execute の結果として、全レコードの結果を横断比較表にまとめる:

```python
# summary.results_table の例
[
    {"record_id": "AB3F", "center": 28.443, "sigma": 0.182, "fwhm": 0.429},
    {"record_id": "KL67", "center": 28.612, "sigma": 0.215, "fwhm": 0.506},
    {"record_id": "MN89", "center": 28.301, "sigma": 0.198, "fwhm": 0.466},
    {"record_id": "PQ12", "error": "Fitting did not converge"},
]
```

---

## 8. エラーハンドリング・タイムアウト

### 8.1 エラー分類と対応

| エラー種別 | 検出方法 | ユーザーへの通知 | リトライ |
|-----------|---------|----------------|---------|
| 構文エラー | AST parse | エラーメッセージ + 行番号 | 不要（コード修正が必要） |
| 禁止import | AST検査 | 禁止モジュール名 + 代替方法の提案 | 不要 |
| 実行時エラー | stderr | 完全なトレースバック | 不要（コード修正が必要） |
| タイムアウト | asyncio.wait_for | 「実行タイムアウト (N秒)」 | 可（timeout_sec増加で再試行） |
| メモリ超過 | OOM Kill | 「メモリ不足」 | 可（データ量削減で再試行） |
| Nextcloudエラー | 例外捕捉 | ファイル取得失敗メッセージ | 自動リトライ（3回） |

### 8.2 タイムアウト制御

```python
# 3段階のタイムアウト

# L1: ユーザー指定タイムアウト（デフォルト60秒）
user_timeout = min(timeout_sec, 120)  # 最大120秒に制限

# L2: subprocess/Jobタイムアウト（ユーザー指定 + バッファ）
execution_timeout = user_timeout + 10  # 10秒のバッファ

# L3: MCPツール全体のタイムアウト（ファイル取得・保存を含む）
total_timeout = user_timeout + 60  # 前後処理の時間を考慮
```

### 8.3 エラーレスポンス形式

```python
# 正常終了
{
    "analysis_id": "AN7K",
    "name": "gaussian_fit",
    "results": {"center": 28.443, "sigma": 0.182},
    "stdout": "Fitting converged",
    "images": ["AN7K_img_0.png"],
    "duration_sec": 3.2,
    "error": None,
}

# エラー終了（コード検査）
{
    "analysis_id": "",
    "name": "",
    "results": {},
    "stdout": "",
    "images": [],
    "duration_sec": 0.0,
    "error": "コード検査エラー: 禁止されたモジュール: os (行 3); 禁止されたモジュール: subprocess (行 5)"
}

# エラー終了（実行時エラー）
{
    "analysis_id": "AN7K",
    "name": "gaussian_fit",
    "results": {},
    "stdout": "",
    "images": [],
    "duration_sec": 2.1,
    "error": "Traceback (most recent call last):\n  File \"_code.py\", line 15\n    popt, pcov = curve_fit(gaussian, x, y)\nRuntimeError: Optimal parameters not found: maxfev=800 reached"
}

# エラー終了（タイムアウト）
{
    "analysis_id": "AN7K",
    "name": "analysis",
    "results": {},
    "stdout": "",
    "images": [],
    "duration_sec": 60.0,
    "error": "実行タイムアウト (60秒)"
}
```

---

## 9. Dockerfileサンプル

### 9.1 本番用 (Cloud Run Jobs)

```dockerfile
# code-executor/Dockerfile
FROM python:3.12-slim AS base

# システム依存パッケージ
RUN apt-get update && apt-get install -y --no-install-recommends \
    libopenblas-dev \
    liblapack-dev \
    libhdf5-dev \
    && rm -rf /var/lib/apt/lists/*

# Pythonパッケージ（科学計算）
COPY code-executor/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# 実行ユーザー（rootでは実行しない）
RUN useradd -m -s /bin/bash executor
USER executor
WORKDIR /workspace

# エントリポイント
COPY code-executor/entrypoint.py /app/entrypoint.py
ENTRYPOINT ["python", "/app/entrypoint.py"]
```

### 9.2 requirements.txt

```
# code-executor/requirements.txt

# 科学計算基礎
numpy>=2.0.0
scipy>=1.13
pandas>=2.2
matplotlib>=3.9
scikit-learn>=1.5

# フィッティング・解析
lmfit>=1.3

# 画像処理
Pillow>=11.0

# ファイル形式
h5py>=3.11
openpyxl>=3.1

# 材料科学
pymatgen>=2024.6
ase>=3.23
periodictable>=1.7

# GCPクライアント（結果の読み書き用）
google-cloud-storage>=2.18
```

### 9.3 entrypoint.py

```python
#!/usr/bin/env python3
"""Cloud Run Jobs用エントリポイント。
環境変数からタスク情報を読み取り、ユーザーコードを実行する。
"""
import json
import os
import sys
import traceback
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    execution_id = os.environ.get("EXECUTION_ID", "unknown")
    input_bucket = os.environ.get("INPUT_BUCKET", "")
    output_bucket = os.environ.get("OUTPUT_BUCKET", "")
    workspace = Path("/workspace")

    # 1. Cloud Storage から入力ファイルをダウンロード
    if input_bucket:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(input_bucket.split("/")[0])
        prefix = "/".join(input_bucket.split("/")[1:])
        blobs = bucket.list_blobs(prefix=prefix)
        for blob in blobs:
            filename = blob.name.split("/")[-1]
            blob.download_to_filename(str(workspace / filename))

    # 2. ユーザーコードを読み込み
    code_path = workspace / "_code.py"
    if not code_path.exists():
        print(json.dumps({"error": "コードファイルが見つかりません", "results": {}, "images": []}))
        sys.exit(1)

    code = code_path.read_text()

    # 3. ファイルパス変数を準備
    file_vars = {}
    for f in workspace.iterdir():
        if not f.name.startswith("_") and f.is_file():
            var_name = f.name.replace(".", "_") + "_path"
            file_vars[var_name] = str(f)

    # file_path は最初のファイルを指す
    data_files = [f for f in workspace.iterdir() if not f.name.startswith("_") and f.is_file()]
    if data_files:
        file_vars["file_path"] = str(data_files[0])

    # 4. matplotlibのデフォルト設定
    matplotlib.rcParams.update({
        "figure.figsize": (8, 6),
        "figure.dpi": 150,
        "savefig.dpi": 150,
        "savefig.bbox": "tight",
        "savefig.facecolor": "white",
        "font.size": 12,
        "axes.unicode_minus": False,
    })

    # 5. 実行
    namespace = {**file_vars}
    try:
        exec(code, namespace)
    except Exception:
        error_tb = traceback.format_exc()
        output = {
            "error": error_tb,
            "results": {},
            "images": [],
        }
        print(json.dumps(output, default=str))

        # 結果をCloud Storageにアップロード
        if output_bucket:
            _upload_output(output_bucket, execution_id, output, [])
        sys.exit(0)  # エラーでも0で終了（結果は出力に含まれる）

    # 6. 画像の自動保存
    images = []
    for i, fig_num in enumerate(plt.get_fignums()):
        fig = plt.figure(fig_num)
        img_path = str(workspace / f"_img_{i}.png")
        fig.savefig(img_path, dpi=150, bbox_inches="tight", facecolor="white")
        images.append(img_path)
        plt.close(fig)

    # 7. result変数の収集
    result = namespace.get("result", {})

    output = {
        "results": result,
        "images": images,
        "error": None,
    }
    print(json.dumps(output, default=str))

    # 8. 結果をCloud Storageにアップロード
    if output_bucket:
        _upload_output(output_bucket, execution_id, output, images)


def _upload_output(output_bucket: str, execution_id: str, output: dict, image_paths: list[str]):
    """結果をCloud Storageにアップロードする。"""
    from google.cloud import storage
    client = storage.Client()
    bucket_name = output_bucket.split("/")[0]
    prefix = "/".join(output_bucket.split("/")[1:])
    bucket = client.bucket(bucket_name)

    # 結果JSON
    blob = bucket.blob(f"{prefix}/{execution_id}/result.json")
    blob.upload_from_string(
        json.dumps(output, default=str, ensure_ascii=False),
        content_type="application/json"
    )

    # 画像ファイル
    for img_path in image_paths:
        img_name = Path(img_path).name
        blob = bucket.blob(f"{prefix}/{execution_id}/{img_name}")
        blob.upload_from_filename(img_path, content_type="image/png")


if __name__ == "__main__":
    main()
```

---

## 10. コスト見積もり

### 10.1 Cloud Run Jobs（コード実行）

| 項目 | 単価 | 想定利用量/月 | 月額コスト |
|------|------|-------------|-----------|
| vCPU | $0.00002400/秒 | 2 vCPU x 30秒 x 500回 = 30,000秒 | $0.72 |
| メモリ | $0.00000250/GiB秒 | 2 GiB x 30秒 x 500回 = 30,000 GiB秒 | $0.08 |
| **小計** | | | **$0.80** |

### 10.2 Cloud Run Service（MCPサーバー）

| 項目 | 単価 | 想定利用量/月 | 月額コスト |
|------|------|-------------|-----------|
| vCPU | $0.00002400/秒 | 2 vCPU x 常時稼働なし (min=0) | ~$5.00 |
| メモリ | $0.00000250/GiB秒 | 1 GiB | ~$2.00 |
| リクエスト | $0.40/100万 | ~10,000 | ~$0.00 |
| **小計** | | | **~$7.00** |

### 10.3 Cloud Functions

| Function | 呼び出し回数/月 | メモリ | 実行時間 | 月額コスト |
|----------|---------------|--------|---------|-----------|
| embedding_generator | 500 | 256 MiB | 5秒 | ~$0.02 |
| nextcloud_poller | 8,640 (5分毎) | 512 MiB | 30秒 | ~$0.50 |
| preview_generator | 500 | 1024 MiB | 30秒 | ~$0.30 |
| notebook_summarizer | 1,000 | 512 MiB | 10秒 | ~$0.10 |
| **小計** | | | | **~$0.92** |

### 10.4 Firestore

| 項目 | 単価 | 想定利用量/月 | 月額コスト |
|------|------|-------------|-----------|
| ドキュメント読み取り | $0.036/10万 | 100,000 | $0.04 |
| ドキュメント書き込み | $0.108/10万 | 10,000 | $0.01 |
| ストレージ | $0.108/GiB | 1 GiB | $0.11 |
| **小計** | | | **~$0.16** |

### 10.5 Vertex AI

| 項目 | 単価 | 想定利用量/月 | 月額コスト |
|------|------|-------------|-----------|
| text-embedding-004 | $0.00002/1K文字 | 500回 x 500文字 | ~$0.01 |
| Gemini 2.0 Flash | $0.00002/1K入力 | 1,000回 x 2K文字 | ~$0.04 |
| **小計** | | | **~$0.05** |

### 10.6 合計

| カテゴリ | 月額コスト |
|---------|-----------|
| Cloud Run Jobs | $0.80 |
| Cloud Run Service | $7.00 |
| Cloud Functions | $0.92 |
| Firestore | $0.16 |
| Vertex AI | $0.05 |
| Cloud Storage (一時) | $0.10 |
| Secret Manager | $0.06 |
| **合計** | **~$9.09/月** |

**注意事項**:
- 上記は小規模チーム（5人、月500解析実行）を想定した見積もり
- Cloud Run Service の min-instances=0 設定により、未使用時のコストはほぼゼロ
- 無料枠（Cloud Run: 月200万リクエスト、Firestore: 日5万読み取り等）を適用すると更に削減可能
- Nextcloudのホスティング費用は含まない（既存環境を利用する前提）
