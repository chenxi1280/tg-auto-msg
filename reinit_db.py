import asyncio
import sys

from backend.database.runtime.session import drop_database, init_database

async def main():
    print("⚠️  警告: 即将删除所有数据表并重新初始化...")
    try:
        # 删除所有表
        print("1. 正在删除旧表...")
        await drop_database()
        print("✅ 旧表已删除")

        # 创建新表
        print("2. 正在创建新表...")
        await init_database()
        print("✅ 数据库已成功重置！所有表结构已更新。")

    except Exception as e:
        print(f"❌ 重置失败: {e}")
        raise

if __name__ == "__main__":
    # 兼容 Windows 平台的事件循环策略（如果在 Windows 上运行）
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main())
