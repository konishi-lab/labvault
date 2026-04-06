# labvault examples

labvault をインストールしたらすぐ試せるサンプル集です。
すべて InMemoryBackend で動くため、Firestore や Nextcloud などの外部サービスは不要です。

## ファイル一覧

| ファイル | 形式 | 内容 |
|---------|------|------|
| `01_quickstart.ipynb` | Notebook | レコード作成・条件設定・ファイル保存/取得・結果記録 |
| `02_instrument_script.py` | Script | 装置制御スクリプトでの `log_value` / `log_event` パターン |
| `03_search_and_organize.ipynb` | Notebook | 検索・タグ・子レコード・ディレクトリ一括追加・削除/復元 |

## 動かし方

```bash
# インストール
pip install -e .

# Notebook
jupyter lab examples/

# スクリプト
python examples/02_instrument_script.py
```
