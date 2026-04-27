# マルチテナント化 次タスク

「konishi-lab 専用」だった labvault を、同一 GCP プロジェクト (`klab-laser-process`) と Nextcloud (`arim00065`) 配下で複数研究室が使えるようにするための残タスク一覧。

## 完了済み (前提)

| Phase | 内容 | 完了日 |
|---|---|---|
| 1 | `teams/{team_id}` collection 作成 + `allowed_users` を `teams[]` + `default_team` 構造に移行 | 2026-04-27 |
| 2 | backend を per-team Lab に変更、`X-Labvault-Team` header で team context 解決、Nextcloud `group_folder` を `teams/{team_id}` から動的取得、SDK / frontend も対応 | 2026-04-27 |
| 5 | private Artifact Registry (`labvault-pypi`) で wheel 配布、`v*` tag push で自動 publish | 2026-04-27 |

## 残タスク

### Phase 3: サインアップ + admin 承認フロー

**目的**: 新規メンバーが web UI からセルフ申請 → admin がチーム振り分けして承認、で完結させる。

- [ ] **`pending_users/{email}` collection 設計**
  - フィールド: `email`, `display_name`, `requested_team_name` (自由入力), `created_at`, `requester_uid`
- [ ] **backend エンドポイント**
  - `POST /api/auth/request-access` — 認証済 (Firebase login 通過) だが allowed_users 未登録のユーザーが叩く。`requested_team_name` を受け取って `pending_users` に保存
  - `GET /api/admin/pending` — super-admin のみ。pending 一覧
  - `POST /api/admin/approve` — body: `{email, team_id, role, action: "create_team" | "assign"}`
    - `create_team` の場合は同時に `teams/{new_id}` を作成 (`name`, `nextcloud_group_folder` も入力)
    - `allowed_users/{email}` に `teams=[{team_id, role}]`, `default_team` を set
    - `pending_users/{email}` を削除
  - `POST /api/admin/users/{email}/teams` — admin が後から team を追加/削除
- [ ] **auth.py 修正**
  - allowed_users 未登録ユーザーがログインできた後の挙動を「申請画面に誘導」に変更 (現状は 403)
  - 案: `current_user` を 2 段階に分割。`current_authenticated_user` (Firebase 通過)、`current_authorized_user` (allowed_users 通過)。申請エンドポイントは前者を使う
- [ ] **frontend**
  - 申請フォーム (team 名入力)
  - 「申請中」状態の表示
  - admin 承認画面 (pending list、create_team / assign 切替、role 選択)
  - admin ユーザー一覧 + team 編集画面

**スコープ判断**: 当面メンバー追加が稀ならこの Phase は遅らせて、admin が `seed_admin.py` 拡張版 + 手動 IAM grant で対応する選択肢もある。

### Phase 6: team selector UI

**目的**: 複数 team に所属するユーザーが web UI で team を切り替えられるようにする。

- [ ] header に team 切替ドロップダウン (`useAuth().teams` を表示、`setCurrentTeam` を呼ぶ)
- [ ] team 切替時に画面 (records 一覧、検索結果) を再取得
- [ ] localStorage 永続化 (実装済 — 動作確認のみ)

**現状**: backend は per-team で完全に動く。frontend は localStorage に team を保持しているが、切替 UI が無いので 1 team 固定状態。

### メンバー管理の自動化 (AR + allowed_users 連動)

**目的**: admin 承認時に Artifact Registry の reader 権限も同時付与する。

選択肢:

- **案 A: Google Group 一本化 (推奨)**
  - `labvault-users@<workspace-domain>` を作成
  - AR repo に group 単位で `roles/artifactregistry.reader` 付与
  - 承認時に backend が Admin SDK Directory API で group に email 追加
  - 必要権限: backend SA に `roles/groups.member.editor` (or Workspace 管理者代理)
  - メリット: AR IAM 触らない、admin が group で一覧確認可能
  - 注意: Workspace ドメインが必要 (`g.ecc.u-tokyo.ac.jp` は東大組織の管理下なので使えない可能性あり、別途確認)

- **案 B: 直接 IAM API**
  - 承認時に backend が Resource Manager API で AR repo の IAM policy に email を追加
  - 必要権限: backend SA に `roles/artifactregistry.repoAdmin` (該当 repo のみ)
  - メリット: 追加インフラ不要
  - デメリット: ユーザー一覧が AR IAM と allowed_users の両方に分散

- **案 C: 手動運用 (当面)**
  - 承認時に admin が gcloud で IAM 付与
  - 文書化のみで実装不要
  - 人数 < 10 ならこれで足りる

### その他の改善

- [ ] **Vector Search の team フィルタ追加** — 現状 `find_nearest` は deleted_at + status のみ filter。Phase 2 で path 階層分離されているので実害は無いが、念のため明示 filter も足す
- [ ] **MCP サーバーの team 対応** — 現状 `LABVAULT_TEAM` 固定。複数 team に所属するユーザーが MCP で team を切替えるための引数追加 (各ツールに `team: str` optional)
- [ ] **装置 PC 運用手順書** — SA で運用するか、ユーザーアカウントで運用するか。`LABVAULT_PLATFORM_URL` + ADC でセットアップする標準フローを `docs/instrument_pc_setup.md` に
- [ ] **README の install 手順を実利用者でレビュー** — 別アカウントで `gcloud auth application-default login` から始めて pip install まで通るか確認
- [ ] **AR repo cleanup ポリシー** — 古い patch version を残し続けるか定期削除するか。当面は無削除

> リリース運用 (タグ → CI publish のフロー) は CLAUDE.md「リリース運用」を参照。

## 参考

- 設計: [auth_design.md](./auth_design.md)
- マイグレーションスクリプト: `scripts/migrate_to_multitenant.py`
- 実装コミット: 4f5a93b (Phase 1+2), b8e2250 / 765141c (Phase 5)
