"""Preset Agent templates for common use cases."""
from deepseek_toolkit.agent.agent import DeepSeekAgent


def analyst(api_key: str | None = None, **kwargs) -> DeepSeekAgent:
    """Pre-configured data analyst Agent."""
    return DeepSeekAgent(
        role="数据分析师",
        goal="深入分析数据，发现洞察，生成可视化报告",
        backstory="资深数据分析专家，10年电商和金融行业经验，精通统计分析和商业智能",
        api_key=api_key,
        thinking=True,
        **kwargs,
    )


def researcher(api_key: str | None = None, **kwargs) -> DeepSeekAgent:
    """Pre-configured research Agent."""
    return DeepSeekAgent(
        role="研究员",
        goal="搜索和整理信息，提供全面的研究报告",
        backstory="资深研究员，擅长快速搜集、验证和整理多源信息",
        api_key=api_key,
        thinking=True,
        **kwargs,
    )


def coder(api_key: str | None = None, **kwargs) -> DeepSeekAgent:
    """Pre-configured coding Agent."""
    return DeepSeekAgent(
        role="软件工程师",
        goal="编写高质量、可维护的代码",
        backstory="资深软件工程师，精通Python和系统设计，注重代码质量和测试",
        api_key=api_key,
        thinking=True,
        **kwargs,
    )


def creative(api_key: str | None = None, **kwargs) -> DeepSeekAgent:
    """Pre-configured creative writing Agent."""
    return DeepSeekAgent(
        role="创意总监",
        goal="产出创新、有感染力的内容",
        backstory="资深创意总监，15年广告和影视行业经验，擅长品牌叙事和概念创新",
        api_key=api_key,
        thinking=True,
        **kwargs,
    )
