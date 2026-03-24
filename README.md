# labvault

**Python/Notebookで実験する研究室のための実験データ基盤。**

測定から解析までのコード・データ・条件が自動で記録され、蓄積されたデータをLLMが横断検索・解析する。

## 特徴

- **自動ログ**: `lab.new("XRD測定")` の1行で、以降のNotebookセル実行が全て自動記録される
- **ファイル管理**: `exp.add("data.ras")` でデータ保存。装置ファイル(.ras, .dm3等)からメタデータを自動抽出
- **ローカルファースト**: データは必ずローカルに先に保存。ネットワーク障害でもデータは消えない
- **テンプレート**: XRD/SEM/SQUID等の測定テンプレートで条件入力を標準化。必須項目チェック付き
- **装置制御対応**: `exp.log_value()` / `exp.log_event()` で.pyスクリプトからも記録可能
- **LLM横断検索**: MCP経由でClaude/Geminiが全実験データを検索・比較・解析
- **チーム共有**: 研究室メンバー全員のデータが1つの検索可能なプールに

## クイックスタート

```python
from labvault import Lab

lab = Lab()
exp = lab.new("Fe-Cr薄膜 XRD測定", template="XRD")

# 条件を記録
exp.conditions(target="Cu", voltage_kV=40, temperature_C=500)

# データを保存（.rasからメタデータを自動抽出）
exp.add("xrd_data.ras")

# 結果を記録
exp.results["lattice_a"] = 2.873
exp.results["phase"] = "BCC"

exp.status = "success"
```

## 装置制御スクリプトからの記録

```python
# instrument_control.py（Notebookではない通常の.py）
from labvault import Lab

lab = Lab()
exp = lab.new("スパッタ成膜", auto_log=False)
exp.conditions(temperature_C=500, pressure_Pa=0.5)

exp.log_event("deposition_start", "RF ON 200W")
for t in measure_temperature():
    exp.log_value("substrate_temperature_C", t)
exp.log_event("deposition_end", "RF OFF")

exp.add("process_log.csv")
```

## 別Notebookでの解析追記

```python
# analysis.ipynb（測定とは別のNotebook）
from labvault import Lab

lab = Lab()
exp = lab.get("AB3F", auto_log=True)  # 既存Recordに接続、セルログ記録開始
# → 以降のセルはAB3Fに記録される（セッション自動分離）

exp.results["fwhm"] = 0.429
exp.save("fit_plot", fig)
```

## インストール

```bash
pip install labvault

# GCPバックエンド付き
pip install labvault[gcp,nextcloud]

# 全部入り
pip install labvault[all]
```

## アーキテクチャ

```
labvault (このリポ)        = Python SDK（実験者が使う）
labvault-platform          = バックエンド（MCPサーバー + Cloud Functions + GCPインフラ）
```

| コンポーネント | 役割 |
|-------------|------|
| SDK (labvault) | Lab/Record API, IPython hooks, ローカルバッファ, パーサー |
| Firestore | メタデータ, Vector Search, セルログ |
| Nextcloud (大学提供) | バイナリファイル (30TB) |
| Cloud Functions Gen2 | MCPサーバー (8ツール), embedding生成 |
| Vertex AI | text-embedding-004 (セマンティック検索) |

月額GCPコスト: **~$1** (5人チーム, 月500操作)

## 設計ドキュメント

- [SDK Cookbook](docs/design/v10/04_sdk_cookbook.md) — 全APIのコード例
- [v10 概要](docs/design/v10/00_v10_overview.md) — アーキテクチャ・コスト
- [マイルストーン](docs/design/v10/05_milestones.md) — 実装計画
- [要件定義](docs/design/REQUIREMENTS.md) — R01-R22

## License

MIT
