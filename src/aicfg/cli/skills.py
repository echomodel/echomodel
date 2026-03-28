"""CLI commands for cross-tool skill management."""

import json
import sys

import click
from rich.console import Console
from rich.table import Table

from aicfg.sdk import skills as sdk

console = Console()


@click.group()
def skills():
    """Manage cross-tool AI agent skills."""
    pass


@skills.group()
def marketplace():
    """Manage skill marketplaces."""
    pass


@marketplace.command(name="register")
@click.argument("alias")
@click.argument("url")
def marketplace_register(alias, url):
    """Register a marketplace. ALIAS is like owner/repo, URL is the git URL."""
    try:
        result = sdk.marketplace_register(alias, url)
        console.print(f"  [green]✓[/green] Registered {result['alias']} ({result['url']})")
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@marketplace.command(name="list")
def marketplace_list():
    """List registered marketplaces."""
    results = sdk.marketplace_list()
    if not results:
        click.echo("No marketplaces registered.")
        return
    for mp in results:
        console.print(f"  {mp['alias']}  [dim]{mp['url']}[/dim]")


@marketplace.command(name="remove")
@click.argument("alias")
def marketplace_remove(alias):
    """Remove a registered marketplace."""
    try:
        sdk.marketplace_remove(alias)
        console.print(f"  [red]✗[/red] Removed {alias}")
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@skills.command(name="list")
@click.option("--category", "-c", help="Filter by category")
@click.option("--target", "-t", type=click.Choice(["claude", "gemini"]), help="Filter by platform")
@click.option("--installed", is_flag=True, default=None, help="Show only installed skills")
@click.option("--not-installed", is_flag=True, default=None, help="Show only not-installed skills")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text", help="Output format")
def list_skills(category, target, installed, not_installed, fmt):
    """List available skills."""
    if installed and not_installed:
        click.echo("Cannot specify both --installed and --not-installed", err=True)
        sys.exit(1)

    installed_filter = None
    if installed:
        installed_filter = True
    elif not_installed:
        installed_filter = False

    results = sdk.list_skills(category=category, target=target, installed=installed_filter)

    if fmt == "json":
        console.print_json(json.dumps(results))
        return

    if not results:
        click.echo("No skills found.")
        return

    # Group by source
    from collections import OrderedDict
    grouped = OrderedDict()
    for s in results:
        source = s.get("source", "-")
        if source not in grouped:
            grouped[source] = []
        grouped[source].append(s)

    table = Table(title="Skills", expand=True)
    table.add_column("Name", style="cyan", no_wrap=True, ratio=2)
    table.add_column("Description", no_wrap=True, overflow="ellipsis", ratio=4)
    table.add_column("Claude", justify="center", width=6)
    table.add_column("Gemini", justify="center", width=6)

    for source, skills_in_source in grouped.items():
        label = "[dim](unmanaged)[/dim]" if source == "-" else f"[bold]{source}[/bold]"
        table.add_row(label, "", "", "", end_section=True)
        for s in skills_in_source:
            claude_status = "[green]✓[/green]" if s["installed"]["claude"] else "[dim]-[/dim]"
            gemini_status = "[green]✓[/green]" if s["installed"]["gemini"] else "[dim]-[/dim]"
            if "claude" not in s["effective_targets"]:
                claude_status = "[dim]n/a[/dim]"
            if "gemini" not in s["effective_targets"]:
                gemini_status = "[dim]n/a[/dim]"
            table.add_row(s["name"], s["description"], claude_status, gemini_status)

    console.print(table)


@skills.command()
@click.argument("name")
def show(name):
    """Show full details of a skill."""
    skill = sdk.get_skill(name)
    if not skill:
        click.echo(f"Skill not found: {name}", err=True)
        sys.exit(1)

    console.print(f"\n[bold cyan]{skill['name']}[/bold cyan]")
    console.print(f"  [dim]Description:[/dim] {skill['description']}")
    console.print(f"  [dim]Category:[/dim]    {skill['category'] or '(none)'}")
    console.print(f"  [dim]Invocation:[/dim]  {skill['invocation']}")
    console.print(f"  [dim]Targets:[/dim]     {', '.join(skill['effective_targets'])}")
    console.print(f"  [dim]Source:[/dim]      {skill.get('source', '-')}")

    for platform, is_installed in skill["installed"].items():
        if platform in skill["effective_targets"]:
            icon = "[green]✓ installed[/green]" if is_installed else "[dim]not installed[/dim]"
            console.print(f"  [dim]{platform}:[/dim]       {icon}")

    body_lines = skill["body"].strip().split("\n")
    preview = "\n".join(body_lines[:20])
    if len(body_lines) > 20:
        preview += f"\n... ({len(body_lines) - 20} more lines)"
    console.print(f"\n[dim]--- Body ---[/dim]\n{preview}\n")


@skills.command()
@click.argument("name")
@click.option("--target", "-t", type=click.Choice(["claude", "gemini"]), help="Install to specific platform only")
def install(name, target):
    """Install a skill to configured platforms."""
    try:
        result = sdk.install_skill(name, target=target)
        for path in result["installed"]:
            console.print(f"  [green]✓[/green] {path}")
        if result.get("from_cache"):
            console.print(f"  [yellow]Warning:[/yellow] Installed from cache")
        if result.get("message"):
            console.print(f"  [dim]{result['message']}[/dim]")
        console.print(f"  [dim]Source: {result['source']} ({result['url']})[/dim]")
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@skills.command()
@click.argument("name")
@click.option("--target", "-t", type=click.Choice(["claude", "gemini"]), help="Uninstall from specific platform only")
def uninstall(name, target):
    """Uninstall a skill from platforms."""
    try:
        removed = sdk.uninstall_skill(name, target=target)
        if not removed:
            click.echo(f"'{name}' was not installed on any platform.")
            return
        for path in removed:
            console.print(f"  [red]✗[/red] {path}")
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
