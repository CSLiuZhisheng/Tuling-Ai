"""
简化的手动测试脚本

不依赖复杂的导入，直接测试核心功能
"""

import sys
import io

# 设置 UTF-8 输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

print("="*60)
print("  Memory Service 集成测试（简化版）")
print("="*60)
print()

# 测试 1：检查文件是否存在
print("1. 检查文件结构...")

import os
from pathlib import Path

files_to_check = [
    "memory_service/core/manager.py",
    "memory_service/client.py",
    "memory_service/main.py",
    "langgraph_service/app/services/graph_runtime.py",
    "langgraph_service/requirements.txt",
    "main_service/app/routers/memory.py",
    "main_service/requirements.txt",
]

for file in files_to_check:
    if Path(file).exists():
        print(f"  ✅ {file}")
    else:
        print(f"  ❌ {file} - 不存在")

print()

# 测试 2：检查代码集成
print("2. 检查代码集成...")

# 检查 langgraph_service 集成
runtime_file = Path("langgraph_service/app/services/graph_runtime.py")
if runtime_file.exists():
    content = runtime_file.read_text(encoding='utf-8')
    if "from memory_service.client import MemoryClient" in content:
        print("  ✅ langgraph_service 已集成 MemoryClient")
    else:
        print("  ⚠️  langgraph_service 可能未完全集成")

# 检查 main_service 集成
memory_router = Path("main_service/app/routers/memory.py")
if memory_router.exists():
    content = memory_router.read_text(encoding='utf-8')
    if "MemoryClient" in content:
        print("  ✅ main_service 已创建记忆路由")
    else:
        print("  ⚠️  main_service 路由可能不完整")

print()

# 测试 3：检查依赖配置
print("3. 检查依赖配置...")

req_files = [
    "langgraph_service/requirements.txt",
    "main_service/requirements.txt",
]

for req_file in req_files:
    if Path(req_file).exists():
        content = Path(req_file).read_text(encoding='utf-8')
        if "memory_service" in content:
            print(f"  ✅ {req_file} 已添加 memory_service")
        else:
            print(f"  ⚠️  {req_file} 未添加 memory_service")

print()

# 测试 4：文档检查
print("4. 检查文档...")

docs = [
    "memory_service/README.md",
    "memory_service/docs/INTEGRATION_GUIDE.md",
    "langgraph_service/docs/MEMORY_INTEGRATION_DONE.md",
    "main_service/docs/MEMORY_INTEGRATION_DONE.md",
    "MEMORY_SERVICE_FINAL_SUMMARY.md",
]

for doc in docs:
    if Path(doc).exists():
        print(f"  ✅ {doc}")
    else:
        print(f"  ⚠️  {doc} - 缺失")

print()
print("="*60)
print("  基础检查完成")
print("="*60)
print()
print("下一步：")
print("  1. 安装依赖：cd langgraph_service && pip install -r requirements.txt")
print("  2. 启动服务：python app/main.py")
print("  3. 测试对话功能")
print()
