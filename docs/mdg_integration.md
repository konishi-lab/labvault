# MDG (Measurement Data Gateway) 統合設計

## MDG とは

東京大学物性研究所 (ISSP) の実験データ取得・配信プラットフォーム。
`brokersystem` ライブラリ (Python) を通じてデータにアクセスする。
エージェント (実験装置/シミュレータ) とクライアントをブローカーが仲介する。

- GitHub: https://github.com/utokyo-issp-koblab/brokersystem
- ブローカーURL: `https://mdg2.gigalixirapp.com`
- 認証: トークンベース (label ごとに発行)
- ライブラリバージョン: 0.3.2

## Active エージェント一覧 (2026-04-13 調査)

全35エージェント中、15エージェントが active。主要なもの：

### 実験装置系 (daq)

| ID | 名前 | 説明 | 状態 |
|---|---|---|---|
| `99d47aa1-...` | MDG data taking | レーザー加工のデータ取得 (ABF/ニッケル/銅) | **active** |
| `591707c3-...` | MDG data taking SLM | SLM レーザー加工 (シリコン/モリブデン/銅) | **active** |
| `d6f7f292-...` | carbide1 照射前後表面形状評価 | observe/shoot/observe フロー | **active** |
| `17664db6-...` | carbide1 一括実行 | Cartesian グリッド探索 | **active** |
| `fdc1c45c-...` | carbide1 一括実行の結果取得 | 完了セッションの結果取得 | **active** |
| `b086434b-...` | carbide1 結果取得 | 個別トライアルの結果取得 | **active** |
| `1be80a07-...` | MDG Status Monitor | 装置ステータス監視 | **active** |

### シミュレーション系 (predict)

| ID | 名前 | 説明 | 状態 |
|---|---|---|---|
| `30915ac5-...` | Local Fluence Model | 最適加工レシピ提案 (除去速度モデル) | **active** |
| `4cf21ae3-...` | ガラス深穴シミュレーター | パルスエネルギー一定の穴あけ (0-250uJ) | **active** |
| `39d31082-...` | 白色光発生シミュレーション | sech型パルスの白色スペクトル予測 | **active** |
| `ffc6d7ce-...` | Plot Cosine | cos(a*x+b) のプロット (テスト用) | **active** |

### データ取得確認済み (2026-04-13)

**Local Fluence Model** でデータ取得に成功：
```python
result = broker.ask("30915ac5-...", {
    "spot_size": 50, "material": "copper",
    "max_pulse_energy": 40, "max_power": 10, "depth": 100
})
# → 13パターンの最適加工レシピ (repetition_rate, pulse_energy, depth 等)
```

### carbide1 照射前後表面形状評価

最も データ量が多いエージェント。出力に画像・3D形状データを含む。

**入力 (単体実行):**
| パラメータ | 型 | 説明 |
|---|---|---|
| cassette_id | number | カセット ID |
| session_name | string | セッション名 |
| location_id | number | 照射位置 ID |
| pulseenergy | number | パルスエネルギー |
| pulsenumber | number | パルス数 |
| pulseduration | number | パルス幅 |
| defocus | number | デフォーカス量 |

**出力:**
| パラメータ | 型 | 説明 |
|---|---|---|
| take_image_before | image | 照射前の光学画像 |
| take_image_after | image | 照射後の光学画像 |
| take_image_comparison | image | 比較画像 |
| measure3d_before_plot | image | 照射前の3D形状 |
| measure3d_after_plot | image | 照射後の3D形状 |
| measure3d_comparison | image | 3D形状比較 |
| parameters_json | - | 処理パラメータ |

**一括実行の結果取得 (session_name で全トライアル取得):**
- trial_table: 全トライアルの条件・結果テーブル
- all_png_zip: 全画像の ZIP
- all_plux_zip: 全 PLUX データの ZIP

## labvault への統合方針

### Phase 1: MCP ツールとして追加 (推奨)

Claude から「MDG で実験して」「シミュレーションして」が可能に。

```python
@mcp.tool(description="MDG エージェントにリクエストを送信する")
def mdg_request(agent_name: str, params: dict) -> dict:
    broker = Broker(broker_url=BROKER_URL, auth=MDG_TOKEN)
    board = broker.board()
    # agent_name → agent_id のマッピング
    agent = next(a for a in board["agents"] if a["name"] == agent_name)
    return broker.ask(agent["id"], params)
```

### Phase 2: 結果の labvault レコード自動登録

MDG の結果を labvault に自動保存：

```python
result = broker.ask(agent_id, params)
exp = lab.new("MDG carbide1 照射", tags=["MDG", "carbide1"])
exp.conditions(**params)
exp.results["max_detected_depth_um"] = result["result"].get("max_detected_depth")
# 画像をファイルとして保存
if "take_image_after" in result["result"]:
    image_data = broker.get_file(f"files/{result['result']['take_image_after']}")
    exp.add(image_data.content, name="take_image_after.png")
```

### Phase 3: Web UI に MDG パネル

- エージェント一覧表示
- パラメータ入力フォーム (エージェントの input schema から自動生成)
- 結果表示 (画像プレビュー + テーブル)

## 環境変数

```bash
MDG_BROKER_URL=https://mdg2.gigalixirapp.com
MDG_TOKEN=db1cfc13-d02d-40f1-8056-2d4e80c14380
```

## 次のステップ

1. ~~施設担当者に MDG data taking エージェントの起動を依頼~~ → **active 確認済み**
2. carbide1 の既存セッション名を確認して結果取得テスト
3. MCP ツールとして labvault に統合
4. 結果の自動レコード登録
