# マルチテナント化 次タスク

「konishi-lab 専用」だった labvault を、同一 GCP プロジェクト (`klab-laser-process`) と Nextcloud (`arim00065`) 配下で複数研究室が使えるようにするための残タスク一覧。

## 完了済み (前提)

| Phase | 内容 | 完了日 |
|---|---|---|
| 1 | `teams/{team_id}` collection 作成 + `allowed_users` を `teams[]` + `default_team` 構造に移行 | 2026-04-27 |
| 2 | backend を per-team Lab に変更、`X-Labvault-Team` header で team context 解決、Nextcloud `group_folder` を `teams/{team_id}` から動的取得、SDK / frontend も対応 | 2026-04-27 |
| 5 | private Artifact Registry (`labvault-pypi`) で wheel 配布、`v*` tag push で自動 publish | 2026-04-27 |
| 6 | header に team selector ドロップダウン、team 切替時は `key={currentTeam}` で children remount し全 fetch を再発火、`/api/auth/me` に team `name` を含める | 2026-04-28 |
| 3 | サインアップ + super-admin 承認フロー (auth.py 2 段階化、`pending_users` collection、`/api/auth/request-access` / `/api/admin/pending` / `/api/admin/approve`、申請フォーム + 承認 UI) | 2026-04-28 |

## 残タスク

### Phase 3 残り (後回し)

- [ ] `POST /api/admin/users/{email}/teams` — admin が承認済みユーザーに team を後から追加/削除
- [ ] admin ユーザー一覧画面 (現状は pending のみ)
- [ ] team-scoped admin (`teams[].role == "admin"`) の判定ヘルパー `require_team_admin(team_id)` を追加し、approve や user 編集を team admin にも開放

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
- 実装コミット: 4f5a93b (Phase 1+2), b8e2250 / 765141c (Phase 5), 407b464 (Phase 6), f114f98 (Phase 3)
