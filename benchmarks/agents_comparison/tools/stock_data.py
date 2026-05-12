"""Real stock data fetcher — uses Sina K-line API (China-accessible, free).

Provides daily OHLCV data for Chinese A-shares (Shanghai/Shenzhen).
No API key required.
"""
import json
import urllib.request
import urllib.parse


def fetch_stock_data(symbol: str, period: str = "6mo") -> str:
    """Fetch real stock price data.

    Args:
        symbol: Stock ticker symbol (e.g., '000001.SZ' for Ping An Bank,
                '600519.SH' for Kweichow Moutai)
        period: Time period — '1mo', '3mo', '6mo', '1y', '2y', '5y'

    Returns:
        CSV-formatted price data with Date,Open,High,Low,Close,Volume columns
    """
    symbol_lower = symbol.lower()
    if ".sz" in symbol_lower:
        code = symbol_lower.replace(".sz", "")
        sina_symbol = f"sz{code}"
    elif ".sh" in symbol_lower:
        code = symbol_lower.replace(".sh", "")
        sina_symbol = f"sh{code}"
    elif ".hk" in symbol_lower:
        code = symbol_lower.replace(".hk", "")
        sina_symbol = f"hk{code}"
    else:
        return (
            f"ERROR: Unsupported symbol: {symbol}. "
            f"Use formats like '000001.SZ', '600519.SH', '0700.HK'"
        )

    # Map period to datalen (approximate trading days)
    period_days = {
        "1mo": 22, "3mo": 66, "6mo": 130,
        "1y": 260, "2y": 520, "5y": 1300,
    }
    datalen = period_days.get(period, 130)

    # Try Sina K-line API first (works in China)
    result = _fetch_sina_kline(sina_symbol, datalen)
    if result and not result.startswith("ERROR") and not result.startswith("Failed"):
        return result

    # Fallback: East Money K-line API
    result = _fetch_eastmoney(symbol, period)
    if result and not result.startswith("ERROR") and not result.startswith("Failed"):
        return result

    return f"Failed to fetch stock data for {symbol}. Both Sina and East Money APIs unavailable."


def _fetch_sina_kline(sina_symbol: str, datalen: int) -> str:
    """Fetch K-line data from Sina finance API."""
    try:
        url = (
            f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            f"CN_MarketData.getKLineData?symbol={sina_symbol}&scale=240"
            f"&ma=no&datalen={datalen}"
        )
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8", errors="replace")

        if not text or text.startswith("null") or len(text) < 10:
            return f"No data from Sina for {sina_symbol}"

        data = json.loads(text)
        if not data:
            return f"No data returned for {sina_symbol}"

        # Build CSV
        lines = ["Date,Open,High,Low,Close,Volume"]
        for item in data:
            date = item.get("day", "")
            open_p = item.get("open", "")
            high = item.get("high", "")
            low = item.get("low", "")
            close = item.get("close", "")
            volume = item.get("volume", "")
            lines.append(f"{date},{open_p},{high},{low},{close},{volume}")

        # Get stock name from real-time quote
        name = _get_sina_name(sina_symbol)

        result = f"# {name} ({sina_symbol}) — {len(data)} trading days\n"
        result += "\n".join(lines)
        result += f"\n# Total: {len(data)} trading days"

        if len(result) > 8000:
            # Keep header + first 60 rows + last 10 rows
            all_lines = result.split("\n")
            header = all_lines[:2]
            body = all_lines[2:-1]
            footer = all_lines[-1]
            if len(body) > 70:
                kept = body[:60] + [f"... [truncated {len(body)-70} rows] ..."] + body[-10:]
            else:
                kept = body
            result = "\n".join(header + kept + [footer])
            if len(result) > 8000:
                result = result[:8000] + f"\n... [truncated, {len(body)} total rows]"

        return result

    except json.JSONDecodeError:
        return f"Failed to parse Sina response for {sina_symbol}"
    except Exception as e:
        return f"Sina K-line failed for {sina_symbol}: {e}"


def _get_sina_name(sina_symbol: str) -> str:
    """Get stock name from Sina real-time quote."""
    try:
        url = f"https://hq.sinajs.cn/list={sina_symbol}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn/",
        })
        with urllib.request.urlopen(req, timeout=5) as resp:
            text = resp.read().decode("gbk", errors="replace")
        # Format: var hq_str_sh600519="name,..."
        if '="' in text:
            name_part = text.split('="')[1].split(",")[0]
            return name_part if name_part else sina_symbol
    except Exception:
        pass
    return sina_symbol


def _fetch_eastmoney(symbol: str, period: str) -> str:
    """Fallback: East Money K-line API."""
    period_map = {
        "1mo": "101", "3mo": "103", "6mo": "106",
        "1y": "101", "2y": "102", "5y": "105",
    }
    period_code = period_map.get(period, "106")

    symbol_upper = symbol.upper()
    if ".SZ" in symbol_upper:
        secid = f"0.{symbol_upper.replace('.SZ', '')}"
    elif ".SH" in symbol_upper:
        secid = f"1.{symbol_upper.replace('.SH', '')}"
    else:
        return f"East Money does not support: {symbol}"

    try:
        url = (
            f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
            f"secid={secid}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57&"
            f"klt={period_code}&fqt=1&end=20500101&lmt=120"
        )
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://quote.eastmoney.com/",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if not data.get("data") or not data["data"].get("klines"):
            return "East Money returned no data"

        klines = data["data"]["klines"]
        name = data["data"].get("name", symbol)
        lines = ["Date,Open,High,Low,Close,Volume"]
        for k in klines:
            parts = k.split(",")
            if len(parts) >= 6:
                date, open_p, close_p, high, low, volume = (
                    parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
                )
                lines.append(f"{date},{open_p},{high},{low},{close_p},{volume}")

        result = f"# {name} ({symbol}) — {period}\n"
        result += "\n".join(lines)
        if len(result) > 8000:
            result = result[:8000] + f"\n... [truncated, {len(lines)-1} total rows]"
        return result

    except Exception as e:
        return f"East Money failed: {e}"
