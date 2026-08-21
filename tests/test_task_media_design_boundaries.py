"""Regression checks for the V2 task-media product boundary."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_bot_help_describes_automatic_single_media_only():
    messages_source = _source("backend/bot/ui/messages.py")
    manual = messages_source.split('BOT_HELP_MANUAL = """', 1)[1].split('"""', 1)[0]

    assert "系统会自动识别类型，不需要选择模式" in manual
    assert "不支持贴纸、普通文件、语音、相册和消息按钮" in manual
    assert "图片、视频、动图、贴纸" not in manual
    assert "文本 + 媒体 + 按钮" not in manual


def test_bot_media_entry_activates_capture_without_parsing_deep_link():
    editing_source = _source("backend/bot/handlers/task/editing.py")

    assert "activate_capture_for_actor(event, capture.capture_id)" in editing_source
    assert '.rsplit("media_", 1)' not in editing_source
    assert "activate_capture_from_start" not in editing_source


def test_capture_prompt_explicitly_auto_detects_media_type():
    activation_source = _source("backend/task_media/capture_activation.py")

    assert "系统会自动识别媒体类型" in activation_source
    assert "普通文件、贴纸、语音和相册不支持" in activation_source


def test_media_chain_never_downloads_or_buffers_file_bytes():
    media_sources = "\n".join(
        _source(path)
        for path in (
            "backend/task_media/capture_service.py",
            "backend/task_media/telegram_gateway.py",
        )
    )

    assert "download_media" not in media_sources
    assert "BytesIO" not in media_sources
    assert "bytearray(" not in media_sources
