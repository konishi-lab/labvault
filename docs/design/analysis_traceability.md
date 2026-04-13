# 解析トレーサビリティ設計

> 実験データから解析で得た results の出自（provenance）を完全に追跡し、同じ解析を再実行可能にする。

## 設計原則

- **Record が全ての中心** — 解析も Record として表現する。新しいデータモデルは追加しない
- **横断分析は一発で完結** — 測定 Record の results にキャッシュを書き戻し、`aggregate` がそのまま動く
- **正本は解析 Record** — 測定 Record の results はキャッシュ。出自は `__analysis_id` で追跡
- **コードもプロンプトも保存** — 「これで解析しろ」が明示できる

## データ構造

```
実験シリーズ (6HDKNS, type=experiment)
  └── 測定 Record (AB3F7K, type=measurement)
        conditions: {pulse_energy: 1e-5, material: "Al2O3"}
        results: {
            depth: 0.5,                        ← キャッシュ（横断分析用）
            depth__analysis_id: "XY9Z2P",      ← 出自の解析 Record ID
            roughness: 0.12,
            roughness__analysis_id: "XY9Z2P",
        }
        files: [surface.vk4, crater.png]       ← 生データ
        └── 解析 Record (XY9Z2P, type=analysis)
              conditions: {method: "vk4_depth", threshold: 0.1}
              results: {depth: 0.5, roughness: 0.12}   ← 正本
              files: [analyzer.py, heightmap.npy, depth_map.png]  ← コード + 出力
              status: "success"
```

### ルール

1. `run_analysis()` が書き戻す時、必ず `{key}__analysis_id` も書く
2. 正本は常に**解析 Record**。測定 Record の値はキャッシュ
3. 再解析で新しい解析 Record が作られたら、測定 Record のキャッシュも自動更新
4. 手動入力 `rec.results["depth"] = 0.5` は `__analysis_id` なし → 手動由来と判別可能
5. 解析 Record 削除時は測定 Record のキャッシュも削除

### 複数手法の競合

同じキー（depth）を異なる手法で解析した場合、最後に実行した解析が測定 Record に書き戻される。旧版の値は旧解析 Record に残るので、`compare` で比較可能。

```python
rec.run_analysis(method_a, "surface.vk4")  # depth=0.5, depth__analysis_id=AAA
rec.run_analysis(method_b, "surface.vk4")  # depth=0.6, depth__analysis_id=BBB ← 上書き
# compare(AAA, BBB) で旧版と比較可能
```

## SDK API

### 基本: 関数を渡して解析実行

```python
def analyze_depth(data: bytes, *, threshold: float = 0.1) -> dict:
    """VK4 データから深さと粗さを解析する。"""
    import numpy as np
    heightmap = parse_vk4(data)
    return {
        "results": {"depth": float(np.min(heightmap)), "roughness": float(np.std(heightmap))},
        "files": {"heightmap.npy": heightmap.tobytes(), "depth_map.png": render_colormap(heightmap)},
    }

meas = lab.get("AB3F7K")
meas.run_analysis(analyze_depth, "surface.vk4", params={"threshold": 0.1})
```

`run_analysis()` の内部処理:

1. `inspect.getsource(fn)` で関数ソースコードを取得
2. 解析 Record を子として作成 (`type="analysis"`)
3. 入力ファイルからデータを取得し、関数を実行
4. 解析 Record に results + output files + コード(analyzer.py) を保存
5. 測定 Record の results にキャッシュ + `__analysis_id` を書き戻す

### コード文字列を直接渡す

```python
code = """
import numpy as np
def analyze(data, threshold=0.1):
    heightmap = parse_vk4(data)
    return {"results": {"depth": float(np.min(heightmap))}}
"""
meas.run_analysis(code, "surface.vk4", params={"threshold": 0.1})
```

### LLM プロンプトによる解析

```python
meas.run_analysis(
    "claude_vision",
    "crater.png",
    params={"prompt": "クレーター直径をum単位で測定して", "model": "claude-sonnet-4-20250514"},
)
```

コードもプロンプトも「解析手順を記述したテキスト」として統一的に扱う。

| analyzer_type | source (files) | 再実行方法 |
|---------------|----------------|-----------|
| `python` | analyzer.py (関数ソース) | 保存されたコードを実行 |
| `llm` | prompt.txt + モデル名 | 同じプロンプト + モデルで API 呼び出し |

### バッチ処理

```python
parent = lab.get("6HDKNS")
for meas in parent.children():
    meas.run_analysis(analyze_depth, "measure3d_plux.zip", params={"threshold": 0.1})
# → 1,644件全てに解析 Record + results 書き戻し + output files
```

### 再実行

```python
meas.rerun_analysis("depth")
# → depth__analysis_id から解析 Record を取得
# → 同じ method + params + source_file で新しい解析 Record を作成
# → 測定 Record のキャッシュを新しい値で更新
```

### 手動解析（段階的に使う場合）

```python
meas = lab.get("AB3F7K")
ana = meas.sub("depth analysis v1", type="analysis")
ana.conditions(method="vk4_depth", threshold=0.1)

data = meas.get_data("surface.vk4")
depth = analyze_depth(data, threshold=0.1)

ana.results["depth"] = depth
ana.save("heightmap", heightmap_array)
ana.add("analyzer.py")
ana.status = "success"

# 手動で書き戻す場合
meas.results["depth"] = depth
```

## 解析関数の返り値規約

```python
def my_analysis(data: bytes, **params) -> dict:
    return {
        "results": {"key1": value1, "key2": value2},      # 必須: 結果値
        "files": {"output.npy": bytes, "plot.png": bytes}, # 任意: 出力ファイル
    }
```

- `results`: dict[str, scalar] — 測定 Record に書き戻される
- `files`: dict[str, bytes] — 解析 Record の files に保存される

## 解析 Record の Firestore 構造

```json
{
    "id": "XY9Z2P",
    "title": "analysis:vk4_depth",
    "type": "analysis",
    "status": "success",
    "parent_id": "AB3F7K",
    "conditions": {
        "method": "vk4_depth",
        "threshold": 0.1,
        "analyzer_type": "python",
        "source_file": "surface.vk4",
        "source_fingerprint": "abc123...(先頭64KB sha256 + size)",
        "software_version": "numpy==1.26.4"
    },
    "results": {
        "depth": 0.5,
        "roughness": 0.12
    },
    "created_by": "konishi",
    "created_at": "2026-04-13T10:30:00+00:00"
}
```

ファイル (Nextcloud):
- `analyzer.py` — 関数ソースコード (or prompt.txt)
- `heightmap.npy` — 出力ファイル
- `depth_map.png` — 出力ファイル

## 横断分析のフロー

### 「pulse_energy と depth の関係は？」

```
aggregate(key="depth", group_by="pulse_energy", parent_id="6HDKNS")
→ 測定 Record の results.depth と conditions.pulse_energy で一発回答
```

### 「depth はどうやって得られた？」

```
get_detail("AB3F7K")
→ results.depth=0.5, results.depth__analysis_id="XY9Z2P"

get_detail("XY9Z2P")
→ conditions: {method: "vk4_depth", threshold: 0.1}
→ files: [analyzer.py, heightmap.npy]

data_preview("XY9Z2P", "analyzer.py")
→ コード全文を LLM が読んで説明
```

### 「手法 A と B の結果を比較して」

```
search(parent_id="AB3F7K", record_type="analysis")
→ [解析Record A (XY9Z2P), 解析Record B (PQ7R3S)]

compare(["XY9Z2P", "PQ7R3S"])
→ 条件の差異 (threshold: 0.1 vs 0.05) と結果の差異 (depth: 0.5 vs 0.48)
```

### 「前処理の出力を使って更に解析して」

```python
# 前処理: VK4 → heightmap
meas.run_analysis(preprocess_vk4, "surface.vk4")
# → 解析 Record に heightmap.npy が生成される

# 後段解析: heightmap → crater 特徴量
meas.run_analysis(analyze_crater, "heightmap.npy", params={"method": "gaussian_fit"})
# → input が前段の output。チェーン追跡可能
```

## MCP / CLI への影響

### 既存ツールの変更

| ツール | 変更 |
|--------|------|
| `aggregate` | `record_type` パラメータ追加（analysis を除外 or 限定） |
| `get_detail` | `__analysis_id` 付きの results を返す（変更なし、フィールドが増えるだけ） |

### 新規ツール/コマンドは不要

- 解析コードの確認: `data_preview(解析Record, "analyzer.py")`
- 解析手法の検索: `search(record_type="analysis", conditions={"method": "vk4_depth"})`
- 解析結果の比較: `compare([解析RecordA, 解析RecordB])`
- 解析結果の集計: `aggregate(key="depth", parent_id=測定Record)`

全て既存ツールで対応可能。

### CLI

```bash
# 解析結果の横断集計
labvault aggregate depth --group-by pulse_energy -p 6HDKNS

# 解析 Record の検索
labvault search -t analysis -c "method=vk4_depth"

# 解析コードの確認（将来）
labvault show XY9Z2P --files
```

## 実装フェーズ

### Phase 1: Record.run_analysis() の基盤

1. `Record.run_analysis(fn, source_file, params=)` の実装
   - `inspect.getsource()` でコード取得
   - 解析 Record (type=analysis) の自動作成
   - results + files の保存
   - 測定 Record への書き戻し + `__analysis_id`
2. 解析関数の返り値規約 (`results` + `files`)
3. テスト追加

### Phase 2: 再実行 + バッチ

1. `Record.rerun_analysis(key)` の実装
2. バッチ処理のユーティリティ
3. `source_fingerprint` (先頭64KB sha256 + size)

### Phase 3: MCP / CLI 対応

1. `aggregate` に `record_type` フィルタ追加
2. `get_detail` の `children_summary` に解析情報を含める
3. CLI の `labvault search -t analysis` 対応

### Phase 4: LLM 解析統合

1. `analyzer_type="llm"` のサポート
2. Claude Vision API 呼び出し (REST 直接、Anthropic SDK はオプショナル)
3. プロンプト + レスポンスの保存 (SQLite バッファ → Nextcloud)

## 設計判断の根拠

### なぜ解析を Record にするのか

- スキーマ変更不要。既存の conditions/results/files/parent_id がそのまま使える
- 既存の MCP 7ツール + CLI 16コマンドが解析にもそのまま動く
- 再解析 = 新 Record。バージョニングが自然に解決する
- LLM が `search(type="analysis")` で解析履歴を照会できる

### なぜ書き戻すのか

- `aggregate(key="depth", group_by="pulse_energy")` が一発で動く
- conditions（測定 Record）と results（解析 Record）の分断を防ぐ
- LLM の横断分析で N+1 問題が発生しない

### なぜ `__analysis_id` を付けるのか

- 正本（解析 Record）とキャッシュ（測定 Record）の関係が明確
- 手動入力と解析由来を区別できる
- トレーサビリティ: 値 → 解析 Record → コード + パラメータ の追跡が可能
