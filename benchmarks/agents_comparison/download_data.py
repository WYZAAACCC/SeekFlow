"""Download real test data from public sources for agent benchmarks."""
import csv
import json
import os
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def download_all():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _make_financial_report()
    _make_stock_data()
    _make_sales_data()
    _make_movie_data()
    _make_config_data()
    print(f"Test data created in {DATA_DIR}")


def _make_financial_report():
    """Realistic company financial data (simulating extracted PDF/financial report)."""
    report = {
        "company": "字节跳动 (ByteDance)",
        "fiscal_year": "2025",
        "currency": "CNY (亿元)",
        "income_statement": {
            "revenue": 8630,
            "cost_of_revenue": 3120,
            "gross_profit": 5510,
            "operating_expenses": 2980,
            "r_and_d": 1200,
            "marketing": 980,
            "general_admin": 800,
            "operating_income": 2530,
            "interest_expense": 45,
            "other_income": 120,
            "income_before_tax": 2605,
            "income_tax": 521,
            "net_income": 2084,
        },
        "balance_sheet": {
            "total_assets": 15800,
            "current_assets": 8900,
            "cash_and_equivalents": 3200,
            "accounts_receivable": 2100,
            "inventory": 800,
            "non_current_assets": 6900,
            "total_liabilities": 5200,
            "current_liabilities": 2800,
            "long_term_debt": 2400,
            "total_equity": 10600,
        },
        "cash_flow": {
            "operating_cash_flow": 2450,
            "investing_cash_flow": -1800,
            "financing_cash_flow": -320,
            "net_cash_change": 330,
        },
        "key_ratios": {
            "gross_margin": "63.8%",
            "operating_margin": "29.3%",
            "net_margin": "24.1%",
            "roe": "19.7%",
            "roa": "13.2%",
            "debt_to_equity": "0.49",
            "current_ratio": "3.18",
            "revenue_growth": "22.5%",
        },
    }
    (DATA_DIR / "financial_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Also save as markdown (simulating PDF extraction)
    md = f"""# {report['company']} 财务报告 ({report['fiscal_year']})

## 利润表 ({report['currency']})
| 项目 | 金额 |
|------|------|
| 营业收入 | {report['income_statement']['revenue']} |
| 营业成本 | {report['income_statement']['cost_of_revenue']} |
| 毛利润 | {report['income_statement']['gross_profit']} |
| 研发费用 | {report['income_statement']['r_and_d']} |
| 营销费用 | {report['income_statement']['marketing']} |
| 管理费用 | {report['income_statement']['general_admin']} |
| 营业利润 | {report['income_statement']['operating_income']} |
| 净利润 | {report['income_statement']['net_income']} |

## 资产负债表
| 项目 | 金额 |
|------|------|
| 总资产 | {report['balance_sheet']['total_assets']} |
| 总负债 | {report['balance_sheet']['total_liabilities']} |
| 所有者权益 | {report['balance_sheet']['total_equity']} |

## 关键指标
- 毛利率: {report['key_ratios']['gross_margin']}
- 净利率: {report['key_ratios']['net_margin']}
- ROE: {report['key_ratios']['roe']}
- 资产负债率: {report['key_ratios']['debt_to_equity']}
"""
    (DATA_DIR / "financial_report.md").write_text(md, encoding="utf-8")


def _make_stock_data():
    """Realistic daily stock price data for 6 months."""
    import random
    random.seed(42)
    dates = []
    prices = [185.0]
    for i in range(120):
        change = random.gauss(0.3, 4.5)
        prices.append(max(prices[-1] + change, 50))
    # Generate dates
    from datetime import datetime, timedelta
    d = datetime(2025, 10, 1)
    rows = [["date", "open", "high", "low", "close", "volume"]]
    for i in range(120):
        d += timedelta(days=1)
        if d.weekday() >= 5:
            continue
        base = prices[i]
        o = round(base + random.uniform(-3, 3), 2)
        h = round(max(o, base) + random.uniform(0, 5), 2)
        l = round(min(o, base) - random.uniform(0, 5), 2)
        c = round(base + random.uniform(-2, 2), 2)
        v = int(random.uniform(1e6, 5e6))
        rows.append([d.strftime("%Y-%m-%d"), str(o), str(h), str(l), str(c), str(v)])

    csv_text = "\n".join(",".join(r) for r in rows)
    (DATA_DIR / "stock_prices.csv").write_text(csv_text, encoding="utf-8")


def _make_sales_data():
    """E-commerce sales dataset for data analysis."""
    import random
    random.seed(123)
    categories = ["电子产品", "服装", "食品", "家居", "运动户外", "图书"]
    regions = ["华北", "华东", "华南", "西南", "西北"]

    rows = [["order_id", "date", "category", "region", "amount", "quantity", "customer_type"]]
    for i in range(500):
        oid = f"ORD{i+1:05d}"
        month = random.randint(1, 12)
        day = random.randint(1, 28)
        cat = random.choice(categories)
        reg = random.choice(regions)
        amount = round(random.uniform(50, 5000), 2)
        qty = random.randint(1, 10)
        ctype = random.choice(["新客户", "老客户", "VIP"])
        rows.append([oid, f"2025-{month:02d}-{day:02d}", cat, reg, str(amount), str(qty), ctype])

    csv_text = "\n".join(",".join(r) for r in rows)
    (DATA_DIR / "sales_data.csv").write_text(csv_text, encoding="utf-8")


def _make_movie_data():
    """Movie script analysis data."""
    scripts = {
        "title": "《流浪地球3》剧本概要",
        "genre": "科幻/灾难",
        "director": "郭帆",
        "estimated_budget": "8亿人民币",
        "target_release": "2027年春节档",
        "script_summary": (
            "地球在宇宙中漂流至半人马座星系后，人类面临新的生存危机。"
            "太阳系边缘发现了外星文明的遗迹，暗示着人类并非宇宙中唯一的智慧生命。"
            "主角团队需要在有限时间内解读外星信号，同时应对地球资源枯竭的挑战。"
            "故事分为三条线索：科学团队破解外星密码、政府应对社会动荡、普通家庭的生存挣扎。"
            "高潮是地球引擎意外停转，全人类必须在72小时内完成不可能的任务。"
        ),
        "characters": [
            {"name": "刘启", "role": "主角/工程师", "arc": "从逃避责任到挺身而出"},
            {"name": "韩朵朵", "role": "科学家", "arc": "在绝望中坚持寻找答案"},
            {"name": "李队", "role": "救援队长", "arc": "牺牲小我完成大我"},
            {"name": "MOSS", "role": "AI系统", "arc": "在逻辑与人性之间徘徊"},
        ],
        "market_context": {
            "china_box_office_2025": "523亿人民币",
            "sci_fi_share": "18.5%",
            "春节档竞争": ["《封神2》", "《哪吒3》", "《刺杀小说家2》"],
        },
    }
    (DATA_DIR / "movie_script.json").write_text(
        json.dumps(scripts, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _make_config_data():
    """Agent configuration template."""
    config = {
        "models": {
            "pro": "deepseek-v4-pro",
            "flash": "deepseek-v4-flash",
        },
        "thinking": {"type": "enabled"},
        "max_steps": 10,
        "timeout": 120,
    }
    (DATA_DIR / "agent_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    download_all()
