"""
数据库初始化脚本
"""
import asyncio

from backend.database.session import init_database


async def main():
    """主函数"""
    print("正在初始化数据库...")
    await init_database()
    print("✅ 数据库初始化完成！")


if __name__ == "__main__":
    asyncio.run(main())
