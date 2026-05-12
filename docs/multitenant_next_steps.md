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
| 3+ | admin ユーザー一覧 + team 後追い (`GET /api/admin/users` / `GET /api/admin/teams` / `POST /api/admin/users/{email}/teams` / `DELETE .../teams/{team_id}`、`/admin/users` 画面で team 追加/削除) | 2026-05-11 |
| AR連動 | 案 B (直接 IAM API) で Artifact Registry reader を承認時に自動付与 (`app/artifact_registry.py`、`admin_approve` / `admin_add_user_team` から呼ぶ。冪等。`LABVAULT_AR_REPO` 未設定なら no-op) | 2026-05-11 |
| 3+ | user の deactivate/reactivate (`PATCH /api/admin/users/{email}` の `active`)。自己 deactivate と最後の super-admin deactivate を 400 で拒否。`auth_me` に "deactivated" status 追加、AuthGate で明示メッセージ。AR reader も連動 revoke/grant | 2026-05-11 |
| 3+ | admin が他ユーザーの display_name を編集可。`PATCH /api/admin/users/{email}` を PATCH semantics 化、UserCard で inline 編集 (Enter 保存 / Esc cancel、IME 確定 Enter は無視) | 2026-05-12 |
| MCP | MCP の team 対応 (`Lab.team` 公開、`create_server` を per-team Lab キャッシュ化、各ツールに `team: str | None = None` 追加。事前構築 lab は team 未指定時のフォールバックとして動作しテスト互換維持) | 2026-05-12 |

## 残タスク

### Phase 3 残り (後回し)

- [ ] team-scoped admin (`teams[].role == "admin"`) の判定ヘルパー `require_team_admin(team_id)` を追加し、approve や user 編集を team admin にも開放

### AR 連動の運用メモ (案 B 採用済)

採用理由: Workspace ドメイン未保有のため案 A (Google Group) が選べない。`allowed_users` を SoT、AR IAM はそのミラーと割り切る。

**初回セットアップ (一度だけ手動実行)** — runtime SA に該当 repo の repoAdmin を付与:

```bash
gcloud artifacts repositories add-iam-policy-binding labvault-pypi \
  --location=asia-northeast1 \
  --project=klab-laser-process \
  --member=serviceAccount:labvault-api@klab-laser-process.iam.gserviceaccount.com \
  --role=roles/artifactregistry.repoAdmin
```

**動作**:

- `POST /api/admin/approve` 成功時に `grant_reader(email)` を呼ぶ
- `POST /api/admin/users/{email}/teams` でも呼ぶ (旧 user の救済を兼ねる)
- 失敗しても処理は止めず、レスポンスの `ar_granted: bool | None` で結果を返す
- `LABVAULT_AR_REPO` 未設定なら no-op で warning ログのみ

**未実装** (TODO):

- [ ] 既存ユーザーの一括 backfill スクリプト (現状は手動 gcloud or 「team 再追加」で代用)
- [ ] user deactivate 時の `revoke_reader` 連動 (deactivate endpoint 自体が未実装)
- [ ] admin UI で grant 失敗時の retry ボタン

### その他の改善

- [ ] **Vector Search の team フィルタ追加** — 現状 `find_nearest` は deleted_at + status のみ filter。Phase 2 で path 階層分離されているので実害は無いが、念のため明示 filter も足す
- [ ] **装置 PC 運用手順書** — SA で運用するか、ユーザーアカウントで運用するか。`LABVAULT_PLATFORM_URL` + ADC でセットアップする標準フローを `docs/instrument_pc_setup.md` に
- [ ] **README の install 手順を実利用者でレビュー** — 別アカウントで `gcloud auth application-default login` から始めて pip install まで通るか確認
- [ ] **AR repo cleanup ポリシー** — 古い patch version を残し続けるか定期削除するか。当面は無削除

> リリース運用 (タグ → CI publish のフロー) は CLAUDE.md「リリース運用」を参照。

## 参考

- 設計: [auth_design.md](./auth_design.md)
- マイグレーションスクリプト: `scripts/migrate_to_multitenant.py`
- 実装コミット: 4f5a93b (Phase 1+2), b8e2250 / 765141c (Phase 5), 407b464 (Phase 6), f114f98 (Phase 3)
