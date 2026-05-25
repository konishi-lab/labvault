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

## apply 手順

`gcloud firestore` の indexes コマンドを使う。`labvault` database に対して:

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
firebase deploy --only firestore:indexes --project klab-laser-process
```

で `firestore.indexes.json` を一括 apply する (Firebase Console から
`labvault` database を選んで firebase.json の database 設定を `labvault`
に向けるか、`firebase use --add` で別の Firestore database を切替える)。

`firebase.json` がまだ無いので、initial 1 回だけ:

```bash
firebase init firestore   # firestore.indexes.json を選んで rules はスキップ
firebase deploy --only firestore:indexes
```

## 確認

```bash
gcloud firestore indexes composite list \
  --database=labvault \
  --project=klab-laser-process
```

`State: READY` になっていれば使える状態。`Building` の間はクエリが
未インデックスエラーで弾かれる可能性あり。レコード数次第で数分〜数十分。

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
