#!/usr/bin/env python3
"""Seed fixed sing-box gateway proxies for account-level reauth."""
from __future__ import annotations

import asyncio

from backend.bot.account.proxy_observation import SING_BOX_PROXY_REGIONS, upsert_sing_box_proxy_region
from backend.database.runtime.session import get_async_session


async def main() -> None:
    async with get_async_session() as session:
        rows = []
        for region in SING_BOX_PROXY_REGIONS:
            proxy = await upsert_sing_box_proxy_region(session, region)
            rows.append((region.label, proxy.proxy_id, proxy.host, proxy.port))
        await session.commit()

    for label, proxy_id, host, port in rows:
        print(f"{label}: proxy_id={proxy_id} socks5://{host}:{port}")


if __name__ == "__main__":
    asyncio.run(main())
