"""Test bootstrap for CI-friendly defaults."""

from __future__ import annotations

import os


os.environ.setdefault("TG_API_ID", "123456")
os.environ.setdefault("TG_API_HASH", "test-api-hash")
os.environ.setdefault("BOT_TOKEN", "123456:test-bot-token")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://tester:tester@localhost:5432/tg_auto_msg_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
