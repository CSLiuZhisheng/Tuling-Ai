from __future__ import annotations

import uvicorn


if __name__ == "__main__":
    # 开发启动入口。reload=True 适合本地调试，生产环境应由进程管理器或
    # 单独的 Uvicorn 命令控制 worker 数量和重启策略。
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8001,
        reload=True,
        log_level="info",
    )
