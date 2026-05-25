# Firestore 複合インデックス

`firestore.indexes.json` で宣言された複合インデックスは、template の
`indexed_fields` を top-level field (`idx_<key>`) に昇格させた上で
`deleted_at` + `idx_<key>` + `updated_at DESC` の where + order
を効率化するためのもの。

## 何のために必要か

PR #11 で `Record._to_dict()` が `idx_target / idx_method / ...`
など template の `indexed_fields` を top-level に書き出すようになった。
これにより SDK の `Lab.search()` / `Lab.list()` は `conditions={"target":
"Cu"}` のような scalar 等値クエリを Firestore の where 句に
**push down** する (PR #14 で実装)。

例えば「XRD の `target == "Cu"` で最新 20 件」は内部的に:

```python
q.where("deleted_at", "==", None)\
 .where("idx_target", "==", "Cu")\
 .order_by("updated_at", direction=DESCENDING)\
 .limit(20)
```

となる。Firestore はこの「等値フィルタ + 別フィールドでの順序付け」
を実行するために対応する複合インデックスを必要とする。

宣言が無いと Firestore は実行時に "The query requires an index. You can
create it here: https://console.firebase.google.com/..." というエラーを
返す。エラーリンクから個別に作っても良いが、CI / 別環境に展開するときに
辛いので `firestore.indexes.json` で一括宣言しておく。

## apply 手順 (推奨: gcloud スクリプト)

firebase-tools v14 系では multi-database 配列形式の `firestore.indexes.json`
で `firebase deploy --only firestore:indexes:<db>` が
`Cannot read properties of undefined (reading 'map')` で落ちる既知の
不具合がある。当面は同梱の gcloud スクリプトを使う:

```bash
./scripts/apply_firestore_indexes.sh
```

新規 8 個 (`idx_<key>` 対応) のみ async submit する。既存と等価な index は
ALREADY_EXISTS で skip。既存 index は触らないので overwrite 事故は起きない。

State 確認:

```bash
gcloud firestore indexes composite list \
  --project=klab-laser-process --database=labvault
```

## apply 手順 (将来: firebase CLI)

firebase-tools の bug が直ったら、`firestore.indexes.json` を一括 apply
する方が宣言性が高い。`labvault` database に対して:

```bash
gcloud firestore indexes composite create \
  --collection-group=records \
  --query-scope=COLLECTION \
  --field-config=field-path=deleted_at,order=ascending \
  --field-config=field-path=idx_target,order=ascending \
  --field-config=field-path=updated_at,order=descending \
  --database=labvault \
  --project=klab-laser-process
```

…のように 1 個ずつ叩くのは現実的でないので、firebase-tools が入っているなら

```bash
firebase deploy --only firestore:indexes
```

で `firestore.indexes.json` を一括 apply する。リポジトリ root に
すでに `firebase.json` と `.firebaserc` がコミットされており、labvault
database (default ではない名前付き database) を指している:

```jsonc
// firebase.json
{
  "firestore": [
    { "database": "labvault", "indexes": "firestore.indexes.json" }
  ]
}
```

```jsonc
// .firebaserc
{
  "projects": { "default": "klab-laser-process" }
}
```

別 project を扱うなら `--project` で上書き:

```bash
firebase deploy --only firestore:indexes --project klab-laser-process
```

`firebase` CLI が無い場合は `npm i -g firebase-tools` か
`brew install firebase-cli` で導入し、`firebase login` 済の Google
account が GCP project の Firebase / Editor 権限を持っている必要がある。

## 確認

```bash
gcloud firestore indexes composite list \
  --database=labvault \
  --project=klab-laser-process
```

`State: READY` になっていれば使える状態。`Building` の間はクエリが
未インデックスエラーで弾かれる可能性あり。レコード数次第で数分〜数十分。

## 重要: deploy は overwrite

`firebase deploy --only firestore:indexes` は差分 deploy ではなく、
**宣言ファイル = 本番のあるべき姿** として扱う overwrite なので、
`firestore.indexes.json` に書いていない index は (確認プロンプト後に)
**削除される**。

特に Firestore Console や `gcloud` から手動で追加した index、
vector index (`embedding`) などは忘れがちなので、追記漏れに注意する。

新しい index を追加する前に必ず:

```bash
firebase firestore:indexes --database labvault
```

で現状を取得し、`firestore.indexes.json` の内容と diff を取って漏れが
無いか確認する。差分があれば本番が真なので取り込んでからコミットする。

`firebase deploy` 実行時には「これらが削除されます」の確認プロンプトが
出るので、想定外の削除リストがあれば中断する。

## 追加するとき

新しい template を作って `indexed_fields` を追加した場合、対応する
複合インデックスも `firestore.indexes.json` に追記する。形式は:

```jsonc
{
  "collectionGroup": "records",
  "queryScope": "COLLECTION",
  "fields": [
    { "fieldPath": "deleted_at", "order": "ASCENDING" },
    { "fieldPath": "idx_<new_key>", "order": "ASCENDING" },
    { "fieldPath": "updated_at", "order": "DESCENDING" }
  ]
}
```

parent_id 絞り込みパターンが必要な場合は `parent_id` を間に入れた
4-field index を追加する。

## ローカル emulator

ローカル開発で複合インデックス必要なクエリを試したい場合、
`firebase emulators:start --only firestore` で `firestore.indexes.json`
を読み込ませると emulator が同じ振る舞いをする (本番に何も flush
しないので安全)。
