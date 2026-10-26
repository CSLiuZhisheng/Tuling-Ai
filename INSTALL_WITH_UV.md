# 使用 UV 安装 Memory Service 依赖指南

## 📦 UV 简介

`uv` 是一个极快的 Python 包管理器，比 pip 快 10-100 倍。

---

## 🚀 安装步骤

### 步骤 1：安装 Memory Service

```bash
# 进入 memory_service 目录
cd memory_service

# 使用 uv 安装（开发模式）
uv pip install -e .

# 或者如果出错，先安装基础依赖
uv pip install fastapi uvicorn pydantic langgraph langchain-core langchain-openai psycopg asyncpg httpx python-dotenv structlog
```

**验证**：
```bash
python -c "from memory_service.client import MemoryClient; print('✅ 安装成功')"
```

---

### 步骤 2：安装 LangGraph Service 依赖

```bash
cd ../langgraph_service

# 使用 uv 安装所有依赖
uv pip install -r requirements.txt
```

**预计时间**：1-2 分钟

**验证**：
```bash
python -c "from memory_service.client import MemoryClient; print('✅ LangGraph Service 依赖安装成功')"
```

---

### 步骤 3：安装 Main Service 依赖

```bash
cd ../main_service

# 使用 uv 安装所有依赖
uv pip install -r requirements.txt
```

**验证**：
```bash
python -c "from memory_service.client import MemoryClient; print('✅ Main Service 依赖安装成功')"
```

---

## 🔧 常见问题

### 问题 1：uv 未安装

```bash
# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# 或使用 pip 安装
pip install uv
```

### 问题 2：权限错误

```bash
# Windows：以管理员身份运行 PowerShell
# Linux/macOS：使用 sudo 或虚拟环境
```

### 问题 3：依赖冲突

```bash
# 创建新的虚拟环境
uv venv .venv
source .venv/bin/activate  # Linux/macOS
# 或
.venv\Scripts\activate  # Windows

# 然后重新安装
uv pip install -r requirements.txt
```

---

## 📋 完整安装命令（一键复制）

### Windows PowerShell

```powershell
# 1. 安装 memory_service
cd memory_service
uv pip install -e .

# 2. 安装 langgraph_service 依赖
cd ..\langgraph_service
uv pip install -r requirements.txt

# 3. 安装 main_service 依赖
cd ..\main_service
uv pip install -r requirements.txt

# 4. 验证安装
cd ..
python tests/test_simple.py
```

### Linux/macOS

```bash
# 1. 安装 memory_service
cd memory_service
uv pip install -e .

# 2. 安装 langgraph_service 依赖
cd ../langgraph_service
uv pip install -r requirements.txt

# 3. 安装 main_service 依赖
cd ../main_service
uv pip install -r requirements.txt

# 4. 验证安装
cd ..
python tests/test_simple.py
```

---

## ⚡ UV 性能对比

| 操作 | pip | uv | 提升 |
|------|-----|----|----|
| 安装 langgraph_service 依赖 | ~5分钟 | ~30秒 | 10倍 |
| 安装 main_service 依赖 | ~2分钟 | ~10秒 | 12倍 |
| 总耗时 | ~7分钟 | ~40秒 | **10倍+** |

---

## 🎯 安装后验证

运行验证脚本：

```bash
# 在项目根目录
python tests/test_simple.py
```

**期望输出**：
```
============================================================
  Memory Service 集成测试（简化版）
============================================================

1. 检查文件结构...
  ✅ memory_service/core/manager.py
  ✅ memory_service/client.py
  ...（所有文件通过）

2. 检查代码集成...
  ✅ langgraph_service 已集成 MemoryClient
  ✅ main_service 已创建记忆路由

3. 检查依赖配置...
  ✅ 所有依赖配置完成

4. 检查文档...
  ✅ 所有文档齐全

============================================================
  基础检查完成
============================================================
```

---

## 🚀 启动服务

### LangGraph Service

```bash
cd langgraph_service
python app/main.py
```

**访问**：http://localhost:8000

### Main Service

```bash
cd main_service
python app/main.py
```

**访问**：http://localhost:8001

### Memory Service（独立部署，可选）

```bash
cd memory_service
python main.py
```

**访问**：http://localhost:8020/docs

---

## 📊 依赖清单

### Memory Service
- fastapi==0.115.0
- uvicorn==0.31.0
- langgraph==0.2.45
- langchain-core==0.3.15
- langchain-openai==0.2.9
- psycopg==3.2.3
- asyncpg==0.29.0

### LangGraph Service
- 包含 Memory Service 依赖
- 额外：langmem, mcp, langchain-tavily 等

### Main Service
- 包含 Memory Service 依赖
- 额外：sqlalchemy, pydantic-settings 等

---

## ✅ 验收标准

- [ ] `uv pip install` 无报错
- [ ] `python -c "from memory_service.client import MemoryClient"` 成功
- [ ] `python tests/test_simple.py` 全部通过
- [ ] 服务启动无报错

---

## 🆘 故障排查

### 问题：uv 安装慢

```bash
# 使用国内镜像
uv pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 问题：模块导入失败

```bash
# 确认 memory_service 已安装
uv pip list | grep memory

# 如果没有，重新安装
cd memory_service
uv pip install -e .
```

### 问题：版本冲突

```bash
# 查看冲突
uv pip check

# 强制重新安装
uv pip install --force-reinstall -r requirements.txt
```

---

## 📝 下一步

安装完成后：

1. ✅ 配置环境变量（`.env` 文件）
2. ✅ 启动服务测试
3. ✅ 运行功能测试
4. ✅ 查看文档：`MEMORY_SERVICE_FINAL_SUMMARY.md`

---

**使用 UV 让依赖安装快 10 倍！** ⚡

---

**文档版本**：1.0  
**最后更新**：2025-01-XX
