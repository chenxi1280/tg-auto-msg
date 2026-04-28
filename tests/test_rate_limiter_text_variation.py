from backend.bot.safety.rate_limiter import RateLimiter


def _strip_zero_width(text: str) -> str:
    for char in RateLimiter.ZERO_WIDTH_CHARS:
        text = text.replace(char, "")
    return text


def test_invisible_variation_keeps_telegram_username_clickable():
    limiter = RateLimiter(redis_url="redis://example.invalid/0")
    text = "个人开课，有🏠可外出，人照一致美美: @meimei0418_Bot"

    for _ in range(50):
        varied = limiter.add_invisible_variation(text)

        assert _strip_zero_width(varied) == text
        assert "@meimei0418_Bot" in varied


def test_invisible_variation_protects_urls_and_html_fragments():
    limiter = RateLimiter(redis_url="redis://example.invalid/0")
    text = '点击 <a href="https://t.me/meimei0418_Bot">联系</a> &amp; 备用 https://t.me/meimei0418_Bot'

    for _ in range(50):
        varied = limiter.add_invisible_variation(text)

        assert _strip_zero_width(varied) == text
        assert 'href="https://t.me/meimei0418_Bot"' in varied
        assert "&amp;" in varied
        assert "https://t.me/meimei0418_Bot" in varied
