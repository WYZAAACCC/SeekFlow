"""Brainstorming tool — generates creative ideas via structured prompt."""

import random


def brainstorm_ideas(topic: str, count: int = 5) -> str:
    """Generate creative ideas on a given topic using structured brainstorming techniques.

    Uses multiple creativity frameworks:
    - SCAMPER (Substitute, Combine, Adapt, Modify, Put to another use, Eliminate, Reverse)
    - TRIZ contradiction resolution
    - Lateral thinking prompts

    Args:
        topic: The topic or problem to brainstorm about (e.g., 'sci-fi film about AI consciousness')
        count: Number of ideas to generate (1-10, default 5)

    Returns:
        Formatted list of creative ideas with rationale
    """
    count = max(1, min(count, 10))

    frameworks = [
        "SCAMPER-Combine: 将两个看似无关的概念融合",
        "SCAMPER-Adapt: 从自然界或历史事件中借鉴模式",
        "SCAMPER-Modify: 改变尺度、时间线或视角",
        "SCAMPER-Reverse: 颠覆传统叙事结构或因果关系",
        "TRIZ-矛盾: 识别核心矛盾并寻找突破性解决方案",
        "横向思维: 从完全不同领域的成功模式中获取灵感",
        "What-If: 假设一个关键前提条件发生改变",
        "跨界融合: 将科技、艺术、哲学交叉碰撞",
        "极简主义: 去掉所有非必要元素后的核心是什么",
        "极端场景: 放大到极致或缩小到极致会发生什么",
    ]

    ideas = []
    for i in range(count):
        framework = frameworks[i % len(frameworks)]
        seed = random.randint(1, 9999)

        ideas.append({
            "id": i + 1,
            "framework": framework.split(":")[0],
            "method": framework.split(":", 1)[1].strip() if ":" in framework else framework,
            "prompt": f"[{framework}] 针对「{topic}」，请思考一个创新方案。种子: {seed}",
        })

    # Format output
    lines = [f"创造性头脑风暴: {topic}", "=" * 50]
    for idea in ideas:
        lines.append(f"\n## 想法 #{idea['id']} [{idea['framework']}]")
        lines.append(f"   方法: {idea['method']}")
        lines.append(f"   提示: {idea['prompt']}")
        lines.append(f"   (此提示供LLM进一步展开，请基于此框架生成具体创意内容)")

    return "\n".join(lines)
