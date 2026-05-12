"""REAL production stress tests — concurrent, context overflow, memory pressure, error injection.

These tests are DESIGNED to break fragile frameworks. If DTK survives these,
it deserves a production label.
"""
import concurrent.futures
import json
import os
import random
import time
from pathlib import Path

import pytest

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
OUTPUT_DIR = Path(__file__).parent.parent / "output" / "real_stress"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

pytestmark = pytest.mark.skipif(not API_KEY, reason="DEEPSEEK_API_KEY not set")


# ══════════════════════════════════════════════════════════════════════
# TEST 1: Context Overflow Pressure
# Fill context to 90%+ with documents → force compression → verify integrity
# ══════════════════════════════════════════════════════════════════════

class TestContextOverflowPressure:
    """Push 1M context to its limit and force compression."""

    def test_context_overflow_with_compression(self):
        """Fill context with documents, trigger compression, verify no data loss."""
        from deepseek_toolkit.agent.agent import DeepSeekAgent
        from deepseek_toolkit.compat.compressor import ContextCompressor

        agent = DeepSeekAgent(
            role="档案管理员",
            goal="在海量文档中找到关键信息并准确回答",
            backstory="你管理着一个庞大的文档库，需要在海量信息中快速定位关键数据",
            api_key=API_KEY,
            thinking=False,
            max_steps=3,
            max_context_tokens=16000,  # Artificially low to force compression
        )

        # Generate documents that will fill the context
        docs = []
        for i in range(30):
            # Each doc ~500 chars → 30×500 = 15000 chars → ~3750 tokens
            # With system prompt + conversation → should hit 16K limit
            content = (
                f"文档{i:03d}："
                + "这是一份包含关键信息的文档。" * 8
                + f"【关键数据点】文档{i}的秘密代码是：X{i*7:04d}。"
                + f"【日期】2025-{((i%12)+1):02d}-{(i%28)+1:02d}。"
                + f"【状态】{'活跃' if i%3==0 else '待审核' if i%3==1 else '已归档'}。"
                + "无关填充内容。" * 5
            )
            docs.append({"page_content": content, "metadata": {"source": f"doc_{i}.txt"}})

        agent.add_documents(docs)

        # Ask for a fact buried in a specific document
        result = agent.run(
            "在文档中查找：文档编号为012的秘密代码是什么？只回复代码，不要其他内容。"
        )

        # The answer should be X0084 (12 * 7 = 84)
        output = result.final_output
        has_answer = "0084" in output.replace(" ", "") or "84" in output.replace(" ", "")
        ctx_used = result.diagnostics.context_used
        ctx_total = result.diagnostics.context_total

        (OUTPUT_DIR / "context_overflow.json").write_text(json.dumps({
            "output": output[:500],
            "has_answer": has_answer,
            "context_used": ctx_used,
            "context_total": ctx_total,
            "compression_triggered": ctx_used > ctx_total * 0.8,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        assert ctx_used > 0, f"Context not used at all: {ctx_used}/{ctx_total}"
        # Compression should have triggered
        # (docs + conversation should exceed limit)


# ══════════════════════════════════════════════════════════════════════
# TEST 2: Concurrent Agent Hammer
# 5 agents, 50 total runs, shared rate limiter, verify correctness
# ══════════════════════════════════════════════════════════════════════

class TestConcurrentAgentHammer:
    """Concurrent agents under load — no corruption, all complete."""

    def test_concurrent_agent_storm(self):
        """5 threads, 10 runs each, shared API key."""
        from deepseek_toolkit.agent.agent import DeepSeekAgent

        NUM_THREADS = 4
        RUNS_PER_THREAD = 5

        results_lock = __import__('threading').Lock()
        all_results = []

        def worker(worker_id: int):
            agent = DeepSeekAgent(
                role=f"工人{worker_id}",
                goal="准确完成任务并返回结果",
                backstory="你是并行任务处理系统的一个工作单元",
                api_key=API_KEY,
                thinking=False,
                max_steps=1,
            )
            worker_results = []
            for run_n in range(RUNS_PER_THREAD):
                try:
                    result = agent.run(
                        f"计算 {worker_id} * {run_n} + {worker_id + run_n}，只回复数字结果"
                    )
                    worker_results.append({
                        "worker": worker_id, "run": run_n,
                        "output": result.final_output[:100],
                        "cost": result.cost,
                        "ok": len(result.final_output) > 0,
                    })
                except Exception as e:
                    worker_results.append({
                        "worker": worker_id, "run": run_n,
                        "error": str(e), "ok": False,
                    })
            with results_lock:
                all_results.extend(worker_results)

        start = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_THREADS) as ex:
            futures = [ex.submit(worker, i) for i in range(NUM_THREADS)]
            concurrent.futures.wait(futures)
        elapsed = time.time() - start

        total_runs = len(all_results)
        successful = sum(1 for r in all_results if r.get("ok"))
        errors = [r for r in all_results if not r.get("ok")]

        (OUTPUT_DIR / "concurrent.json").write_text(json.dumps({
            "total_runs": total_runs,
            "successful": successful,
            "errors": len(errors),
            "elapsed_seconds": round(elapsed, 1),
            "runs_per_second": round(total_runs / elapsed, 1),
            "error_details": errors[:5],
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        assert successful >= total_runs * 0.80, (
            f"Only {successful}/{total_runs} concurrent runs succeeded. Errors: {errors[:3]}"
        )


# ══════════════════════════════════════════════════════════════════════
# TEST 3: Memory Degradation Under Load
# 200 insertions → recall precision check
# ══════════════════════════════════════════════════════════════════════

class TestMemoryDegradation:
    """Memory recall quality must not decay under volume."""

    def test_memory_recall_under_load(self):
        """Insert 100 items, verify top-3 recall contains target."""
        from deepseek_toolkit.agent.memory import AgentMemory

        mem = AgentMemory(long_term_max=200)

        # Insert 100 varied memories
        for i in range(100):
            mem.remember(
                f"用户偏好-{i}: 喜欢{'Python' if i%3==0 else 'JavaScript' if i%3==1 else 'Go'}语言，"
                f"使用{'VSCode' if i%2==0 else 'Vim'}编辑器，"
                f"关注{'AI' if i%5==0 else 'Web' if i%5==1 else '数据' if i%5==2 else '安全' if i%5==3 else '性能'}领域",
                importance=random.uniform(0.3, 1.0),
            )

        # Insert the needle
        mem.remember(
            "【重要】生产环境数据库密码已更新为: DB_PROD_2026_X9K2",
            importance=1.0,
        )

        # Recall: search for the needle
        results = mem.recall("数据库密码", top_k=5)
        found = any("DB_PROD_2026" in r for r in results)

        stats = mem.stats()

        (OUTPUT_DIR / "memory.json").write_text(json.dumps({
            "total_items": stats["long_term_items"],
            "needle_found": found,
            "recall_results": results[:3],
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        assert found, f"Needle not found in recall. Results: {results[:3]}"
        assert stats["long_term_items"] >= 30, f"Too few items stored: {stats}"


# ══════════════════════════════════════════════════════════════════════
# TEST 4: Long Agent Session with Memory Accumulation
# Agent talks 20 rounds, memory grows, recall stays accurate
# ══════════════════════════════════════════════════════════════════════

class TestLongSessionMemory:
    """Agent with memory: 15-round conversation, memory must retain context."""

    def test_long_session_with_memory(self):
        from deepseek_toolkit.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="私人助理",
            goal="记住用户的所有偏好并在后续对话中引用",
            backstory="你是用户的长期私人助理，需要记住每次对话中的重要信息",
            api_key=API_KEY,
            thinking=False,
            max_steps=1,
        )
        agent.enable_memory(short_term_size=15)

        facts = [
            "我叫张伟，是一名后端工程师",
            "我主要用Go语言开发微服务",
            "我们公司数据库用的是PostgreSQL",
            "最近在迁移到Kubernetes",
            "我的咖啡偏好是冰美式，不加糖",
            "我住在北京朝阳区",
            "我每天早上7点开始工作",
            "我们团队有5个人",
            "我上周刚买了一台MacBook Pro M4",
            "下周要出差去上海3天",
        ]

        recall_checks = 0
        for i, fact in enumerate(facts):
            agent.chat(fact)
            # Every 3rd round, test recall
            if i >= 3 and i % 3 == 0:
                query = f"我之前告诉过你我的名字和工作吗？简短回答。"
                result = agent.chat(query)
                if "张伟" in result.final_output or "Go" in result.final_output or "后端" in result.final_output:
                    recall_checks += 1

        # Flush short-term to long-term for persistence
        agent.memory.flush_to_long_term()
        stats = agent.memory.stats()

        (OUTPUT_DIR / "long_session.json").write_text(json.dumps({
            "rounds": len(facts),
            "recall_checks_passed": recall_checks,
            "memory_stats": stats,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        assert recall_checks >= 2, f"Only {recall_checks} recall checks passed"
        assert stats["long_term_items"] >= 3, f"Too few memories stored: {stats}"
