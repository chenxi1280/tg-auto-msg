#!/bin/bash

echo "========================================"
echo "  Telegram 定时消息推送管理系统"
echo "  快速启动脚本"
echo "========================================"
echo ""

# 检查 Python 版本
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "✓ Python 版本: $PYTHON_VERSION"

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo ""
    echo "📦 创建虚拟环境..."
    python3 -m venv venv
fi

echo "✓ 激活虚拟环境"
source venv/bin/activate

# 安装依赖
echo ""
echo "📥 安装依赖..."
pip install -r requirements.txt

# 检查 .env 文件
if [ ! -f ".env" ]; then
    echo ""
    echo "⚠️  未找到 .env 文件，从 .env.example 复制..."
    cp .env.example .env
    echo "请编辑 .env 文件并填写配置信息！"
    echo ""
    read -p "是否现在打开编辑器编辑 .env 文件？(y/n): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        ${EDITOR:-nano} .env
    fi
fi

# 初始化数据库
echo ""
echo "🗄️  初始化数据库..."
python -m database.init_db

# 启动应用
echo ""
echo "========================================"
echo "  启动应用"
echo "========================================"
echo ""

python main.py
