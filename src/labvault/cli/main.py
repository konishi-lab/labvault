"""labvault CLI."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import click


@click.group()
@click.version_option(package_name="labvault")
def cli() -> None:
    """labvault -- 実験データ基盤 CLI."""


@cli.command()
@click.option("--team", prompt="Team name", help="チーム名")
@click.option("--user", prompt="Your name", help="ユーザー名")
@click.option("--nextcloud-url", default="", help="Nextcloud URL")
@click.option("--nextcloud-user", default="", help="Nextcloud ユーザー")
@click.option(
    "--nextcloud-password",
    default="",
    hide_input=True,
    help="Nextcloud パスワード",
)
@click.option("--nextcloud-group-folder", default="", help="グループフォルダ")
@click.option("--gcp-project", default="", help="GCP プロジェクト ID")
def init(
    team: str,
    user: str,
    nextcloud_url: str,
    nextcloud_user: str,
    nextcloud_password: str,
    nextcloud_group_folder: str,
    gcp_project: str,
) -> None:
    """初期セットアップ (config.toml 生成)."""
    config_dir = Path.home() / ".labvault"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.toml"

    lines = [
        f'team = "{team}"',
        f'user = "{user}"',
    ]
    if nextcloud_url:
        lines.append(f'nextcloud_url = "{nextcloud_url}"')
    if nextcloud_user:
        lines.append(f'nextcloud_user = "{nextcloud_user}"')
    if nextcloud_password:
        lines.append(f'nextcloud_password = "{nextcloud_password}"')
    if nextcloud_group_folder:
        lines.append(f'nextcloud_group_folder = "{nextcloud_group_folder}"')
    if gcp_project:
        lines.append(f'gcp_project = "{gcp_project}"')

    config_path.write_text("\n".join(lines) + "\n")
    click.echo(f"Config written: {config_path}")


@cli.command()
@click.argument("title")
@click.option("--type", "-t", "record_type", default="experiment")
@click.option("--tags", "-T", multiple=True, help="タグ (複数指定可)")
def new(title: str, record_type: str, tags: tuple[str, ...]) -> None:
    """新しいレコードを作成する。"""
    lab = _get_lab()
    rec = lab.new(
        title,
        type=record_type,
        tags=list(tags) if tags else None,
        auto_log=False,
    )
    click.echo(f"{rec.id}  {rec.title}")
    lab.close()


@cli.command()
@click.argument("record_id")
@click.argument("files", nargs=-1, type=click.Path(exists=True))
def add(record_id: str, files: tuple[str, ...]) -> None:
    """レコードにファイルを追加する。"""
    lab = _get_lab()
    rec = lab.get(record_id)
    for f in files:
        rec.add(f)
        click.echo(f"Added: {f} -> {rec.id}")
    lab.close()


@cli.command("list")
@click.option("--tags", "-T", multiple=True, help="タグでフィルタ")
@click.option("--status", "-s", default=None, help="ステータスでフィルタ")
@click.option("--type", "-t", "record_type", default=None, help="タイプでフィルタ")
@click.option("--limit", "-n", default=20, help="表示件数")
def list_cmd(
    tags: tuple[str, ...],
    status: str | None,
    record_type: str | None,
    limit: int,
) -> None:
    """レコード一覧を表示する。"""
    lab = _get_lab()
    records = lab.list(
        tags=list(tags) if tags else None,
        status=status,
        type=record_type,
        limit=limit,
    )
    if not records:
        click.echo("No records found.")
    else:
        for rec in records:
            tags_str = f"  [{', '.join(rec.tags)}]" if rec.tags else ""
            click.echo(f"{rec.id}  {rec.title}  ({rec.status}){tags_str}")
    lab.close()


@cli.command()
@click.argument("record_id")
def show(record_id: str) -> None:
    """レコードの詳細を表示する。"""
    lab = _get_lab()
    rec = lab.get(record_id)

    click.echo(f"ID:         {rec.id}")
    click.echo(f"Title:      {rec.title}")
    click.echo(f"Type:       {rec.type}")
    click.echo(f"Status:     {rec.status}")
    click.echo(f"Created by: {rec.created_by}")
    click.echo(f"Created at: {rec.created_at:%Y-%m-%d %H:%M:%S}")
    click.echo(f"Updated at: {rec.updated_at:%Y-%m-%d %H:%M:%S}")

    if rec.tags:
        click.echo(f"Tags:       {', '.join(rec.tags)}")

    conditions = rec.get_conditions()
    if conditions:
        click.echo("Conditions:")
        for k, v in conditions.items():
            click.echo(f"  {k}: {v}")

    if rec.results:
        click.echo("Results:")
        for k, v in rec.results.items():
            click.echo(f"  {k}: {v}")

    if rec.notes:
        click.echo("Notes:")
        for n in rec.notes:
            click.echo(f"  [{n.created_at:%H:%M:%S}] {n.text}")

    data_refs = rec.list_data()
    if data_refs:
        click.echo("Files:")
        for ref in data_refs:
            click.echo(f"  {ref.name} ({ref.size_bytes} bytes)")

    if rec.links:
        click.echo("Links:")
        for lk in rec.links:
            click.echo(f"  -> {lk.target_id} ({lk.relation})")

    lab.close()


@cli.command()
@click.argument("query", default="")
@click.option("--limit", "-n", default=20, help="表示件数")
@click.option("--parent-id", "-p", default=None, help="親レコード ID でフィルタ")
@click.option("--tags", "-T", multiple=True, help="タグでフィルタ")
@click.option("--status", "-s", "status_filter", default=None, help="ステータス")
@click.option("--type", "-t", "type_filter", default=None, help="タイプでフィルタ")
@click.option(
    "--created-by",
    "-u",
    "created_by",
    default=None,
    help="作成者 (email 完全一致) でフィルタ。例: user@example.com",
)
@click.option(
    "--conditions",
    "-c",
    multiple=True,
    help="条件フィルタ (例: power=20, power>=50, power<=100)",
)
@click.option("--show-conditions", "-C", is_flag=True, help="条件も表示する")
def search(
    query: str,
    limit: int,
    parent_id: str | None,
    tags: tuple[str, ...],
    status_filter: str | None,
    type_filter: str | None,
    created_by: str | None,
    conditions: tuple[str, ...],
    show_conditions: bool,
) -> None:
    """レコードを検索する。"""
    lab = _get_lab()

    cond_dict = _parse_conditions(conditions) if conditions else None

    if query:
        # semantic search + post-filter (created_by は post-filter で対応)
        results = lab.search(
            query,
            tags=list(tags) if tags else None,
            status=status_filter,
            type=type_filter,
            parent_id=parent_id,
            conditions=cond_dict,
            limit=limit * 5 if created_by else limit,
        )
        if created_by:
            results = [r for r in results if r.created_by == created_by]
        results = results[:limit]
    else:
        results = lab.list(
            tags=list(tags) if tags else None,
            status=status_filter,
            type=type_filter,
            created_by=created_by,
            limit=limit * 5 if cond_dict or parent_id else limit,
        )
        if parent_id is not None:
            results = [r for r in results if r.parent_id == parent_id]
        if cond_dict:
            from labvault.core.lab import _match_condition

            results = [
                r
                for r in results
                if all(
                    _match_condition(r.get_conditions().get(k), v)
                    for k, v in cond_dict.items()
                )
            ]
        results = results[:limit]

    if not results:
        click.echo("No results found.")
    else:
        for rec in results:
            line = f"{rec.id}  {rec.title}  ({rec.status})"
            if show_conditions:
                cond = rec.get_conditions()
                if cond:
                    pairs = [f"{k}={v}" for k, v in cond.items()]
                    line += f"  [{', '.join(pairs)}]"
            click.echo(line)
    lab.close()


def _human_bytes(n: int) -> str:
    """人間が読める単位に整形 (B, KB, MB, GB, TB)."""
    val = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1024:
            return f"{val:.2f} {unit}"
        val /= 1024
    return f"{val:.2f} PB"


@cli.command()
@click.option(
    "--created-by",
    "-u",
    "created_by",
    default=None,
    help="作成者 email で絞る (省略時は team 全体)",
)
@click.option(
    "--top-creators",
    default=10,
    help="by_creator の上位表示数",
)
def usage(created_by: str | None, top_creators: int) -> None:
    """team の storage 利用量を集計する (レコード数 / ファイル数 / 総 bytes)。

    ``--created-by`` で特定ユーザーのみに絞れる。返り値は by_creator /
    by_extension / by_type の内訳も表示。
    """
    lab = _get_lab()
    try:
        summary = lab.get_usage(created_by=created_by)
    finally:
        lab.close()

    click.echo(f"team: {summary['team']}")
    if created_by:
        click.echo(f"created_by filter: {created_by}")
    click.echo(f"records: {summary['total_records']:,}")
    click.echo(f"files:   {summary['total_files']:,}")
    click.echo(
        f"bytes:   {_human_bytes(summary['total_bytes'])} "
        f"({summary['total_bytes']:,} B)"
    )
    click.echo("")

    creators = sorted(
        summary["by_creator"].items(),
        key=lambda kv: kv[1]["bytes"],
        reverse=True,
    )[:top_creators]
    if creators:
        click.echo(f"top creators (by bytes, top {len(creators)}):")
        for creator, stats in creators:
            click.echo(
                f"  {stats['records']:5,} rec / {stats['files']:5,} files "
                f"/ {_human_bytes(stats['bytes']):>10}  {creator}"
            )
        click.echo("")

    ext = summary["by_extension"]
    if ext:
        click.echo("by file extension:")
        for e, stats in sorted(
            ext.items(), key=lambda kv: kv[1]["bytes"], reverse=True
        ):
            click.echo(
                f"  {stats['files']:5,}  .{e:<12s}  "
                f"{_human_bytes(stats['bytes'])}"
            )
        click.echo("")

    types = summary["by_type"]
    if types:
        click.echo("by record type:")
        for t, count in sorted(
            types.items(), key=lambda kv: kv[1], reverse=True
        ):
            click.echo(f"  {count:5,}  {t}")


@cli.command()
def doctor() -> None:
    """設定の健全性をチェックする。

    出力凡例:
      [OK] = 設定済 / 疎通 OK
      [--] = 未設定だが代替手段があるため致命ではない
      [!!] = 設定不整合 or 疎通失敗。要対処
    """
    from labvault.core.config import Settings

    click.echo("labvault doctor\n")
    issues = 0
    home = Path.home() / ".labvault"

    # --- 設定ファイル群 (すべて optional。env / .env / credentials で代替可) ---
    config_path = home / "config.toml"
    if config_path.exists():
        click.echo(f"  [OK] config.toml: {config_path}")
    else:
        click.echo(
            "  [--] config.toml: not present (env / .env / credentials で代替可)"
        )

    creds_path = home / "credentials"
    if creds_path.exists():
        click.echo(f"  [OK] credentials: {creds_path}")
    else:
        click.echo("  [--] credentials: not present (PAT モードを使う場合のみ必要)")

    # --- Settings ロード ---
    settings: Settings | None
    try:
        settings = Settings()
        click.echo(f"  [OK] team: {settings.team or '(not set)'}")
        click.echo(f"  [OK] user: {settings.user or '(not set)'}")
    except Exception as e:
        click.echo(f"  [!!] Settings: {e}")
        issues += 1
        settings = None

    click.echo(f"  [OK] Python: {sys.version.split()[0]}")

    if settings is not None:
        # --- Platform URL (Web UI backend、PAT / Nextcloud credentials の源) ---
        if settings.platform_url:
            click.echo(f"  [OK] platform URL: {settings.platform_url}")
        else:
            click.echo("  [--] platform URL: not set (direct backend モード)")

        # --- PAT ---
        if settings.token:
            click.echo(f"  [OK] PAT: configured ({settings.token[:8]}...)")
        else:
            click.echo("  [--] PAT: not set (ADC を使用)")

        # PAT モード (token + platform_url) では Firestore / Nextcloud に
        # 直接接続しないので、GCP project / Nextcloud direct URL は
        # 未使用。表示は維持しつつ「不要」と明示する。
        in_pat_mode = bool(settings.token and settings.platform_url)

        # --- GCP project ---
        pat_note = " (PAT モードでは未使用)" if in_pat_mode else ""
        if settings.gcp_project:
            click.echo(f"  [OK] GCP project: {settings.gcp_project}{pat_note}")
        else:
            click.echo(f"  [--] GCP project: not set{pat_note}")

        # --- Nextcloud ---
        if settings.nextcloud_url:
            try:
                import httpx

                resp = httpx.get(f"{settings.nextcloud_url}/status.php", timeout=5)
                if resp.status_code == 200:
                    click.echo(f"  [OK] Nextcloud: {settings.nextcloud_url}{pat_note}")
                else:
                    click.echo(f"  [!!] Nextcloud: HTTP {resp.status_code}")
                    issues += 1
            except Exception as e:
                click.echo(f"  [!!] Nextcloud: {e}")
                issues += 1
        elif settings.platform_url:
            click.echo("  [OK] Nextcloud: via platform (credentials は runtime に取得)")
        else:
            click.echo("  [--] Nextcloud: not configured")

        # --- 推定 backend モード ---
        # Lab.__init__ の _build_platform_client / _auto_* と同じロジック。
        # 実際に Lab() を作らずに表示することで firestore / vertex 等の
        # 重い初期化を回避する。
        if settings.token and settings.platform_url:
            mode = "PAT mode — 全 backend が Platform* に切替 (Google アカウント不要)"
        elif settings.platform_url:
            mode = "Mixed mode — Firestore/Vertex は ADC、Nextcloud は platform 経由"
        else:
            mode = "Direct mode — Firestore/Nextcloud/Vertex を直接呼出"
        click.echo(f"  [OK] mode: {mode}")

    click.echo()
    click.echo("凡例: [OK]=設定済 / [--]=未設定だが代替可 (致命でない) / [!!]=要対処")
    if issues == 0:
        click.echo("All checks passed.")
    else:
        click.echo(f"{issues} issue(s) found. See above.")

    # --- 次のステップ ---
    # 設定状態と推奨パスを案内する。「推奨 = ADC (gcloud)」を強調し、
    # 装置 PC や gcloud が使えない環境では PAT、という位置付け。
    hints: list[str] = []
    if settings is None:
        return

    if not settings.team:
        hints.append(
            "team が未設定。`labvault init` で入力するか、.env に "
            "`LABVAULT_TEAM=konishi-lab` を書く。"
        )
    if not settings.user:
        hints.append(
            "user が未設定。Record の created_by が空になる。"
            "PAT モードなら `labvault auth set-token --force` (verify 経由で "
            "発行者 email を default 設定)、それ以外は `labvault init` または "
            ".env に `LABVAULT_USER=<your-name>` を書く。"
        )

    has_pat = bool(settings.token)
    has_gcp = bool(settings.gcp_project)

    if not has_pat and not has_gcp:
        # 認証ゼロ
        hints.append(
            "認証が未設定。**推奨は ADC**: "
            "`gcloud auth application-default login` + "
            ".env に `LABVAULT_GCP_PROJECT=klab-laser-process` を書く。"
        )
        hints.append(
            "装置 PC など gcloud を使えない環境では PAT: "
            "Web UI で発行 → `labvault auth set-token --token-stdin`。"
        )
    elif has_pat and not settings.platform_url:
        hints.append(
            "PAT が設定されているが LABVAULT_PLATFORM_URL が空。"
            "`labvault auth set-token --force` で credentials を再作成すると "
            "platform_url も埋まる。"
        )
    elif has_pat and has_gcp:
        hints.append(
            "PAT と GCP project の両方が設定されている。Settings の優先順位上 "
            "PAT が使われる。ADC の方が監査ログが個人と紐付くので、可能なら "
            "PAT を外して ADC のみに寄せる方が推奨。"
        )

    if not settings.nextcloud_url and not settings.platform_url:
        hints.append(
            "Nextcloud / platform URL のどちらも未設定。"
            "ファイル保存は InMemory フォールバックになり、再起動で消える。"
        )

    if issues == 0 and not hints:
        hints.append(
            '動作確認: `python -c "from labvault import Lab; '
            'lab = Lab(); print(type(lab.backend).__name__)"`'
        )

    if hints:
        click.echo()
        click.echo("次のステップ:")
        for h in hints:
            click.echo(f"  • {h}")


@cli.command()
@click.argument("record_id")
def delete(record_id: str) -> None:
    """レコードを削除する (ソフトデリート)."""
    lab = _get_lab()
    try:
        lab.delete(record_id)
        click.echo(f"Deleted: {record_id}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from None
    lab.close()


@cli.command()
@click.argument("record_id")
def restore(record_id: str) -> None:
    """削除したレコードを復元する。"""
    lab = _get_lab()
    try:
        rec = lab.restore(record_id)
        click.echo(f"Restored: {rec.id}  {rec.title}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from None
    lab.close()


@cli.command()
@click.argument("record_id")
@click.argument("text")
def note(record_id: str, text: str) -> None:
    """レコードにメモを追加する。"""
    lab = _get_lab()
    try:
        rec = lab.get(record_id)
        rec.note(text)
        click.echo(f"Note added to {rec.id}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from None
    lab.close()


@cli.command()
@click.argument("record_id")
@click.argument("tags", nargs=-1, required=True)
@click.option("--remove", "-r", is_flag=True, help="タグを削除する")
def tag(record_id: str, tags: tuple[str, ...], remove: bool) -> None:
    """レコードのタグを追加/削除する。"""
    lab = _get_lab()
    try:
        rec = lab.get(record_id)
        if remove:
            rec.untag(*tags)
            click.echo(f"Tags removed from {rec.id}: {', '.join(tags)}")
        else:
            rec.tag(*tags)
            click.echo(f"Tags added to {rec.id}: {', '.join(tags)}")
        click.echo(f"Current tags: {rec.tags}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from None
    lab.close()


@cli.command()
@click.argument("record_id")
@click.argument(
    "new_status",
    type=click.Choice(["running", "success", "failed", "partial"]),
)
def status(record_id: str, new_status: str) -> None:
    """レコードのステータスを変更する。"""
    lab = _get_lab()
    try:
        rec = lab.get(record_id)
        rec.status = new_status
        click.echo(f"{rec.id}: status -> {rec.status}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from None
    lab.close()


@cli.command("check-results")
@click.option(
    "--limit",
    "-n",
    default=1000,
    help="scan する record 数の上限 (default 1000)",
)
@click.option(
    "--csv",
    "csv_path",
    default=None,
    type=click.Path(),
    help="違反一覧を CSV に書き出す",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="各違反の preview を出力",
)
def check_results(limit: int, csv_path: str | None, verbose: bool) -> None:
    """既存 record の results に v0.3.0 規約違反 (dict / 長 list / size 超過) が
    無いか scan する。

    新規書き込みは ``_ResultsProxy.__setitem__`` で hard error になるが、
    規約以前に書き込まれたデータは Firestore 側に残っている可能性がある。
    本コマンドで棚卸ししてください。書き換えは行わない (read-only)。
    """
    import csv as csv_module
    import time

    from labvault.core.results_audit import scan_record, summarize

    lab = _get_lab()
    team = lab.team
    click.echo(f'Scanning team "{team}" (limit={limit})...')
    started = time.time()

    # C2 (2026-06-30): lab.backend (Protocol typed) で raw dict 経由のまま
    # audit ロジックに通す。Lab.list は Record オブジェクトを返してしまうので、
    # results_audit が dict 前提のここでは admin 経路の Protocol access が
    # 最も自然。
    rows = lab.backend.list_records(team, limit=limit)
    elapsed = time.time() - started

    all_violations = []
    affected_record_ids: set[str] = set()
    for row in rows:
        violations = scan_record(row)
        if violations:
            all_violations.extend(violations)
            affected_record_ids.add(str(row.get("id") or ""))

    counts = summarize(all_violations)

    click.echo(f"Scanned {len(rows)} records ({elapsed:.2f}s).")
    if not all_violations:
        click.echo("✅ 違反なし。")
        lab.close()
        return

    click.echo(
        f"⚠ Violations: {len(all_violations)} (in {len(affected_record_ids)} records)"
    )
    for kind in ("dict", "long_list", "value_too_large", "total_too_large"):
        n = counts.get(kind, 0)
        if n:
            click.echo(f"  {kind:<18} {n}")

    if verbose:
        click.echo("\n詳細:")
        for v in all_violations:
            click.echo(f"  [{v.record_id}] {v.key:<20} {v.kind}")
            click.echo(f"    {v.detail}")
            if v.value_preview:
                click.echo(f"    preview: {v.value_preview}")

    if csv_path:
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv_module.writer(fh)
            writer.writerow(["record_id", "key", "kind", "detail", "value_preview"])
            for v in all_violations:
                writer.writerow([v.record_id, v.key, v.kind, v.detail, v.value_preview])
        click.echo(f"\nCSV: {csv_path} に書き出しました。")

    if not verbose:
        click.echo("\nヒント: --verbose で詳細、--csv FILE で書き出し可能。")
    lab.close()


@cli.command()
@click.argument("output_dir", type=click.Path())
@click.option("--limit", "-n", default=100, help="エクスポート件数")
def export(output_dir: str, limit: int) -> None:
    """レコードを JSON ファイルとしてエクスポートする。"""
    import json
    from pathlib import Path

    lab = _get_lab()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    records = lab.list(limit=limit)
    for rec in records:
        data = rec._to_dict()
        path = out / f"{rec.id}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))

    click.echo(f"Exported {len(records)} records to {out}/")
    lab.close()


@cli.command()
@click.argument("key")
@click.option("--group-by", "-g", default=None, help="グループ化キー")
@click.option("--parent-id", "-p", default=None, help="親レコード ID でフィルタ")
@click.option("--tags", "-T", multiple=True, help="タグでフィルタ")
@click.option("--status", "-s", default=None, help="ステータスでフィルタ")
@click.option("--type", "-t", "record_type", default=None, help="タイプでフィルタ")
def aggregate(
    key: str,
    group_by: str | None,
    parent_id: str | None,
    tags: tuple[str, ...],
    status: str | None,
    record_type: str | None,
) -> None:
    """数値キーの統計集計 (conditions/results 両対応)."""
    from labvault.core.aggregate import StatsResult, compute_aggregate

    lab = _get_lab()
    records = lab.list(
        tags=list(tags) if tags else None,
        status=status,
        type=record_type,
        limit=5000,
    )
    if parent_id is not None:
        records = [r for r in records if r.parent_id == parent_id]

    result = compute_aggregate(records, key, group_by=group_by)

    def _fmt(s: StatsResult) -> str:
        if not s.count:
            return "no data"
        return (
            f"n={s.count}  mean={s.mean:.4f}  std={s.std:.4f}  "
            f"min={s.min}  max={s.max}  median={s.median:.4f}"
        )

    click.echo(f"Key: {key}  ({result.record_count} records scanned)")
    click.echo(f"Overall: {_fmt(result.overall)}")

    if group_by and result.groups:
        click.echo(f"\nGroup by: {group_by}")
        for gk in sorted(result.groups.keys()):
            click.echo(f"  {gk}: {_fmt(result.groups[gk])}")
    lab.close()


@cli.command()
@click.argument("parent_id")
def overview(parent_id: str) -> None:
    """実験シリーズの概要を表示する。"""
    from labvault.core.aggregate import compute_stats, is_numeric, numeric_values_only

    lab = _get_lab()
    all_records = lab.list(limit=5000)
    children = [r for r in all_records if r.parent_id == parent_id]

    if not children:
        click.echo(f"No children found for {parent_id}")
        lab.close()
        return

    status_counts: dict[str, int] = {}
    condition_keys: dict[str, list[Any]] = {}
    result_keys: dict[str, list[float]] = {}

    for rec in children:
        st = str(rec.status)
        status_counts[st] = status_counts.get(st, 0) + 1
        for k, v in rec.get_conditions().items():
            condition_keys.setdefault(k, []).append(v)
        for k, v in rec.results.to_dict().items():
            if is_numeric(v):
                result_keys.setdefault(k, []).append(float(v))

    click.echo(f"Parent: {parent_id}  Children: {len(children)}")
    status_str = ", ".join(f"{k}={v}" for k, v in sorted(status_counts.items()))
    click.echo(f"Status: {status_str}")

    if condition_keys:
        click.echo("\nConditions:")
        for k, vals in sorted(condition_keys.items()):
            nums = numeric_values_only(vals)
            if nums and len(nums) == len(vals):
                stats = compute_stats(nums)
                click.echo(
                    f"  {k}: min={stats.min}  max={stats.max}  "
                    f"mean={stats.mean:.4f}  unique={len(set(nums))}"
                )
            else:
                unique = sorted(set(str(v) for v in vals))
                if len(unique) <= 10:
                    click.echo(f"  {k}: {', '.join(unique)}")
                else:
                    click.echo(f"  {k}: {len(unique)} unique values")

    if result_keys:
        click.echo("\nResults:")
        for k, vals in sorted(result_keys.items()):
            stats = compute_stats(vals)
            click.echo(
                f"  {k}: n={stats.count}  mean={stats.mean:.4f}  "
                f"min={stats.min}  max={stats.max}"
            )
    lab.close()


@cli.group()
def auth() -> None:
    """認証 (Personal Access Token) 関連のコマンド。"""


_DEFAULT_PLATFORM_URL = "https://labvault-api-355809880738.asia-northeast1.run.app"
_DEFAULT_TEAM = "konishi-lab"


def _credentials_path() -> Path:
    return Path.home() / ".labvault" / "credentials"


def _verify_token_against_backend(
    token: str, platform_url: str
) -> tuple[bool, str, str]:
    """PAT を backend に投げて検証する。`(ok, message, email)` を返す。

    email は `--user` を渡さなかったときの default 値として
    `auth_set_token` が拾う。失敗時は空文字。

    `requests`/`httpx` の重い依存を避けるため、標準ライブラリの
    `urllib` を使う。タイムアウト 10 秒。
    """
    import json as _json
    import urllib.error
    import urllib.request

    url = platform_url.rstrip("/") + "/api/auth/me"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.reason}", ""
    except (urllib.error.URLError, TimeoutError) as e:
        return False, f"network error: {e}", ""

    try:
        data = _json.loads(body)
    except ValueError:
        return False, "invalid JSON response", ""
    status = data.get("status", "?")
    if status != "authorized":
        return False, f"token accepted but status={status!r}", ""
    email = data.get("email", "")
    teams = ", ".join(
        t.get("team_id", "?") for t in (data.get("teams") or []) if isinstance(t, dict)
    )
    return True, f"verified: {email or '?'} (teams: {teams or '(none)'})", email


@auth.command("set-token")
@click.option(
    "--token",
    default=None,
    help=(
        "Personal Access Token (lv_*)。省略時は対話プロンプトで非表示入力。"
        " --token-stdin と排他。"
    ),
)
@click.option(
    "--token-stdin",
    is_flag=True,
    help="stdin から token を 1 行で受け取る (shell 履歴に残らない)。",
)
@click.option(
    "--platform-url",
    default=_DEFAULT_PLATFORM_URL,
    show_default=True,
    help="labvault platform API の URL。",
)
@click.option(
    "--team",
    default=_DEFAULT_TEAM,
    show_default=True,
    help="LABVAULT_TEAM に書き込む team 識別子。",
)
@click.option(
    "--user",
    default="",
    help=(
        "LABVAULT_USER に書き込む装置 / ユーザー識別子 (例: instrument-xrd-1)。"
        " Record の created_by に入る。"
    ),
)
@click.option(
    "--force",
    is_flag=True,
    help="既存 ~/.labvault/credentials を確認なしで上書きする。",
)
@click.option(
    "--verify/--no-verify",
    default=True,
    show_default=True,
    help="書き込み前に backend に問い合わせて token が有効か確認する。",
)
def auth_set_token(
    token: str | None,
    token_stdin: bool,
    platform_url: str,
    team: str,
    user: str,
    force: bool,
    verify: bool,
) -> None:
    """Personal Access Token を ~/.labvault/credentials に書き込む。

    1 つの PAT で pip install (PyPI proxy 経由) と SDK ランタイム認証の
    両方を賄える。発行は Web UI: <PLATFORM_URL>/account/tokens から。
    """
    import getpass
    import os
    import sys

    if token is not None and token_stdin:
        raise click.UsageError("--token と --token-stdin は同時指定不可")

    if token_stdin:
        token_value = sys.stdin.readline().strip()
    elif token is not None:
        token_value = token.strip()
    else:
        # 対話プロンプト (非表示入力)
        token_value = getpass.getpass("Personal Access Token (lv_*): ").strip()

    if not token_value:
        raise click.UsageError("token is empty")
    if not token_value.startswith("lv_"):
        raise click.UsageError("token must start with 'lv_'")

    # 検証 (backend 到達 + 有効性確認)。verify 成功時は backend が返す
    # email を後段で「--user 未指定時の default」として使う。
    verified_email = ""
    if verify:
        click.echo(f"Verifying token against {platform_url} ... ", nl=False)
        ok, msg, verified_email = _verify_token_against_backend(
            token_value, platform_url
        )
        click.echo(msg)
        if not ok:
            raise click.ClickException(
                "token verification failed. "
                "Use --no-verify to skip if you know it's OK."
            )

    # 上書き保護
    creds_path = _credentials_path()
    if creds_path.exists() and not force:
        raise click.ClickException(
            f"{creds_path} already exists. Re-run with --force to overwrite."
        )

    # user 未指定 + verify で email が取れた → default として採用。
    # 装置 PC のように複数人で 1 つの credentials を共有する場合は
    # `--user instrument-xrd-1` のような識別子を明示するのを推奨。
    user_auto = False
    if not user and verified_email:
        user = verified_email
        user_auto = True

    # ディレクトリ作成 + ファイル書き込み + パーミッション設定。
    # 0o700/0o600 は POSIX。Windows では ACL で本人のみ読書可になるように
    # 試みるが、失敗しても警告のみで継続 (NTFS でも user フォルダ配下なら
    # 通常は他ユーザーから見えない)。
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"LABVAULT_TOKEN={token_value}",
        f"LABVAULT_PLATFORM_URL={platform_url}",
        f"LABVAULT_TEAM={team}",
    ]
    if user:
        lines.append(f"LABVAULT_USER={user}")
    creds_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if os.name == "posix":
        try:
            os.chmod(creds_path.parent, 0o700)
            os.chmod(creds_path, 0o600)
        except OSError as e:
            click.echo(f"  warning: chmod failed: {e}", err=True)
    elif os.name == "nt":
        # Windows: icacls で本人 (UserName) のみに絞る。失敗時は警告のみ。
        import subprocess

        try:
            user_name = os.environ.get("USERNAME") or ""
            if user_name:
                subprocess.run(
                    [
                        "icacls",
                        str(creds_path),
                        "/inheritance:r",
                        "/grant:r",
                        f"{user_name}:F",
                    ],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except OSError as e:
            click.echo(f"  warning: icacls failed: {e}", err=True)

    click.echo(f"[OK] credentials saved: {creds_path}")
    if user_auto:
        click.echo(f"     LABVAULT_USER = {user}  (PAT 発行者を default 設定)")
        click.echo("     装置 PC など複数人で 1 つの credentials を共有する場合は")
        click.echo("     --user instrument-xrd-1 のように明示するのを推奨します。")
    click.echo("Try: labvault doctor")


@auth.command("status")
def auth_status() -> None:
    """`~/.labvault/credentials` の状況を表示する (token 全体は出さない).

    Settings 経由で env / .env もマージ表示するのは便利だが、副次的に
    「いまファイルに何が書かれているか」と一致しなくなる場合があるため、
    本コマンドは credentials ファイルを直接 parse する。
    """
    creds_path = _credentials_path()
    if not creds_path.exists():
        click.echo(f"  credentials file: (not present at {creds_path})")
        return
    click.echo(f"  credentials file: {creds_path}")

    pairs: dict[str, str] = {}
    for raw in creds_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        if key:
            pairs[key.strip()] = value.strip()

    token = pairs.get("LABVAULT_TOKEN", "")
    if token:
        masked = token[:8] + "..." if len(token) > 12 else "***"
        click.echo(f"  LABVAULT_TOKEN:        {masked}")
    else:
        click.echo("  LABVAULT_TOKEN:        (not in credentials)")
    click.echo(
        f"  LABVAULT_PLATFORM_URL: {pairs.get('LABVAULT_PLATFORM_URL', '(not set)')}"
    )
    click.echo(f"  LABVAULT_TEAM:         {pairs.get('LABVAULT_TEAM', '(not set)')}")
    click.echo(f"  LABVAULT_USER:         {pairs.get('LABVAULT_USER', '(not set)')}")


@cli.command("mcp")
def mcp_cmd() -> None:
    """MCP サーバーを起動する (stdio, ローカル直結).

    通常は Cloud Run 上のリモート MCP (`<platform_url>/mcp` + PAT) を推奨。
    本コマンドは SDK が入った環境でローカルの `Lab()` を直接触らせたい
    上級者向け (オフライン解析 / 装置 PC dev / MCP ツール開発)。
    """
    import sys

    from labvault.core.config import Settings
    from labvault.mcp.server import create_server

    settings = Settings()
    backend = "Firestore" if settings.gcp_project else "InMemory"
    storage = "Nextcloud" if settings.nextcloud_url else "InMemory"
    team = settings.team or "default"

    print("labvault MCP server starting (local stdio)...", file=sys.stderr)
    print("  通常は Cloud Run 上のリモート MCP 推奨。", file=sys.stderr)
    print("  詳細: README.md / docs/onboarding.md §3-B", file=sys.stderr)
    print(f"  Team:     {team}", file=sys.stderr)
    print(f"  Metadata: {backend}", file=sys.stderr)
    print(f"  Storage:  {storage}", file=sys.stderr)
    print("  Tools:    7", file=sys.stderr)
    print("  Transport: stdio", file=sys.stderr)
    print(file=sys.stderr)

    server = create_server()
    server.run(transport="stdio")


def _parse_conditions(specs: tuple[str, ...]) -> dict[str, Any]:
    """CLI 条件指定をパースする。

    Examples:
        "power=20"   -> {"power": 20}
        "power>=50"  -> {"power": {"gte": 50}}
        "power<=100" -> {"power": {"lte": 100}}
        "power>10"   -> {"power": {"gt": 10}}
        "power<100"  -> {"power": {"lt": 100}}
    """
    import re

    result: dict[str, Any] = {}
    for spec in specs:
        m = re.match(r"^(\w+)(>=|<=|>|<|!=|=)(.+)$", spec)
        if not m:
            click.echo(f"Warning: invalid condition format: {spec}", err=True)
            continue
        key, op, val_str = m.groups()

        # 数値変換を試みる
        try:
            val: Any = int(val_str)
        except ValueError:
            try:
                val = float(val_str)
            except ValueError:
                val = val_str

        op_map = {">=": "gte", "<=": "lte", ">": "gt", "<": "lt", "!=": "ne"}
        if op == "=":
            result[key] = val
        else:
            result.setdefault(key, {})
            if not isinstance(result[key], dict):
                result[key] = {}
            result[key][op_map[op]] = val
    return result


def _get_lab() -> Any:
    """CLI 用に Lab を初期化する。auto_log=False。"""
    from labvault import Lab

    return Lab()
