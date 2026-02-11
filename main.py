"""
Telegram 定时消息推送管理系统 - 主入口
"""
import uvicorn
from loguru import logger

from backend.h5_backend.api import app


def setup_logger():
    """配置日志"""
    logger.remove()  # 移除默认处理器

    # 添加文件输出
    logger.add(
        "logs/app_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="30 days",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
    )

    # 添加控制台输出
    logger.add(
        sink=lambda msg: print(msg, end=""),
        level="INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}:{function}:{line}</cyan> - <level>{message}</level>"
    )


if __name__ == "__main__":
    # 配置日志
    setup_logger()

    # 运行 uvicorn 服务器
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
