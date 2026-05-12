"""CLI for DeepSeek Toolkit."""
import typer

app = typer.Typer(name="dstk", help="DeepSeek Toolkit CLI", no_args_is_help=True)

eval_app = typer.Typer(name="eval", help="Run benchmarks and evaluate tool calling.")
trace_app = typer.Typer(name="trace", help="View and inspect execution traces.")

app.add_typer(eval_app)
app.add_typer(trace_app)


@app.callback()
def main():
    """DeepSeek Toolkit — reliability toolkit for DeepSeek tool calling."""


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
    from deepseek_toolkit.eval.loader import load_benchmark
    from deepseek_toolkit.eval.runner import EvalRunner
    from deepseek_toolkit.runtime import ToolRuntime

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
