"""
记忆管理 V2 测试脚本

测试功能：
1. LLM 评分准确性
2. 向量检索效果
3. 记忆去重
4. 分层归档
5. 自动清理
"""

import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from langgraph.store.postgres.aio import AsyncPostgresStore
from langchain_openai import ChatOpenAI
from config.settings import Settings
from app.services.memory_manager_v2 import MemoryManagerV2


async def test_llm_scoring():
    """测试 LLM 评分功能"""
    print("\n" + "="*60)
    print("测试 1: LLM 评分准确性")
    print("="*60)

    # 初始化
    conn_string = Settings.LANGGRAPH_POSTGRES_DSN
    async with AsyncPostgresStore.from_conn_string(conn_string) as store:
        llm = ChatOpenAI(
            model=Settings.MODEL,
            api_key=Settings.API_KEY,
            base_url=Settings.API_BASE_URL,
            temperature=0.1,
        )

        manager = MemoryManagerV2(store, llm=llm)

        # 测试用例
        test_cases = [
            {
                "query": "你好",
                "answer": "你好！有什么可以帮你的吗？",
                "expected": 1,  # 应该是 TRIVIAL
                "desc": "简单寒暄"
            },
            {
                "query": "如何使用 FastAPI 创建 POST 接口？",
                "answer": "```python\n@app.post('/api/users')\nasync def create_user(user: User):\n    return {'status': 'success'}\n```",
                "expected": 9,  # 应该是 CRITICAL（包含代码）
                "desc": "包含代码的技术问答"
            },
            {
                "query": "项目的数据库架构如何设计？",
                "answer": "我们采用微服务架构，每个服务独立数据库...",
                "expected": 7,  # 应该是 IMPORTANT
                "desc": "架构设计讨论"
            },
        ]

        print("\n使用 LLM 评分：")
        for case in test_cases:
            score = await manager._evaluate_importance_with_llm(
                case["query"],
                case["answer"]
            )
            status = "✅" if abs(score - case["expected"]) <= 2 else "❌"
            print(f"{status} {case['desc']}: 期望 {case['expected']}, 实际 {score}")

        print("\n使用规则评分（对比）：")
        for case in test_cases:
            score = manager._evaluate_importance_rule_based(
                case["query"],
                case["answer"]
            )
            status = "✅" if abs(score - case["expected"]) <= 2 else "❌"
            print(f"{status} {case['desc']}: 期望 {case['expected']}, 实际 {score}")


async def test_vector_search():
    """测试向量检索功能"""
    print("\n" + "="*60)
    print("测试 2: 向量检索效果")
    print("="*60)

    conn_string = Settings.LANGGRAPH_POSTGRES_DSN
    async with AsyncPostgresStore.from_conn_string(conn_string) as store:
        manager = MemoryManagerV2(store)

        # 先保存一些测试记忆
        test_memories = [
            ("如何使用 FastAPI？", "FastAPI 是一个现代的 Python Web 框架..."),
            ("FastAPI 如何处理异步？", "FastAPI 原生支持 async/await..."),
            ("什么是 LangGraph？", "LangGraph 是一个用于构建 AI 代理的框架..."),
            ("今天天气怎么样？", "抱歉，我无法查询实时天气..."),
        ]

        print("\n保存测试记忆...")
        for query, answer in test_memories:
            await manager.save_memory(
                user_id="test_user",
                query=query,
                answer=answer
            )

        # 测试向量检索
        print("\n测试检索: 'FastAPI 异步编程'")
        results = await manager.search_memories(
            user_id="test_user",
            query="FastAPI 异步编程",
            limit=3,
            use_vector_search=True
        )

        print(f"找到 {len(results)} 条相关记忆：")
        for i, result in enumerate(results, 1):
            query = result["value"].get("query", "")
            score = result.get("score", 0)
            similarity = result.get("similarity", 0)
            print(f"{i}. 【相似度: {similarity:.2f}, 得分: {score:.2f}】 {query}")


async def test_deduplication():
    """测试去重功能"""
    print("\n" + "="*60)
    print("测试 3: 记忆去重")
    print("="*60)

    conn_string = Settings.LANGGRAPH_POSTGRES_DSN
    async with AsyncPostgresStore.from_conn_string(conn_string) as store:
        manager = MemoryManagerV2(store)

        query = "Python 如何安装依赖？"
        answer = "使用 pip install package_name 命令"

        # 第一次保存
        result1 = await manager.save_memory(
            user_id="test_dedup",
            query=query,
            answer=answer
        )
        print(f"第1次保存: {result1['status']}, key={result1['key']}")

        # 第二次保存相同内容
        result2 = await manager.save_memory(
            user_id="test_dedup",
            query=query,
            answer=answer
        )
        print(f"第2次保存: {result2['status']}, key={result2['key']}")

        if result1['key'] == result2['key']:
            print("✅ 去重成功：相同内容未重复保存")
        else:
            print("❌ 去重失败：生成了不同的 key")


async def test_tiered_storage():
    """测试分层存储"""
    print("\n" + "="*60)
    print("测试 4: 分层存储与归档")
    print("="*60)

    conn_string = Settings.LANGGRAPH_POSTGRES_DSN
    async with AsyncPostgresStore.from_conn_string(conn_string) as store:
        manager = MemoryManagerV2(store)

        # 保存记忆
        await manager.save_memory(
            user_id="test_tier",
            query="测试分层存储",
            answer="这是一条测试记忆"
        )

        # 获取统计
        stats = await manager.get_memory_stats("test_tier")
        print(f"\n记忆统计：")
        print(f"  总数: {stats['total']}")
        print(f"  分层: {stats['by_tier']}")
        print(f"  按重要性: {stats['by_importance']}")

        # 测试归档（注意：需要修改时间才能测试归档功能）
        print("\n尝试归档旧记忆...")
        archive_result = await manager.archive_old_memories(
            user_id="test_tier",
            days_threshold=0  # 立即归档所有记忆（仅用于测试）
        )
        print(f"  归档数量: {archive_result['archived']}")


async def test_cleanup():
    """测试清理功能"""
    print("\n" + "="*60)
    print("测试 5: 自动清理低价值记忆")
    print("="*60)

    conn_string = Settings.LANGGRAPH_POSTGRES_DSN
    async with AsyncPostgresStore.from_conn_string(conn_string) as store:
        manager = MemoryManagerV2(store)

        # 保存一些低价值记忆
        low_value = [
            ("你好", "你好！"),
            ("谢谢", "不客气！"),
            ("嗯", "好的"),
        ]

        print("\n保存低价值记忆...")
        for query, answer in low_value:
            result = await manager.save_memory(
                user_id="test_cleanup",
                query=query,
                answer=answer
            )
            print(f"  重要性: {result['importance']}")

        # 执行清理
        print("\n执行清理（重要性 < 3，0天未访问）...")
        cleanup_result = await manager.cleanup_low_value_memories(
            user_id="test_cleanup",
            importance_threshold=3,
            days_threshold=0  # 立即清理（仅用于测试）
        )

        print(f"  删除: {cleanup_result['deleted']} 条")
        print(f"  保留: {cleanup_result['kept']} 条")


async def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*60)
    print("记忆管理 V2 功能测试")
    print("="*60)

    try:
        await test_llm_scoring()
        await test_vector_search()
        await test_deduplication()
        await test_tiered_storage()
        await test_cleanup()

        print("\n" + "="*60)
        print("✅ 所有测试完成")
        print("="*60)

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(run_all_tests())
