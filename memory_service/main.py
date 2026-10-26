"""
Memory Service - 独立服务入口

可作为独立 FastAPI 服务运行，也可被其他服务引用
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from langgraph.store.postgres.aio import AsyncPostgresStore
from langchain_openai import ChatOpenAI

from memory_service.api.routes import router, set_memory_manager
from memory_service.api.schemas import HealthResponse
from memory_service.core.manager import MemoryManager
from memory_service.config.settings import MemoryConfig

# 全局配置和存储
config = MemoryConfig()
_store: AsyncPostgresStore = None
_manager: MemoryManager = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    服务生命周期管理

    启动时：
    - 初始化 PostgreSQL Store
    - 创建 MemoryManager
    - 设置 LLM（如果启用）

    关闭时：
    - 清理资源
    """
    global _store, _manager

    # 启动
    print(f"🚀 Starting Memory Service v{config.VERSION}")
    print(f"📊 PostgreSQL: {config.POSTGRES_URI.split('@')[1] if '@' in config.POSTGRES_URI else 'configured'}")
    print(f"🧠 LLM Scoring: {'enabled' if config.USE_LLM_SCORING else 'disabled'}")
    print(f"🔍 Vector Search: {'enabled' if config.USE_VECTOR_SEARCH else 'disabled'}")

    # 初始化存储
    _store = AsyncPostgresStore.from_conn_string(config.POSTGRES_URI)
    await _store.__aenter__()
    await _store.setup()
    print("✅ PostgreSQL Store initialized")

    # 初始化 LLM（可选）
    llm = None
    if config.USE_LLM_SCORING and config.API_KEY:
        llm = ChatOpenAI(
            model=config.MODEL,
            api_key=config.API_KEY,
            base_url=config.API_BASE_URL,
            temperature=config.TEMPERATURE,
        )
        print(f"✅ LLM initialized: {config.MODEL}")

    # 创建管理器
    _manager = MemoryManager(_store, llm, config)
    set_memory_manager(_manager)
    print("✅ Memory Manager initialized")

    print(f"🎉 Memory Service started on {config.HOST}:{config.PORT}")

    yield

    # 关闭
    print("🛑 Shutting down Memory Service...")
    await _store.__aexit__(None, None, None)
    print("✅ Resources cleaned up")


# 创建 FastAPI 应用
app = FastAPI(
    title="Memory Service",
    version=config.VERSION,
    description="统一的长期记忆管理服务",
    lifespan=lifespan,
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(router)


@app.get("/", response_model=HealthResponse)
async def root():
    """根路径"""
    return HealthResponse(
        status="running",
        service="memory_service",
        version=config.VERSION
    )


@app.get("/health", response_model=HealthResponse)
async def health():
    """健康检查"""
    return HealthResponse(
        status="healthy" if _manager is not None else "initializing",
        service="memory_service",
        version=config.VERSION
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=True,
        log_level=config.LOG_LEVEL.lower()
    )
