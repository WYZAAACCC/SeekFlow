"""CLI for SeekFlow."""
import json
import sys
from pathlib import Path

import typer

app = typer.Typer(name="seekflow", help="SeekFlow CLI", no_args_is_help=True)

eval_app = typer.Typer(name="eval", help="Run benchmarks and evaluate tool calling.")
trace_app = typer.Typer(name="trace", help="View and inspect execution traces.")
tool_app = typer.Typer(name="tool", help="Inspect, verify, install, and audit tools.")
audit_app = typer.Typer(name="audit", help="Verify and export durable audit trails.")

app.add_typer(eval_app)
app.add_typer(trace_app)
app.add_typer(tool_app)
app.add_typer(audit_app)


@app.callback()
def main():
    """SeekFlow — reliability toolkit for DeepSeek tool calling."""


# ═══════════════════════════════════════════════════════════════════
# Tool subcommands (PR-9: Lv3 tool registry CLI)
# ═══════════════════════════════════════════════════════════════════

@tool_app.command("inspect")
def tool_inspect(
    path: str = typer.Argument(..., help="Path to manifest (.yaml/.json)."),
):
    """Inspect a tool manifest and display its details."""
    from seekflow.tools.manifest_loader import load_manifest

    try:
        manifest = load_manifest(path)
    except Exception as e:
        typer.echo(f"Error loading manifest: {e}", err=True)
        raise typer.Exit(code=1)

    _print_manifest_detail(manifest)


@tool_app.command("verify")
def tool_verify(
    path: str = typer.Argument(..., help="Path to manifest (.yaml/.json)."),
    strict: bool = typer.Option(False, "--strict", help="Require signature for external tools."),
):
    """Verify a tool manifest's integrity (digest + signature)."""
    from seekflow.tools.manifest_loader import load_manifest
    from seekflow.tools.manifest_verify import verify_manifest, ManifestVerificationError

    try:
        manifest = load_manifest(path)
    except Exception as e:
        typer.echo(f"Error loading manifest: {e}", err=True)
        raise typer.Exit(code=1)

    try:
        verify_manifest(manifest, strict=strict)
        typer.echo(f"[OK] Manifest '{manifest.name}' (v{manifest.version}) verified.")
        if manifest.signature:
            typer.echo(f"     Signature: present (key={manifest.signing_key_id or 'unknown'})")
        else:
            typer.echo(f"     Signature: none (source={manifest.source})")
        typer.echo(f"     Digest: {manifest.package_digest[:16]}...")
    except ManifestVerificationError as e:
        typer.echo(f"[FAIL] Verification failed: {e}", err=True)
        raise typer.Exit(code=1)


@tool_app.command("install")
def tool_install(
    path: str = typer.Argument(..., help="Path to manifest (.yaml/.json)."),
    strict: bool = typer.Option(False, "--strict", help="Require signature for external tools."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate only, don't persist."),
):
    """Install a tool from a manifest — verify, compile, lint, and register."""
    from seekflow.tools.manifest_loader import load_manifest
    from seekflow.tools.manifest_verify import verify_manifest, compute_manifest_digest
    from seekflow.tools.policy_compiler import compile_policy
    from seekflow.tools.policy_linter import lint_policy, has_errors
    from seekflow.tools.registry import ToolRegistry
    from seekflow.errors import ToolSchemaError

    # 1. Load
    try:
        manifest = load_manifest(path)
    except Exception as e:
        typer.echo(f"Error loading manifest: {e}", err=True)
        raise typer.Exit(code=1)

    # 2. Verify
    try:
        verify_manifest(manifest, strict=strict)
    except Exception as e:
        typer.echo(f"Verification failed: {e}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"[OK] Manifest verified: {manifest.name} v{manifest.version}")

    # 3. Compile
    policy = compile_policy(manifest)
    typer.echo(f"     Policy: risk={policy.risk} runner={policy.runner}")

    # 4. Lint
    issues = lint_policy(policy, source=manifest.source)
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]

    if errors:
        typer.echo(f"[FAIL] Policy lint found {len(errors)} error(s):", err=True)
        for e in errors:
            typer.echo(f"  [{e.code}] {e.message}", err=True)
        raise typer.Exit(code=1)

    if warnings:
        for w in warnings:
            typer.echo(f"  [WARN] [{w.code}] {w.message}")

    # 5. Register
    if dry_run:
        typer.echo("[OK] Dry-run passed — tool would be installed.")
        return

    try:
        registry = ToolRegistry()
        td = registry.register_from_manifest(manifest, strict=strict)

        # Persist to ~/.seekflow/tools/
        _persist_installed_tool(manifest, td)

        typer.echo(f"[OK] Installed: {td.name}")
        typer.echo(f"     Source: {td.source}")
        typer.echo(f"     Policy hash: {compute_manifest_digest(manifest)[:16]}")
    except ToolSchemaError as e:
        typer.echo(f"[FAIL] Registration failed: {e}", err=True)
        raise typer.Exit(code=1)


@tool_app.command("list")
def tool_list():
    """List installed tools from ~/.seekflow/tools/registry.json."""
    registry_path = _get_tool_registry_path()
    if not registry_path.exists():
        typer.echo("No tools installed.")
        return

    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except Exception as e:
        typer.echo(f"Error reading registry: {e}", err=True)
        raise typer.Exit(code=1)

    tools = data.get("tools", [])
    if not tools:
        typer.echo("No tools installed.")
        return

    typer.echo(f"{'NAME':<30} {'VERSION':<12} {'SOURCE':<12} {'RISK':<10} {'RUNNER':<18}")
    typer.echo("-" * 82)
    for t in tools:
        typer.echo(
            f"{t['name']:<30} {t['version']:<12} {t['source']:<12} "
            f"{t.get('risk', 'read'):<10} {t.get('runner', 'auto'):<18}"
        )


@tool_app.command("audit")
def tool_audit(
    name: str = typer.Argument(..., help="Tool name to show audit history for."),
):
    """Show audit history for an installed tool."""
    audit_path = _get_tool_audit_path(name)
    if not audit_path.exists():
        typer.echo(f"No audit history for tool '{name}'.")
        return

    from seekflow.audit.store import JSONLAuditStore
    store = JSONLAuditStore(audit_path)
    events = store.read_all()

    if not events:
        typer.echo(f"No audit events for tool '{name}'.")
        return

    valid, msg = None, ""
    try:
        from seekflow.audit.store import verify_audit_chain
        valid, msg = verify_audit_chain(events)
    except Exception:
        valid = None

    typer.echo(f"Audit trail for '{name}': {len(events)} events")
    if valid is not None:
        status = "[OK] Chain valid" if valid else f"[FAIL] {msg}"
        typer.echo(status)

    for ev in events[:20]:  # limit to last 20
        ts = ev.get("ts", "")[:19]
        etype = ev.get("event_type", "")
        ok = "OK" if ev.get("ok") else "FAIL"
        tool = ev.get("tool_name", "")
        runner = ev.get("runner", "")
        elapsed = ev.get("elapsed_ms", 0)
        typer.echo(f"  {ts}  {etype:<20} {ok:<5} {tool:<20} {runner:<20} {elapsed}ms")


# ═══════════════════════════════════════════════════════════════════
# Audit subcommands (Phase F: durable audit CLI)
# ═══════════════════════════════════════════════════════════════════

@audit_app.command("verify")
def audit_verify(
    path: str = typer.Argument(..., help="Path to audit.jsonl file."),
):
    """Verify the hash chain integrity of an audit trail file."""
    audit_path = Path(path)
    if not audit_path.exists():
        typer.echo(f"File not found: {path}", err=True)
        raise typer.Exit(code=1)

    from seekflow.audit.store import JSONLAuditStore, verify_audit_chain
    store = JSONLAuditStore(audit_path)
    events = store.read_all()

    if not events:
        typer.echo("No events found in audit file.")
        return

    typer.echo(f"Events: {len(events)}")
    valid, msg = verify_audit_chain(events)

    if valid:
        typer.echo("[OK] Audit chain is valid — no tampering detected.")
    else:
        typer.echo(f"[FAIL] {msg}", err=True)
        raise typer.Exit(code=1)


@audit_app.command("export")
def audit_export(
    run_id: str = typer.Option(None, "--run-id", help="Filter by run ID."),
    path: str = typer.Argument(..., help="Path to audit.jsonl or audit.db file."),
    output: str = typer.Option(None, "--output", "-o", help="Output file (stdout if omitted)."),
):
    """Export audit events as JSON, optionally filtered by run_id."""
    audit_path = Path(path)
    if not audit_path.exists():
        typer.echo(f"File not found: {path}", err=True)
        raise typer.Exit(code=1)

    suffix = audit_path.suffix.lower()
    if suffix == ".db":
        from seekflow.audit.store import SQLiteAuditStore
        store = SQLiteAuditStore(audit_path)
        if run_id:
            events = store.query_by_run(run_id)
        else:
            events = []  # SQLite requires run_id filter
            typer.echo("SQLite export requires --run-id", err=True)
            raise typer.Exit(code=1)
        store.close()
    else:
        from seekflow.audit.store import JSONLAuditStore
        store = JSONLAuditStore(audit_path)
        all_events = store.read_all()
        if run_id:
            events = [e for e in all_events if e.get("run_id") == run_id]
        else:
            events = all_events

    output_json = json.dumps(events, indent=2, ensure_ascii=False)
    if output:
        Path(output).write_text(output_json, encoding="utf-8")
        typer.echo(f"Exported {len(events)} events to {output}")
    else:
        typer.echo(output_json)


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def _get_seekflow_dir() -> Path:
    """Get ~/.seekflow/ directory, creating if needed."""
    home = Path.home() / ".seekflow"
    home.mkdir(parents=True, exist_ok=True)
    return home


def _get_tool_registry_path() -> Path:
    return _get_seekflow_dir() / "tools" / "registry.json"


def _get_tool_audit_path(name: str) -> Path:
    return _get_seekflow_dir() / "tools" / "audit" / f"{name}.jsonl"


def _persist_installed_tool(manifest, tool_def) -> None:
    """Persist an installed tool to ~/.seekflow/tools/registry.json."""
    tools_dir = _get_seekflow_dir() / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)

    registry_path = tools_dir / "registry.json"
    if registry_path.exists():
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    else:
        data = {"version": "1", "tools": []}

    # Remove existing entry with same name
    data["tools"] = [t for t in data["tools"] if t["name"] != manifest.name]

    data["tools"].append({
        "name": manifest.name,
        "version": manifest.version,
        "source": manifest.source,
        "risk": manifest.risk,
        "runner": tool_def.policy.runner if tool_def.policy else "auto",
        "installed_at": _now_iso(),
        "manifest_digest": tool_def.metadata.get("manifest_digest", ""),
    })

    registry_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _print_manifest_detail(manifest) -> None:
    """Pretty-print manifest details to stdout."""
    typer.echo(f"Name:        {manifest.name}")
    typer.echo(f"Version:     {manifest.version}")
    typer.echo(f"Source:      {manifest.source}")
    typer.echo(f"Publisher:   {manifest.publisher or '(none)'}")
    typer.echo(f"Risk:        {manifest.risk}")
    typer.echo(f"Capabilities:{' '.join(sorted(manifest.capabilities)) if manifest.capabilities else ' (none)'}")
    typer.echo(f"Digest:      {manifest.package_digest}")
    if manifest.signature:
        typer.echo(f"Signature:   present (key={manifest.signing_key_id})")
    typer.echo(f"Entrypoint:  {manifest.entrypoint}")
    typer.echo(f"Schema ver:  {manifest.schema_version}")

    sandbox = manifest.sandbox
    typer.echo(f"Sandbox:     runner={sandbox.runner} image={sandbox.image or 'default'} "
               f"network={sandbox.network} mem={sandbox.memory_mb}MB")

    if manifest.network.allowed_domains:
        typer.echo(f"Network:     domains={manifest.network.allowed_domains}")
    if manifest.filesystem.workspace_root:
        typer.echo(f"Filesystem:  root={manifest.filesystem.workspace_root} "
                   f"read_only={manifest.filesystem.read_only}")


@eval_app.command("run")
def eval_run(
    path: str = typer.Argument(..., help="Path to benchmark YAML file."),
    model: str = typer.Option("deepseek-chat", "--model", "-m", help="Model to use."),
    api_key: str = typer.Option(None, "--api-key", help="DeepSeek API key."),
    batch: bool = typer.Option(
        False, "--batch",
        help="Use Batch API (50% cheaper, single-step only — no multi-turn tool loops).",
    ),
    batch_poll_interval: float = typer.Option(
        30.0, "--batch-poll-interval",
        help="Seconds between batch status checks.",
    ),
    batch_max_wait: float = typer.Option(
        3600.0, "--batch-max-wait",
        help="Maximum seconds to wait for batch completion.",
    ),
):
    """Run a benchmark file."""
    from seekflow.eval.loader import load_benchmark
    from seekflow.eval.runner import EvalRunner
    from seekflow.runtime import ToolRuntime

    name, bench_model, cases = load_benchmark(path)
    effective_model = model or bench_model

    runtime = ToolRuntime(api_key=api_key)
    runner = EvalRunner(runtime, model=effective_model)

    if batch:
        report = runner.run_cases_batch(
            cases,
            poll_interval=batch_poll_interval,
            max_wait=batch_max_wait,
        )
        report.name = name
    else:
        report = runner.run_cases(cases)
        report.name = name

    report.print()


@trace_app.command("view")
def trace_view(
    path: str = typer.Argument(..., help="Path to trace JSON file."),
):
    """View a trace JSON file."""
    import json

    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:
        data = json.loads(open(path, encoding="utf-8").read())
        for event in data.get("events", []):
            print(f"[{event['type']}] {event.get('timestamp', '')}")
        return

    console = Console()
    data = json.loads(open(path, encoding="utf-8").read())

    console.print()
    console.print(f"[bold]Trace:[/bold] {data.get('trace_id', 'unknown')}")
    console.print(f"[bold]Model:[/bold] {data.get('model', 'unknown')}")
    console.print(f"[bold]Started:[/bold] {data.get('started_at', '')}")
    console.print(f"[bold]Ended:[/bold] {data.get('ended_at', '')}")
    console.print()

    table = Table(title="Events")
    table.add_column("Type", style="cyan")
    table.add_column("Step", style="green")
    table.add_column("Details", style="")

    for event in data.get("events", []):
        etype = event.get("type", "")
        step = str(event.get("data", {}).get("step", ""))
        details = ""
        if etype == "model_request":
            details = f"messages={event['data'].get('message_count', '')}"
        elif etype == "model_response":
            details = f"finish={event['data'].get('finish_reason', '')}"
        elif etype == "tool_call_start":
            details = f"tool={event['data'].get('name', '')}"
        elif etype == "tool_call_result":
            details = f"ok={event['data'].get('ok', '')} elapsed={event['data'].get('elapsed_ms', '')}ms"
        table.add_row(etype, step, details)

    console.print(table)
