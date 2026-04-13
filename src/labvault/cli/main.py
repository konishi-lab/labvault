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
@click.argument("query")
@click.option("--limit", "-n", default=20, help="表示件数")
def search(query: str, limit: int) -> None:
    """レコードを検索する。"""
    lab = _get_lab()
    results = lab.search(query, limit=limit)
    if not results:
        click.echo("No results found.")
    else:
        for rec in results:
            click.echo(f"{rec.id}  {rec.title}  ({rec.status})")
    lab.close()


@cli.command()
def doctor() -> None:
    """設定の健全性をチェックする。"""
    from labvault.core.config import Settings

    click.echo("labvault doctor\n")
    all_ok = True

    # config.toml
    config_path = Path.home() / ".labvault" / "config.toml"
    if config_path.exists():
        click.echo(f"  [OK] config.toml: {config_path}")
    else:
        click.echo(f"  [!!] config.toml: not found ({config_path})")
        all_ok = False

    # Settings
    try:
        settings = Settings()
        click.echo(f"  [OK] team: {settings.team or '(not set)'}")
        click.echo(f"  [OK] user: {settings.user or '(not set)'}")
    except Exception as e:
        click.echo(f"  [!!] Settings: {e}")
        all_ok = False
        settings = None

    # Python
    click.echo(f"  [OK] Python: {sys.version.split()[0]}")

    # Nextcloud
    if settings and settings.nextcloud_url:
        try:
            import httpx

            resp = httpx.get(f"{settings.nextcloud_url}/status.php", timeout=5)
            if resp.status_code == 200:
                click.echo(f"  [OK] Nextcloud: {settings.nextcloud_url}")
            else:
                click.echo(f"  [!!] Nextcloud: HTTP {resp.status_code}")
                all_ok = False
        except Exception as e:
            click.echo(f"  [!!] Nextcloud: {e}")
            all_ok = False
    else:
        click.echo("  [--] Nextcloud: not configured")

    # GCP
    if settings and settings.gcp_project:
        click.echo(f"  [OK] GCP project: {settings.gcp_project}")
    else:
        click.echo("  [--] GCP project: not configured")

    click.echo()
    if all_ok:
        click.echo("All checks passed.")
    else:
        click.echo("Some checks failed. See above.")


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


@cli.command("mcp")
def mcp_cmd() -> None:
    """MCP サーバーを起動する (stdio)."""
    import sys

    from labvault.core.config import Settings
    from labvault.mcp.server import create_server

    settings = Settings()
    backend = "Firestore" if settings.gcp_project else "InMemory"
    storage = "Nextcloud" if settings.nextcloud_url else "InMemory"
    team = settings.team or "default"

    print("labvault MCP server starting...", file=sys.stderr)
    print(f"  Team:     {team}", file=sys.stderr)
    print(f"  Metadata: {backend}", file=sys.stderr)
    print(f"  Storage:  {storage}", file=sys.stderr)
    print("  Tools:    6", file=sys.stderr)
    print("  Transport: stdio", file=sys.stderr)
    print(file=sys.stderr)

    server = create_server()
    server.run(transport="stdio")


def _get_lab() -> Any:
    """CLI 用に Lab を初期化する。auto_log=False。"""
    from labvault import Lab

    return Lab()
