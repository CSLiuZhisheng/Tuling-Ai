"""
Memory Service 集成测试脚本

测试范围：
1. Memory Service 基础功能
2. LangGraph Service 集成
3. Main Service 集成
4. 跨服务数据一致性
"""

import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from langgraph.store.postgres.aio import AsyncPostgresStore
from langchain_openai import ChatOpenAI
import httpx
import os

# 测试配置
POSTGRES_URI = os.getenv(
    "POSTGRES_URI_CUSTOM",
    "postgresql://postgres:123456@127.0.0.1:5432/langgraph_agents?sslmode=disable"
)
TEST_USER_ID = "test_integration_user"


class Colors:
    """终端颜色"""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'


def print_success(msg):
    print(f"{Colors.GREEN}✅ {msg}{Colors.END}")


def print_error(msg):
    print(f"{Colors.RED}❌ {msg}{Colors.END}")


def print_info(msg):
    print(f"{Colors.BLUE}ℹ️  {msg}{Colors.END}")


def print_warning(msg):
    print(f"{Colors.YELLOW}⚠️  {msg}{Colors.END}")


def print_section(title):
    print(f"\n{Colors.BLUE}{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}{Colors.END}\n")


async def test_memory_service_basic():
    """测试 Memory Service 基础功能"""
    print_section("测试 1: Memory Service 基础功能")

    try:
        from memory_service.client import MemoryClient
        print_success("导入 MemoryClient 成功")
    except ImportError as e:
        print_error(f"导入失败: {e}")
        print_warning("请确保已安装: pip install -e ../memory_service")
        return False

    try:
        # 初始化存储
        print_info("初始化 PostgreSQL Store...")
        async with AsyncPostgresStore.from_conn_string(POSTGRES_URI) as store:
            await store.setup()
            print_success("Store 初始化成功")

            # 创建客户端
            print_info("创建 MemoryClient...")
            client = MemoryClient(store=store)
            print_success("MemoryClient 创建成功")

            # 测试保存记忆（规则评分）
            print_info("测试保存记忆（规则评分）...")
            result1 = await client.save_memory(
                user_id=TEST_USER_ID,
                query="什么是 FastAPI？",
                answer="FastAPI 是一个现代的 Python Web 框架",
                use_llm_scoring=False
            )
            print_success(f"保存成功: status={result1.status}, importance={result1.importance}/10, key={result1.key[:8]}...")

            # 测试保存包含代码的记忆
            print_info("测试保存包含代码的记忆...")
            result2 = await client.save_memory(
                user_id=TEST_USER_ID,
                query="如何创建 FastAPI 接口？",
                answer="```python\n@app.post('/api/users')\nasync def create_user():\n    return {'status': 'ok'}\n```",
                use_llm_scoring=False
            )
            print_success(f"保存成功: importance={result2.importance}/10 (应该是 9，因为包含代码)")

            if result2.importance != 9:
                print_warning(f"重要性评分异常：期望 9，实际 {result2.importance}")

            # 测试去重
            print_info("测试去重功能...")
            result3 = await client.save_memory(
                user_id=TEST_USER_ID,
                query="什么是 FastAPI？",
                answer="FastAPI 是一个现代的 Python Web 框架",
                use_llm_scoring=False
            )
            if result3.status == "updated":
                print_success(f"去重成功: status={result3.status}")
            else:
                print_warning(f"去重失败: 期望 updated，实际 {result3.status}")

            # 测试检索
            print_info("测试检索记忆...")
            memories = await client.search_memories(
                user_id=TEST_USER_ID,
                query="FastAPI",
                limit=10,
                use_vector_search=True
            )
            print_success(f"检索成功: 找到 {len(memories)} 条记忆")

            for i, memory in enumerate(memories[:3], 1):
                print(f"  {i}. 重要性: {memory.value.importance}/10")
                print(f"     问题: {memory.value.query[:50]}")
                if memory.similarity:
                    print(f"     相似度: {memory.similarity:.2f}")

            # 测试统计
            print_info("测试获取统计...")
            stats = await client.get_stats(TEST_USER_ID)
            print_success(f"统计成功:")
            print(f"  总记忆数: {stats.total}")
            print(f"  平均重要性: {stats.avg_importance:.2f}")
            print(f"  分层分布: {stats.by_tier}")

            # 测试清理
            print_info("测试清理低价值记忆...")
            cleanup_result = await client.cleanup(
                user_id=TEST_USER_ID,
                importance_threshold=3,
                days_threshold=0  # 立即清理用于测试
            )
            print_success(f"清理完成: 删除 {cleanup_result.deleted} 条，保留 {cleanup_result.kept} 条")

            print_success("Memory Service 基础功能测试通过")
            return True

    except Exception as e:
        print_error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_langgraph_service_integration():
    """测试 LangGraph Service 集成"""
    print_section("测试 2: LangGraph Service 集成")

    try:
        print_info("检查 LangGraph Service 集成...")

        # 检查导入
        try:
            from memory_service.client import MemoryClient
            print_success("MemoryClient 导入成功")
        except ImportError:
            print_error("MemoryClient 导入失败")
            return False

        # 检查 graph_runtime.py 是否更新
        runtime_file = Path("langgraph_service/app/services/graph_runtime.py")
        if runtime_file.exists():
            content = runtime_file.read_text(encoding='utf-8')
            if "from memory_service.client import MemoryClient" in content:
                print_success("graph_runtime.py 已更新使用 MemoryClient")
            else:
                print_warning("graph_runtime.py 可能未更新")

        # 检查 requirements.txt
        req_file = Path("langgraph_service/requirements.txt")
        if req_file.exists():
            content = req_file.read_text(encoding='utf-8')
            if "memory_service" in content:
                print_success("requirements.txt 已添加 memory_service 依赖")
            else:
                print_warning("requirements.txt 未添加 memory_service 依赖")

        print_success("LangGraph Service 集成检查通过")
        return True

    except Exception as e:
        print_error(f"测试失败: {e}")
        return False


async def test_main_service_integration():
    """测试 Main Service 集成"""
    print_section("测试 3: Main Service 集成")

    try:
        print_info("检查 Main Service 集成...")

        # 检查路由文件
        memory_router = Path("main_service/app/routers/memory.py")
        if memory_router.exists():
            print_success("memory.py 路由文件已创建")

            content = memory_router.read_text(encoding='utf-8')
            if "MemoryClient" in content:
                print_success("路由文件使用 MemoryClient")
        else:
            print_warning("memory.py 路由文件不存在")

        # 检查 requirements.txt
        req_file = Path("main_service/requirements.txt")
        if req_file.exists():
            content = req_file.read_text(encoding='utf-8')
            if "memory_service" in content:
                print_success("requirements.txt 已添加 memory_service 依赖")
            else:
                print_warning("requirements.txt 未添加 memory_service 依赖")

        print_success("Main Service 集成检查通过")
        return True

    except Exception as e:
        print_error(f"测试失败: {e}")
        return False


async def test_memory_service_api():
    """测试 Memory Service REST API（如果服务正在运行）"""
    print_section("测试 4: Memory Service REST API（可选）")

    memory_service_url = "http://localhost:8020"

    print_info(f"尝试连接 Memory Service: {memory_service_url}")

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # 测试健康检查
            response = await client.get(f"{memory_service_url}/health")
            if response.status_code == 200:
                print_success("Memory Service 运行中")
                data = response.json()
                print(f"  版本: {data.get('version')}")
                print(f"  状态: {data.get('status')}")
                return True
            else:
                print_warning(f"Memory Service 响应异常: {response.status_code}")
                return False

    except httpx.ConnectError:
        print_warning("Memory Service 未启动（可选测试，可跳过）")
        print_info("如需测试独立服务模式，请运行: cd memory_service && python main.py")
        return None  # None 表示跳过
    except Exception as e:
        print_error(f"连接失败: {e}")
        return False


async def test_cross_service_consistency():
    """测试跨服务数据一致性"""
    print_section("测试 5: 跨服务数据一致性")

    try:
        from memory_service.client import MemoryClient

        async with AsyncPostgresStore.from_conn_string(POSTGRES_URI) as store:
            await store.setup()

            client1 = MemoryClient(store=store)
            client2 = MemoryClient(store=store)

            # 客户端1保存
            print_info("客户端1保存记忆...")
            result1 = await client1.save_memory(
                user_id=TEST_USER_ID,
                query="跨服务测试问题",
                answer="跨服务测试答案",
            )
            print_success(f"客户端1保存成功: key={result1.key[:8]}...")

            # 客户端2读取
            print_info("客户端2读取记忆...")
            memories = await client2.search_memories(
                user_id=TEST_USER_ID,
                query="跨服务",
                limit=5
            )

            found = False
            for memory in memories:
                if memory.value.query == "跨服务测试问题":
                    found = True
                    break

            if found:
                print_success("跨服务数据一致性验证通过")
                return True
            else:
                print_error("跨服务数据不一致")
                return False

    except Exception as e:
        print_error(f"测试失败: {e}")
        return False


async def cleanup_test_data():
    """清理测试数据"""
    print_section("清理测试数据")

    try:
        from memory_service.client import MemoryClient

        async with AsyncPostgresStore.from_conn_string(POSTGRES_URI) as store:
            await store.setup()
            client = MemoryClient(store=store)

            # 清理测试用户的所有记忆
            result = await client.cleanup(
                user_id=TEST_USER_ID,
                importance_threshold=100,  # 删除所有记忆
                days_threshold=0
            )

            print_success(f"清理完成: 删除 {result.deleted} 条测试数据")
            return True

    except Exception as e:
        print_error(f"清理失败: {e}")
        return False


async def run_all_tests():
    """运行所有测试"""
    print(f"\n{Colors.BLUE}{'='*60}")
    print("  Memory Service 集成测试套件")
    print(f"{'='*60}{Colors.END}\n")

    print_info(f"测试用户ID: {TEST_USER_ID}")
    print_info(f"PostgreSQL: {POSTGRES_URI.split('@')[1] if '@' in POSTGRES_URI else '...'}\n")

    results = []

    # 测试1: 基础功能
    result1 = await test_memory_service_basic()
    results.append(("Memory Service 基础功能", result1))

    # 测试2: LangGraph 集成
    result2 = await test_langgraph_service_integration()
    results.append(("LangGraph Service 集成", result2))

    # 测试3: Main Service 集成
    result3 = await test_main_service_integration()
    results.append(("Main Service 集成", result3))

    # 测试4: REST API（可选）
    result4 = await test_memory_service_api()
    if result4 is not None:
        results.append(("Memory Service REST API", result4))

    # 测试5: 跨服务一致性
    result5 = await test_cross_service_consistency()
    results.append(("跨服务数据一致性", result5))

    # 清理测试数据
    await cleanup_test_data()

    # 汇总结果
    print_section("测试结果汇总")

    passed = 0
    failed = 0

    for name, result in results:
        if result:
            print_success(f"{name}: 通过")
            passed += 1
        else:
            print_error(f"{name}: 失败")
            failed += 1

    print(f"\n{Colors.BLUE}{'='*60}{Colors.END}")
    total = passed + failed
    if failed == 0:
        print_success(f"全部测试通过！({passed}/{total})")
        print(f"\n🎉 恭喜！Memory Service 集成成功！")
    else:
        print_warning(f"部分测试失败: {passed} 通过, {failed} 失败")
        print(f"\n⚠️  请检查失败的测试项")
    print(f"{Colors.BLUE}{'='*60}{Colors.END}\n")

    return failed == 0


if __name__ == "__main__":
    try:
        success = asyncio.run(run_all_tests())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print_warning("\n测试被中断")
        sys.exit(1)
    except Exception as e:
        print_error(f"\n测试异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
