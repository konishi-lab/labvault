# MDG (Measurement Data Gateway) 統合設計

## MDG とは

東京大学物性研究所 (ISSP) の実験データ取得・配信プラットフォーム。
`brokersystem` ライブラリ (Python) を通じてデータにアクセスする。
エージェント (実験装置/シミュレータ) とクライアントをブローカーが仲介する。

- GitHub: https://github.com/utokyo-issp-koblab/brokersystem
- ブローカーURL: `https://mdg2.gigalixirapp.com`
- 認証: トークンベース (label ごとに発行)
- ライブラリバージョン: 0.3.2 (ローカルリポからインストール)

## 利用可能なエージェント一覧 (2026-04-07 調査)

`broker.board()` で取得。30エージェント中、labvault に関連するものを抜粋：

### active (現在利用可能)

| ID | 名前 | タイプ | 所有者 | 説明 |
|---|---|---|---|---|
| `282bd7d6-...` | 半導体製造業界コンサル | refer | 谷 峻太郎 (東大物性研) | 半導体のことなら何でも。質問→回答+画像 |
| `ccffcb8a-...` | 半導体製造図版データベース | refer | 谷 峻太郎 (東大物性研) | 半導体の図版検索 |

### inactive (停止中、施設側で起動が必要)

| ID | 名前 | タイプ | 所有者 | 説明 |
|---|---|---|---|---|
| `254a811f-...` | ABF穴あけシミュレータ | predict | 乙津 聡夫 (東大物性研) | レーザー加工のパルス数計算 |
| `0b76e656-...` | 大容量結果ファイル取得 | refer | OFFICIAL (TACMI) | ページングで大容量ファイルダウンロード |
| `99d47aa1-...` | **MDG data taking** | **daq** | 中里 智治 (東大物性研) | レーザー加工のデータ取得 (ABF/ニッケル/銅) |
| `591707c3-...` | **MDG data taking SLM** | **daq** | 中里 智治 (東大物性研) | SLM レーザー加工 (シリコン/モリブデン/銅) |

### MDG data taking エージェントの詳細

研究室のレーザー加工実験に最も関連するエージェント。

**入力パラメータ:**
| パラメータ | 型 | 単位 | 範囲/選択肢 | デフォルト |
|---|---|---|---|---|
| material | choice | - | ABF, ニッケル, 銅 | - |
| pulse_energy | number | uJ | 0.3〜3.0 | 0.5 |
| repeat | number | - | 1〜100 | 1 |
| repetition_rate | number | kHz | 1〜100 | 1 |
| zpos | number | um | -100〜100 | 0 |

**条件:** wavelength (nm)

**出力:**
| パラメータ | 型 | 単位 |
|---|---|---|
| mission_id | string | - |
| max_detected_depth | number | um |
| image | image | - |

## brokersystem の使い方

### クライアントとして接続

```python
from brokersystem import Broker

broker = Broker(
    broker_url="https://mdg2.gigalixirapp.com",
    auth="db1cfc13-d02d-40f1-8056-2d4e80c14380",
)

# エージェント一覧
board = broker.board()
for agent in board["agents"]:
    print(f'{agent["name"]}: active={agent["active"]}')
```

### データ取得 (ask = negotiate + contract + get_result)

```python
result = broker.ask(
    agent_id="99d47aa1-443a-4e85-9e8d-96033c3ad026",  # MDG data taking
    request={
        "material": "ABF",
        "pulse_energy": 0.5,
        "repeat": 1,
        "repetition_rate": 1,
        "zpos": 0,
    },
)
# result["result"]["image"] → 画像ファイル ID
# result["result"]["max_detected_depth"] → 加工深さ (um)
# result["result"]["mission_id"] → ミッション ID
```

### 大容量ファイルのページングダウンロード

```python
import base64

PAGER_AGENT_ID = "0b76e656-a4ab-458b-b6ed-7014f68c2f38"

response = broker.ask(
    PAGER_AGENT_ID,
    {"transfer_id": "f31229f0806129bbfdfb", "page_index": 0},
)
result = response["result"]
data = base64.b64decode(result["page_base64"])
total_pages = result["total_pages"]
file_name = result["file_name"]
```

## labvault への統合方針

### 推奨: 段階的統合

#### Phase 1: インポートスクリプト (最初)

MDG からデータを取得して labvault レコードとして登録するスクリプト。

```python
# scripts/import_mdg.py
from brokersystem import Broker
from labvault import Lab

broker = Broker(broker_url=BROKER_URL, auth=MDG_TOKEN)
lab = Lab()

# MDG で測定実行
result = broker.ask(
    "99d47aa1-...",
    {"material": "ABF", "pulse_energy": 0.5, ...},
)

# labvault に登録
exp = lab.new("MDG laser processing", tags=["MDG", "ABF"])
exp.conditions(
    material="ABF",
    pulse_energy_uJ=0.5,
    repetition_rate_kHz=1,
    source="MDG",
    mdg_mission_id=result["result"]["mission_id"],
)
exp.results["max_detected_depth_um"] = result["result"]["max_detected_depth"]
# 画像を保存 (broker.get_file で取得)
```

#### Phase 2: MCP ツール (将来)

Claude から「MDG でデータを取得して」が可能に。

```python
@mcp.tool(description="MDG で実験データを取得して labvault に登録する")
def mdg_acquire(material: str, pulse_energy: float, ...) -> dict:
    result = broker.ask(agent_id, request)
    exp = lab.new(...)
    return {"record_id": exp.id, "depth": result["max_detected_depth"]}
```

#### Phase 3: Web UI 統合 (将来)

Web UI に MDG エージェント一覧 + 測定リクエストフォームを追加。

## 調査結果まとめ

### 確認済み
- ブローカー接続: OK (トークン認証成功)
- エージェント一覧取得: OK (`broker.board()` で30エージェント)
- API 構造: negotiate → contract → result の3段階プロトコル

### 現状の制約
- MDG data taking エージェントは inactive → 施設側で起動が必要
- 大容量ファイル取得エージェントも inactive
- active なのはコンサル系エージェント (半導体製造業界) のみ

### 次のステップ
1. 施設担当者に MDG data taking エージェントの起動を依頼
2. active なエージェントで ask() の動作確認
3. インポートスクリプトのプロトタイプ作成

## 環境変数

```bash
# .env に追加
MDG_BROKER_URL=https://mdg2.gigalixirapp.com
MDG_TOKEN=db1cfc13-d02d-40f1-8056-2d4e80c14380
```
