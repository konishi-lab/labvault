# Claude Codeでの2リポ同時開発ワークフロー

> labvault（SDK）と labvault-platform（モノレポ）を
> Claude Codeで同時に開発する際のベストプラクティス。

---

## リポジトリ構成（前提）

```
~/ghq/github.com/konishi-lab/
├── labvault/                ← SDK（独立リポ。pip install用）
└── labvault-platform/       ← モノレポ（API + WebApp + Functions + Infra）
```

---

## 1. CLAUDE.mdでの相互参照（最重要）

Claude Codeは会話開始時にCLAUDE.mdを自動読み込みする。
**両リポのCLAUDE.mdに相手の情報を書く**ことで、片方で作業中に他方の存在と場所を常に把握できる。

### labvault/CLAUDE.md に追加する内容

```markdown
## 関連リポジトリ

### labvault-platform（プラットフォーム）
- パス: /Users/hirosuke/ghq/github.com/konishi-lab/labvault-platform
- 内容: API Server + WebApp + Cloud Functions + Terraform
- 共有スキーマ:
  - Firestore定義: packages/api-server/schema/firestore.ts
  - 共有型定義: shared/types/
- SDK側の対応ファイル:
  - Firestoreモデル: src/labvault/core/types.py
  - バックエンド: src/labvault/backends/

## スキーマ変更時の手順
1. Platform側で schema/firestore.ts を変更
2. SDK側で types.py を同期
3. 各リポでPR作成（PRコメントで依存関係を記載）
4. マージ順序: Platform → SDK
```

### labvault-platform/CLAUDE.md に追加する内容

```markdown
## 関連リポジトリ

### labvault（Python SDK）
- パス: /Users/hirosuke/ghq/github.com/konishi-lab/labvault
- 内容: 実験者向けPython SDK + CLI
- SDK側のFirestoreモデル: src/labvault/core/types.py
- SDK側のバックエンド: src/labvault/backends/

## SDK互換性
- API変更時はSDK側のモデルも同期が必要
- SDKはPlatformとは独立したリリースサイクル
- 破壊的変更はAPIバージョニング(/api/v1 → /api/v2)で対応
```

---

## 2. 具体的な開発フロー

### パターンA: Firestoreスキーマ変更

```
1. Platform側のClaude Codeで:
   「Firestoreのrecordsにresultsフィールドを追加して」
   → schema変更 + API変更 + WebApp変更を1つのPRに

2. SDK側のClaude Codeで:
   「Platform側でFirestoreにresultsフィールドが追加された。
    /Users/hirosuke/ghq/.../labvault-platform/shared/types/ を読んで
    SDK側のtypes.pyを同期して」
   → Claude Codeは絶対パスで他リポのファイルを読める
```

### パターンB: APIエンドポイント追加

```
1. Platform側で:
   「POST /api/v1/records/{id}/results エンドポイントを追加して」

2. SDK側で:
   「Platform側に results エンドポイントが追加された。
    /Users/hirosuke/ghq/.../labvault-platform/packages/api-server/routes/ を読んで
    SDK側にresultsメソッドを追加して」
```

### パターンC: 両方同時に変更

```
SDK側のClaude Codeから1セッションで両方変更:
   「Firestoreにsoftwareフィールドを追加したい。
    1. /Users/hirosuke/ghq/.../labvault-platform/... のスキーマを修正
    2. このリポのtypes.pyも同期
    両方変更して」
   → Claude Codeは両リポのファイルを読み書きできる
```

---

## 3. 核心テクニック: 絶対パスで他リポを読み書き

Claude Codeは**ワーキングディレクトリ外のファイルも絶対パスでアクセスできる**。
これが2リポ開発の最も強力な手段。

```
# SDK側で作業中に、Platform側のスキーマを参照
「/Users/hirosuke/ghq/github.com/konishi-lab/labvault-platform/shared/types/record.ts
 を読んで、SDK側のtypes.pyと差分がないか確認して」

# Platform側で作業中に、SDK側のテストを確認
「/Users/hirosuke/ghq/github.com/konishi-lab/labvault/tests/test_types.py
 を読んで、今回のスキーマ変更で壊れるテストがないか確認して」
```

---

## 4. Agent Teamsの使い方

### 同一リポ内の並行作業には最適

```
# Platform側で、API変更とWebApp変更を並行
Agent 1: API Serverのエンドポイント追加
Agent 2: WebAppのUI変更
→ 同一リポなのでAgent Teamsが有効
```

### 2リポ跨ぎは逐次処理が安全

Agent Teamsは同一リポ内の並行作業に最適化されている。
2リポ跨ぎの場合は、1つのClaude Codeセッションから絶対パスで
両方のファイルを逐次操作するほうがコンフリクトリスクが低い。

---

## 5. 共有スキーマの管理方法

### 推奨: SDK側のPydanticモデルを正（Single Source of Truth）にする

```
labvault/src/labvault/core/types.py          ← 正（Pydanticモデル）
labvault-platform/shared/types/record.ts     ← 派生（TypeScript型定義）
```

### 同期チェック

CIで「両リポのスキーマが一致しているか」を自動チェック：

```yaml
# labvault/.github/workflows/schema-sync.yml
- name: Check schema sync
  run: |
    # Platform側のスキーマを取得して差分チェック
    diff <(python scripts/extract_schema.py) \
         <(curl -s https://raw.githubusercontent.com/.../shared/types/record.ts | python scripts/ts_to_py.py)
```

---

## 6. PRテンプレート

### labvault（SDK）

```markdown
## 関連Platform PR
- [ ] labvault-platform#____ （なければ「なし」）

## スキーマ同期
- [ ] types.pyがPlatform側のスキーマと一致している
```

### labvault-platform

```markdown
## 関連SDK PR
- [ ] labvault#____ （なければ「なし」）

## SDK互換性
- [ ] この変更はSDKの破壊的変更を伴わない
- [ ] 破壊的変更の場合: APIバージョニングで対応済み
```

---

## まとめ

| やること | 方法 |
|---------|------|
| 相手リポの存在を知る | CLAUDE.mdに相互参照を記載 |
| 相手リポのファイルを読む | 絶対パスで直接Read |
| 相手リポのファイルを書く | 絶対パスで直接Write（1セッションから両方変更） |
| スキーマ同期 | SDK側が正。Platform側が追従。CIで自動チェック |
| 並行作業 | 同一リポ内はAgent Teams。2リポ跨ぎは逐次 |
| PR管理 | テンプレートで依存関係を明記。マージ順序はPlatform→SDK |
