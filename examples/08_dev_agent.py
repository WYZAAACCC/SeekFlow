"""Development Agent — a real, working agent powered by DeepSeek V4 Pro.

Capabilities: Python execution, file operations, web search, command execution.
Uses streaming output with thinking mode for complex problem solving.
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import traceback
from pathlib import Path

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not API_KEY:
    raise RuntimeError("DEEPSEEK_API_KEY environment variable is required")
MODEL = "deepseek-v4-pro"

from deepseek_toolkit.tools.decorator import tool
from deepseek_toolkit.tools.registry import ToolRegistry
from deepseek_toolkit.runtime import ToolRuntime
from deepseek_toolkit.tools.executor import ToolExecutor


# ═══════════════════════════════════════════════════════════════════════════════
# Tools
# ═══════════════════════════════════════════════════════════════════════════════

SANDBOX_DIR = Path(tempfile.mkdtemp(prefix="dev_agent_"))


@tool(name="run_python")
def run_python(code: str) -> dict:
    """Execute Python code and return stdout, stderr, and return value.

    Writes code to a temp file and executes it in a subprocess.
    Supports full Python syntax including indented blocks.
    10-second timeout.
    """
    import uuid
    script_path = SANDBOX_DIR / f"_run_{uuid.uuid4().hex[:8]}.py"
    script_path.write_text(code, encoding="utf-8")

    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True, text=True, timeout=10,
            cwd=str(SANDBOX_DIR),
            encoding="utf-8", errors="replace",
        )
        result = {
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "exit_code": proc.returncode,
        }
        return result
    except subprocess.TimeoutExpired:
        return {"error": "Timeout after 10 seconds"}
    finally:
        script_path.unlink(missing_ok=True)


@tool(name="write_file")
def write_file(path: str, content: str) -> str:
    """Write content to a file. Path is relative to sandbox directory."""
    full = SANDBOX_DIR / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} bytes to {path}"


@tool(name="read_file")
def read_file(path: str) -> str:
    """Read file contents. Path is relative to sandbox directory."""
    full = SANDBOX_DIR / path
    if not full.exists():
        return f"ERROR: File not found: {path}"
    content = full.read_text(encoding="utf-8")
    if len(content) > 8000:
        content = content[:8000] + f"\n... [truncated, {len(content)} total chars]"
    return content


@tool(name="list_files")
def list_files(directory: str = ".") -> list[str]:
    """List files and directories. Path relative to sandbox."""
    full = SANDBOX_DIR / directory
    if not full.exists():
        return [f"ERROR: Directory not found: {directory}"]
    items = []
    for p in sorted(full.iterdir()):
        prefix = "[DIR] " if p.is_dir() else "[FILE]"
        size = p.stat().st_size if p.is_file() else 0
        items.append(f"{prefix} {p.name} ({size:,} bytes)" if p.is_file() else f"{prefix} {p.name}")
    return items


@tool(name="web_search")
def web_search(query: str) -> str:
    """Search the web and return results. Uses DuckDuckGo text API (no key needed)."""
    import urllib.request
    import urllib.parse

    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(url, headers={"User-Agent": "DevAgent/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"Search failed: {e}"

    # Extract result snippets
    results = []
    import re
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
    for i, s in enumerate(snippets[:8]):
        text = re.sub(r'<[^>]+>', '', s).strip()
        if text:
            results.append(f"{i+1}. {text}")
    return "\n".join(results) if results else "No results found."


@tool(name="shell_command")
def shell_command(command: str) -> str:
    """Run a shell command inside the sandbox directory. Returns stdout+stderr."""
    try:
        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=30, cwd=str(SANDBOX_DIR),
        )
        out = proc.stdout.strip()
        err = proc.stderr.strip()
        parts = []
        if out:
            parts.append(out)
        if err:
            parts.append(f"[stderr]\n{err}")
        if proc.returncode != 0:
            parts.append(f"[exit code: {proc.returncode}]")
        return "\n".join(parts) if parts else "(no output)"
    except subprocess.TimeoutExpired:
        return "ERROR: Command timed out after 30 seconds"


# ═══════════════════════════════════════════════════════════════════════════════
# Agent
# ═══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are a Development Agent with real capabilities:
- Execute Python code
- Read/write files
- Search the web
- Run shell commands

Guidelines:
1. Think step by step. Break complex tasks into smaller steps.
2. For coding tasks: write the code, execute it, then fix errors if any.
3. For research tasks: search the web, read results, then synthesize.
4. Be concise. Show results, not explanations about what you're going to do.
5. When you complete a task, summarize what was done and what the result is.
6. Use the sandbox directory for all file operations (it's already set up)."""


def create_agent(streaming: bool = True):
    """Create the agent with all tools configured."""
    tools = [run_python, write_file, read_file, list_files, web_search, shell_command]

    rt = ToolRuntime(
        tools=tools,
        api_key=API_KEY,
        max_steps=15,
        max_result_chars=6000,
        repair=True,
        trace=True,
        cache_size=64,
        cache_ttl=300,
        timeout=120.0,
    )

    return rt, tools


def run_agent(task: str, streaming: bool = True):
    """Run the agent on a single task."""
    rt, tools = create_agent()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    print("=" * 70)
    print(f"  Dev Agent | model={MODEL} | sandbox={SANDBOX_DIR}")
    print("=" * 70)
    print(f"\nTask: {task}\n")

    if streaming:
        result = run_streaming(rt, messages)
    else:
        result = rt.chat(
            model=MODEL,
            messages=messages,
            extra_body={"thinking": {"type": "enabled"}},
        )
        _print_result_sync(result)

    return result


def run_streaming(rt, messages):
    """Run with streaming output for real-time feedback."""
    tool_idx = 0

    for event in rt.chat_stream(
        model=MODEL,
        messages=messages,
        extra_body={"thinking": {"type": "enabled"}},
    ):
        if event.type == "reasoning" and event.reasoning_content:
            print(f"\033[2m{event.reasoning_content}\033[0m", end="", flush=True)
        elif event.type == "content" and event.content:
            print(event.content, end="", flush=True)
        elif event.type == "tool_call_start":
            tool_idx += 1
            name = event.tool_name or "?"
            print(f"\n\n[{tool_idx}] Calling {name}...", flush=True)
        elif event.type == "tool_call_result":
            result = event.tool_result
            ok = True  # tool_result is present only on success
            status = "OK"
            preview = str(result)[:200]
            print(f"    [{status}] {preview}", flush=True)
        elif event.type == "done":
            print(f"\n\n{'='*70}")
            if event.usage:
                u = event.usage
                print(f"Tokens: prompt={u.get('prompt_tokens','?')} "
                      f"completion={u.get('completion_tokens','?')} "
                      f"total={u.get('total_tokens','?')}")
            return event

    return None


def _print_result_sync(result):
    """Print result for sync path."""
    for i, tr in enumerate(result.tool_results):
        status = "OK" if tr.ok else "FAIL"
        args_preview = json.dumps(tr.arguments, ensure_ascii=False)[:80]
        print(f"\n[{i+1}] {tr.name}({args_preview}) -> {status}")
        r = str(tr.result)[:300] if tr.result else "(none)"
        print(f"    {r}")
    print(f"\n{result.final}")

    tool_count = len(result.tool_results)
    ok_count = sum(1 for t in result.tool_results if t.ok)
    print(f"\n--- Summary ---")
    print(f"Tools: {tool_count} called ({ok_count} OK, {tool_count - ok_count} failed)")
    if result.usage:
        u = result.usage
        print(f"Tokens: prompt={u.get('prompt_tokens','?')} "
              f"completion={u.get('completion_tokens','?')} "
              f"total={u.get('total_tokens','?')}")
        cost_in = 1.74 * u.get('prompt_tokens', 0) / 1_000_000
        cost_out = 3.48 * u.get('completion_tokens', 0) / 1_000_000
        print(f"Est. cost: ${cost_in + cost_out:.5f}")
    if result.trace:
        td = result.trace.to_dict()
        print(f"Trace: {len(td.get('events',[]))} events, id={td.get('trace_id','?')[:8]}...")


# ═══════════════════════════════════════════════════════════════════════════════
# Interactive mode
# ═══════════════════════════════════════════════════════════════════════════════

def interactive():
    """Interactive agent session."""
    rt, tools = create_agent()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    print("=" * 70)
    print(f"  Dev Agent — Interactive Mode")
    print(f"  Model: {MODEL} | Sandbox: {SANDBOX_DIR}")
    print("  Type 'quit' to exit, 'clear' to reset context")
    print("=" * 70)

    while True:
        try:
            task = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not task:
            continue
        if task.lower() == "quit":
            break
        if task.lower() == "clear":
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            print("Context cleared.")
            continue

        messages.append({"role": "user", "content": task})

        result = rt.chat(
            model=MODEL,
            messages=messages,
            extra_body={"thinking": {"type": "enabled"}},
        )

        # Update conversation with what happened
        messages.append({"role": "assistant", "content": result.final})
        _print_result_sync(result)


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "-i":
            interactive()
        else:
            task = " ".join(sys.argv[1:])
            run_agent(task, streaming=False)
    else:
        # Default: run a demo task
        print("No task provided. Running demo task...\n")
        task = (
            "Create a Python script called fibonacci.py that calculates Fibonacci numbers, "
            "then run it to show fib(20). After that, search the web for 'Fibonacci sequence applications in real life' "
            "and write a short summary to a file called fibonacci_notes.txt."
        )
        run_agent(task, streaming=False)
