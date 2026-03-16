# メタデータDB選定: なぜFirestoreなのか（+ 他の選択肢）

## そもそもDBに何を入れるか

```
Nextcloud (30TB無料) → バイナリ実体（npy, 画像, コード, etc.）
DB (GCP)            → メタデータ、検索インデックス、embedding
```

DBに入るのは「軽い情報」だけ:
- 実験のメタデータ（タイトル、条件、タグ、ステータス、日時、作成者）
- ファイルの参照情報（Nextcloud上のパス、ファイルサイズ等）
- 検索用embedding（768次元のベクトル）
- 子レコードの階層構造

データ量目安: 1レコード = 数KB。数万件 = 数百MB程度。

---

## 候補の比較

### 1. Cloud Firestore（v2で選定）

**何か**: GCPのサーバーレスNoSQL DB。JSONドキュメントを階層的に格納。

```
teams/konishi-lab/experiments/ab3f
  → {title: "XRD測定", tags: [...], conditions: {...}, embedding: [...]}
```

| 項目 | 評価 |
|------|------|
| 階層データ | ◎ サブコレクションで親子レコードを自然に表現 |
| スキーマ柔軟性 | ◎ スキーマレス。条件フィールドを自由に追加可能 |
| ベクトル検索 | ○ Firestore Vector Search（2024年GA）で組み込み対応 |
| 全文検索 | △ 複合インデックスのみ。日本語全文検索は弱い |
| 運用負荷 | ◎ サーバーレス。パッチ/バックアップ/スケーリング全自動 |
| コスト | ◎ 数万件で月$5-20。無料枠あり |
| リアルタイム | ◎ リアルタイムリスナー（チーム共有に有利） |
| Python SDK | ○ google-cloud-firestore（公式） |
| 学習コスト | ○ NoSQLの概念理解が必要だがドキュメントは豊富 |

**メリット**: サーバーレスで運用ゼロ。階層データに強い。安い。
**デメリット**: 全文検索が弱い。複雑なクエリ（JOIN相当）ができない。

---

### 2. Cloud SQL（PostgreSQL + pgvector）

**何か**: GCPのマネージドRDB。SQLが使える。

```sql
SELECT * FROM experiments
WHERE team = 'konishi-lab'
  AND tags @> '{XRD}'
  AND (conditions->>'temperature_C')::float > 300
ORDER BY embedding <-> query_embedding
LIMIT 20;
```

| 項目 | 評価 |
|------|------|
| 階層データ | △ 再帰CTE or adjacency listで表現可能だが自然ではない |
| スキーマ柔軟性 | ○ JSONB型で柔軟なメタデータを格納可能 |
| ベクトル検索 | ○ pgvector拡張でHNSW/IVFFlat対応 |
| 全文検索 | ◎ pg_trgm + GINインデックスで日本語も対応可能 |
| 運用負荷 | △ インスタンス管理必要（パッチ、バックアップ設定、接続数管理） |
| コスト | △ 最小インスタンスで月$50-100（常時起動） |
| リアルタイム | △ pg_notify/ポーリング（Firestoreほど簡単ではない） |
| Python SDK | ◎ psycopg2/SQLAlchemy。エコシステム最大 |
| 学習コスト | ◎ SQL（最も普及した技術） |

**メリット**: SQLの表現力。全文検索が強い。エコシステムが広大。
**デメリット**: サーバー管理が必要。最低月$50。常時稼働コスト。

---

### 3. AlloyDB（PostgreSQL互換 + AI統合）

**何か**: GCPの高性能PostgreSQL互換DB。pgvector組み込み。

| 項目 | 評価 |
|------|------|
| 全般 | Cloud SQLと同等だが高性能 |
| ベクトル検索 | ◎ ScaNN統合で高速 |
| コスト | ✗ 月$200+。研究室予算には厳しい |

→ **コストで脱落。** 大企業向け。

---

### 4. Supabase（PostgreSQL + Auth + リアルタイム）

**何か**: Firebase的な体験をPostgreSQLで実現するBaaS。

| 項目 | 評価 |
|------|------|
| 階層データ | △ PostgreSQLベースなので同じ |
| ベクトル検索 | ○ pgvector対応 |
| 全文検索 | ◎ PostgreSQLのFTS |
| 運用負荷 | ◎ マネージド。Firestoreに近い体験 |
| コスト | ◎ 無料プランあり。Pro $25/月 |
| リアルタイム | ◎ Realtime subscriptions |
| 認証 | ◎ 組み込みAuth（メール、OAuth） |
| Python SDK | ○ supabase-py |

**メリット**: PostgreSQLの全文検索力 + Firebaseの手軽さ。安い。
**デメリット**: GCPではなくサードパーティ依存。GCPとの統合が手動。

---

### 5. SQLite + sqlite-vec（ローカルDB）

**何か**: サーバー不要の組み込みDB。

| 項目 | 評価 |
|------|------|
| 運用負荷 | ◎ ゼロ。ファイル1つ |
| コスト | ◎ 無料 |
| ベクトル検索 | △ sqlite-vec（まだ成熟途上） |
| チーム共有 | ✗ ローカル専用。共有にはサーバーが必要 |

→ **オフラインキャッシュとしては最適。メインDBとしてはチーム共有要件を満たさない。**

---

## 判断のポイント

### あなたの要件に照らすと

| 要件 | Firestore | Cloud SQL | Supabase |
|------|-----------|-----------|----------|
| チーム共有（リアルタイム） | ◎ | △ | ◎ |
| 階層データ（親子レコード） | ◎ | △ | △ |
| スキーマ柔軟性（条件は実験ごとに異なる） | ◎ | ○ | ○ |
| ベクトル検索（セマンティック検索） | ○ | ○ | ○ |
| 全文検索（日本語） | △ | ◎ | ◎ |
| 運用ゼロ | ◎ | △ | ◎ |
| GCP内完結 | ◎ | ◎ | ✗ |
| コスト（月額） | $5-20 | $50-100 | $0-25 |
| 数万件の検索速度 | ◎ | ◎ | ◎ |

### Firestoreを選んだ理由

1. **階層データが最も自然**: 実験→子レコード→孫レコードの構造が、サブコレクションでそのまま表現できる。RDB（PostgreSQL）だと再帰CTE等が必要で不自然。

2. **スキーマレス**: 物性実験と化学実験で条件フィールドが全く異なる。Firestoreならフィールドを自由に追加できる。PostgreSQLでもJSONB型で可能だが、Firestoreのほうが設計思想として合っている。

3. **運用ゼロ**: 研究室にDB管理者はいない。サーバーレスで勝手にスケールし、バックアップも自動。

4. **安い**: 数万件規模なら月$5-20。Cloud SQLは最低$50。

5. **リアルタイム**: チームメンバーがデータを追加したら即座に他のメンバーから見える。

### Firestoreの弱点と対策

| 弱点 | 対策 |
|------|------|
| 全文検索が弱い | Vertex AI embeddingによるセマンティック検索で代替。「BCC 格子定数」のような検索はベクトル検索のほうが実は適している |
| 複雑なクエリ（JOIN）ができない | データモデルを非正規化（1ドキュメントに関連情報を含める）。必要に応じてBigQueryにエクスポートして分析 |
| ベンダーロック | エクスポート機能で対策。Firestore → JSON → 他のDBに移行可能 |

---

## LLMとの相性

LLMがDBを使う場面は3つ:

```
① 検索: 「Fe-Cr合金のXRD実験を探して」 → DBにクエリ
② 取得: 「実験ab3fの詳細を見せて」    → DBからドキュメント取得
③ 解析: 取得したデータを読んで回答     → LLMのコンテキストに渡す
```

### ① 検索フェーズ: LLMがクエリを組み立てる

LLMはMCPサーバーのツールを呼び出してDBにクエリを投げる。
このとき「LLMがクエリを正しく組み立てられるか」が相性の核心。

**Firestore:**
```python
# MCPツール内部でLLMのリクエストをFirestoreクエリに変換
db.collection("experiments") \
  .where("tags", "array_contains", "XRD") \
  .where("conditions.temperature_C", ">", 300) \
  .find_nearest(vector_field="embedding", query_vector=q, limit=20)
```
- 構造化フィルタ + ベクトル検索を**1クエリで同時実行**できる
- ただしFirestoreのクエリ言語はSQLより制約が多い（複合条件にインデックス必要）
- MCPツール側でクエリを組み立てるので、LLM自身がFirestoreの文法を知る必要はない

**PostgreSQL (Cloud SQL / Supabase):**
```sql
SELECT * FROM experiments
WHERE tags @> '{XRD}'
  AND (conditions->>'temperature_C')::float > 300
ORDER BY embedding <-> $query_vector
LIMIT 20;
```
- SQLはLLMが最も得意な言語の1つ（学習データに大量のSQLがある）
- **LLMに直接SQLを生成させる**ことも可能（text-to-SQL）
- 複雑な集約・JOIN・ウィンドウ関数も自在

**比較:**

| 観点 | Firestore | PostgreSQL |
|------|-----------|------------|
| LLMがクエリを直接書ける | △（独自API、LLMの学習データに少ない） | ◎（SQLはLLMの得意技） |
| MCPツール経由なら | ◎（ツール内部で変換するので問題なし） | ◎ |
| ハイブリッド検索（構造化+ベクトル） | ◎（1クエリ） | ◎（pgvector + WHERE） |
| 複雑な分析クエリ | △（集約が弱い） | ◎（GROUP BY, JOIN, CTE等） |

**ポイント**: MCPサーバーを挟む設計なので、LLMが直接DBの文法を書く必要はない。
MCPツールが「tag, 条件フィルタ, 自然言語クエリ」を受け取って内部でDB固有のクエリに変換する。
→ **この設計ならFirestoreでもPostgreSQLでもLLMとの相性は同等。**

ただし、もしLLMに「自由にSQLを書かせて分析させたい」場合は
PostgreSQLのほうが圧倒的に有利。

### ② 取得フェーズ: LLMが受け取るデータの形

LLMはJSONテキストとしてデータを受け取る。

**Firestore:**
```json
{
  "id": "ab3f",
  "title": "XRD測定",
  "conditions": {"temperature_C": 500, "atmosphere": "Ar"},
  "tags": ["XRD", "Fe-Cr"],
  "data_refs": {"xrd.ras": {"path": "nextcloud://...", "size_mb": 2.1}},
  "notes": ["BCC単相を確認"]
}
```
→ Firestoreのドキュメントはそのまま**JSONそのもの**。LLMに渡しやすい。

**PostgreSQL:**
```json
{
  "id": "ab3f",
  "title": "XRD測定",
  "conditions": {"temperature_C": 500, "atmosphere": "Ar"},
  "tags": ["XRD", "Fe-Cr"],
  ...
}
```
→ JSONB型を使えば同じ形式で出力可能。差はない。

**比較: 同等。** どちらもJSON形式でLLMに渡せる。

### ③ 解析フェーズ: LLMが横断的に分析する

「チーム全体のXRD実験から、温度と格子定数の相関を分析して」のようなケース。

**Firestore:**
- 全件取得 → Python側で集約・計算 → LLMに渡す
- Firestore自体には集約関数（AVG, GROUP BY等）がほぼない
- MCPサーバー側でPandasやnumpy使って計算する必要あり

**PostgreSQL:**
```sql
SELECT conditions->>'temperature_C' as temp,
       AVG((results->>'lattice_a')::float) as avg_a,
       COUNT(*) as n
FROM experiments
WHERE tags @> '{XRD}' AND tags @> '{Fe-Cr}'
GROUP BY temp
ORDER BY temp;
```
- DB内で集約完了。結果だけLLMに渡せる。
- LLMがSQLを生成 → 実行 → 結果を解釈、のフローが自然。

**比較:**

| 観点 | Firestore | PostgreSQL |
|------|-----------|------------|
| 単一レコードの取得 | ◎ | ◎ |
| 複数レコードの集約分析 | △（Python側で処理） | ◎（SQL内で完結） |
| LLMがデータの傾向を掴む | ○（サマリーを事前計算しておけばOK） | ◎（その場でSQLで集計） |

### まとめ: LLMとの相性

| フェーズ | Firestore | PostgreSQL | 備考 |
|----------|-----------|------------|------|
| 検索（MCPツール経由） | ◎ | ◎ | MCPが吸収するので差なし |
| 検索（LLMが直接クエリ） | △ | ◎ | SQLはLLMの得意技 |
| 取得（JSON応答） | ◎ | ◎ | 差なし |
| 横断分析（集約） | △ | ◎ | PostgreSQLはSQL内で完結 |
| セマンティック検索 | ◎ | ◎ | 両方対応 |

**正直に言うと:**
- **MCPサーバーで全て吸収する設計なら**: Firestoreで十分。コスト・運用メリットが大きい
- **LLMにSQLを直接書かせて自由に分析させたいなら**: PostgreSQLが圧倒的に有利
- **横断的な集約分析が頻繁なら**: PostgreSQLのほうが自然

「データを入れる→LLMから呼び出し→解析する。速さと正確さを求めている」
という要件を考えると、**解析の深さ次第**で最適解が変わる:

- 検索・要約・比較が中心 → Firestore（安い・簡単）
- 集約分析・統計・傾向分析も求める → PostgreSQL（SQLの表現力）

---

## 結論

**Firestoreは「研究室規模のチームデータ共有」にベストマッチ。**

最大の理由は「階層データ×スキーマレス×運用ゼロ×安い」の組み合わせ。
PostgreSQL系（Cloud SQL, Supabase）はSQLの表現力が魅力だが、
階層データの扱いにくさと運用コストが研究室には合わない。

ただし、将来的にクエリの複雑さが増した場合は、
Firestoreのデータを定期的にBigQueryに同期して分析する構成も取れる。
（Firestore → BigQuery連携はGCPネイティブ機能として提供されている）

---

## BigQueryはどうか

### 除外していた理由

v2設計時にBigQueryを「分析専用で、メインDBには不向き」と判断していた。
その根拠を改めて検証する。

| 懸念 | 実態 |
|------|------|
| レイテンシが数秒かかる | ◎ **BigQuery is now fast.** 小規模クエリは1秒未満で返る。BI Engine有効化でさらに高速 |
| 単一レコード取得が遅い | △ 確かにPKルックアップは得意ではない（列指向DB）。ただしキャッシュが効く |
| リアルタイム書き込みが苦手 | △ Streaming insertは対応。ただしFirestoreほどのリアルタイム性はない |
| ベクトル検索ができない | ◎ **VECTOR_SEARCH関数が2024年にGA。** embeddingカラム + ANN検索が可能 |
| コスト | ◎ **分析料金は使った分だけ。保存は$0.02/GB/月。数万件なら月$1-5** |

### BigQueryが実は強い点

| 観点 | BigQuery | Firestore | Cloud SQL |
|------|----------|-----------|-----------|
| **集約分析** | **◎ 最強** | △ | ◎ |
| **SQL** | ◎ 標準SQL | ✗ | ◎ |
| **ベクトル検索** | ◎ VECTOR_SEARCH | ◎ | ◎ pgvector |
| **スキーマ柔軟性** | ◎ JSON型 + STRUCT + ARRAY | ◎ | ○ JSONB |
| **階層データ** | ○ STRUCT/ARRAYのネスト or 再帰CTE | ◎ | △ |
| **運用負荷** | ◎ サーバーレス | ◎ | △ |
| **コスト（保存）** | ◎ $0.02/GB/月 | ◎ | △ $50+/月 |
| **コスト（クエリ）** | ○ $6.25/TB（数万件なら実質$0-5/月） | ◎ 読み取り課金 | ◎ 定額 |
| **リアルタイム書き込み** | △ streaming insert (数秒の遅延) | ◎ | ◎ |
| **単一レコード取得** | △ 列指向なので行取得はやや遅い | ◎ | ◎ |
| **LLMとの相性** | **◎ LLMはSQLが最も得意。BQのSQLは標準的** | △ | ◎ |
| **GCPコンプライアンス** | ◎ | ◎ | ◎ |
| **Vertex AI連携** | **◎ BigQuery ML + Vertex AI統合がネイティブ** | ○ | △ |

### BigQueryが特に輝くシナリオ

```sql
-- LLMが生成するクエリ例: チーム横断分析
SELECT
  conditions.temperature_C,
  AVG(CAST(JSON_VALUE(results, '$.lattice_a') AS FLOAT64)) as avg_lattice_a,
  COUNT(*) as n_experiments,
  ARRAY_AGG(STRUCT(id, title, created_by)) as experiments
FROM `project.dataset.experiments`
WHERE 'XRD' IN UNNEST(tags)
  AND 'Fe-Cr' IN UNNEST(tags)
GROUP BY conditions.temperature_C
ORDER BY conditions.temperature_C;

-- ベクトル検索 + 構造化フィルタ
SELECT *
FROM VECTOR_SEARCH(
  TABLE `project.dataset.experiments`,
  'embedding',
  (SELECT embedding FROM ML.GENERATE_EMBEDDING(
    MODEL `project.dataset.text_embedding`,
    (SELECT 'Fe-Cr合金の結晶性が良い条件' AS content)
  )),
  top_k => 20
)
WHERE status = 'success';
```

### Firestore + BigQuery のハイブリッド構成

実は**Firestoreのデータは自動でBigQueryにエクスポートする機能がGCPにある。**

```
SDK → Firestore（リアルタイム書き込み・単一レコード取得）
         ↓ 自動同期（Firestore BigQuery Export）
      BigQuery（集約分析・LLMからのSQL・ベクトル検索）
```

これなら：
- **書き込み・取得**: Firestoreの即座のレスポンス（数ms）
- **分析・検索**: BigQueryのSQL表現力（数秒で集約完了）
- **コスト**: Firestore $5-20 + BigQuery $1-5 = **月$6-25**（Cloud SQLの半額以下）
- **運用**: 両方サーバーレス。管理ゼロ
- **移行不要**: Firestoreから始めて、BigQuery連携を有効にするだけ

### 改訂版の推奨構成

```
Phase 1: Firestore のみ（月$5-20）
  → 基本的な記録・検索・取得

Phase 2: Firestore + BigQuery 連携を有効化（月$6-25）
  → LLMからのSQL分析、横断集約、ベクトル検索の強化
  → Firestoreの自動エクスポート機能で追加コードほぼ不要

Phase 3: 必要に応じて Cloud SQL 追加（月$50+）
  → Firestoreでは表現できないクエリが頻発する場合のみ
```

---

## 代替案: もしFirestoreが合わないと感じたら

- **BigQuery単体**: 書き込み遅延（数秒）を許容できるならFirestore不要で最安
- **Cloud SQL**: リアルタイム + SQL表現力の両方が必要な場合
- **Supabase**: GCPのコンプライアンスが不要な場合
