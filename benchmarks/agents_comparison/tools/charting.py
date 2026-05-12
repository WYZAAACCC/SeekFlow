"""Chart generation tools — matplotlib-based charts and financial tables."""

import json
import sys
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "output"


def generate_chart(data_json: str, chart_type: str, title: str, filename: str) -> str:
    """Generate a chart (line, bar, pie, candlestick) from JSON data and save as PNG.

    Args:
        data_json: JSON string with chart data. Format depends on chart_type:
            - line/bar: {"labels": [...], "values": [...], "ylabel": "..."}
            - multi-bar: {"labels": [...], "series": {"Series1": [...], "Series2": [...]}, "ylabel": "..."}
            - pie: {"labels": [...], "values": [...]}
            - scatter: {"x": [...], "y": [...], "xlabel": "...", "ylabel": "..."}
        chart_type: "line", "bar", "pie", or "scatter"
        title: Chart title
        filename: Output PNG filename (saved to output/charts/)

    Returns:
        Status message with saved file path
    """
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm
    except ImportError:
        return "ERROR: matplotlib not installed. Run: pip install matplotlib"

    # Set up Chinese font
    try:
        # Try common Chinese fonts on Windows
        for font_name in ['Microsoft YaHei', 'SimHei', 'KaiTi', 'FangSong']:
            try:
                fm.findfont(font_name, fallback_to_default=False)
                plt.rcParams['font.sans-serif'] = [font_name, 'DejaVu Sans']
                break
            except Exception:
                continue
    except Exception:
        pass
    plt.rcParams['axes.unicode_minus'] = False

    try:
        data = json.loads(data_json)
    except json.JSONDecodeError as e:
        return f"ERROR: Invalid JSON data: {e}"

    fig, ax = plt.subplots(figsize=(10, 6))

    try:
        if chart_type == "line":
            ax.plot(data.get("labels", []), data.get("values", []), 'b-o', linewidth=2, markersize=6)
            if data.get("ylabel"):
                ax.set_ylabel(data["ylabel"])

        elif chart_type == "bar":
            labels = data.get("labels", [])
            values = data.get("values", [])
            colors = plt.cm.Blues([0.4 + 0.15 * i for i in range(len(values))]) if len(values) < 20 else 'steelblue'
            ax.bar(labels, values, color=colors)
            if data.get("ylabel"):
                ax.set_ylabel(data["ylabel"])
            plt.xticks(rotation=45, ha='right')

        elif chart_type == "pie":
            values = data.get("values", [])
            labels = data.get("labels", [])
            colors = plt.cm.Set3(range(len(values)))
            ax.pie(values, labels=labels, autopct='%1.1f%%', colors=colors, startangle=90)
            ax.axis('equal')

        elif chart_type == "scatter":
            ax.scatter(data.get("x", []), data.get("y", []), alpha=0.6, c='steelblue')
            if data.get("xlabel"):
                ax.set_xlabel(data["xlabel"])
            if data.get("ylabel"):
                ax.set_ylabel(data["ylabel"])

        else:
            plt.close()
            return f"ERROR: Unknown chart_type '{chart_type}'. Use 'line', 'bar', 'pie', or 'scatter'."

        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3)

        # Save
        charts_dir = OUTPUT_DIR / "charts"
        charts_dir.mkdir(parents=True, exist_ok=True)
        filepath = charts_dir / filename
        plt.tight_layout()
        plt.savefig(str(filepath), dpi=150, bbox_inches='tight')
        plt.close()

        return f"Chart saved: {filepath} ({filepath.stat().st_size} bytes)"

    except Exception as e:
        plt.close()
        return f"Chart generation error: {e}"


def generate_financial_table(data_json: str, title: str, filename: str) -> str:
    """Generate a formatted financial table from JSON data and save as text file.

    Args:
        data_json: JSON with format:
            {"headers": ["Col1", "Col2", ...], "rows": [["val1", "val2", ...], ...],
             "notes": "optional footnote"}
        title: Table title
        filename: Output filename (.txt)

    Returns:
        Status message with file path
    """
    try:
        data = json.loads(data_json)
    except json.JSONDecodeError as e:
        return f"ERROR: Invalid JSON data: {e}"

    headers = data.get("headers", [])
    rows = data.get("rows", [])
    notes = data.get("notes", "")

    if not headers or not rows:
        return "ERROR: Table requires 'headers' and 'rows' in JSON data"

    # Calculate column widths
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(str(cell)))

    # Build table
    lines = []
    lines.append(f"\n{'=' * (sum(col_widths) + len(headers) * 3 + 1)}")
    lines.append(f"  {title}")
    lines.append(f"{'=' * (sum(col_widths) + len(headers) * 3 + 1)}")

    # Header
    header_line = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    lines.append(header_line)
    lines.append("|-" + "-|-".join("-" * w for w in col_widths) + "-|")

    # Rows
    for row in rows:
        row_line = "| " + " | ".join(str(row[i]).ljust(col_widths[i]) if i < len(row) else "".ljust(col_widths[i]) for i in range(len(headers))) + " |"
        lines.append(row_line)

    lines.append(f"{'=' * (sum(col_widths) + len(headers) * 3 + 1)}")
    if notes:
        lines.append(f"\nNote: {notes}")

    # Save
    tables_dir = OUTPUT_DIR / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    filepath = tables_dir / filename
    content = "\n".join(lines)
    filepath.write_text(content, encoding="utf-8")

    return f"Table saved: {filename} ({len(content)} bytes)\n\n{content}"
