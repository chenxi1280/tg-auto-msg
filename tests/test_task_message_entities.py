import unittest
from types import SimpleNamespace

from telethon import helpers
from telethon.tl import types

from backend.database.schema.models import MediaType
from backend.scheduler.core.task_execution import build_telegram_text_and_entities, do_send_message


def _entity_text(text: str, entity) -> str:
    surrogate = helpers.add_surrogate(text)
    start = entity.offset
    end = start + entity.length
    return helpers.del_surrogate(surrogate[start:end])


def test_raw_telegram_username_gets_explicit_mention_entity():
    text, entities = build_telegram_text_and_entities("有事情请找@meimei0418_Bot")

    mentions = [entity for entity in entities or [] if isinstance(entity, types.MessageEntityMention)]
    assert text == "有事情请找@meimei0418_Bot"
    assert [_entity_text(text, entity) for entity in mentions] == ["@meimei0418_Bot"]


def test_html_parse_mode_is_preserved_while_raw_mentions_and_urls_stay_clickable():
    text, entities = build_telegram_text_and_entities(
        '🔔<b>找@meimei0418_Bot</b> 或 https://t.me/meimei0418_Bot'
    )

    assert text == "🔔找@meimei0418_Bot 或 https://t.me/meimei0418_Bot"
    assert any(isinstance(entity, types.MessageEntityBold) for entity in entities or [])
    assert any(
        isinstance(entity, types.MessageEntityMention)
        and _entity_text(text, entity) == "@meimei0418_Bot"
        for entity in entities or []
    )
    assert any(
        isinstance(entity, types.MessageEntityUrl)
        and _entity_text(text, entity) == "https://t.me/meimei0418_Bot"
        for entity in entities or []
    )


class ScheduledTaskSendEntityTests(unittest.IsolatedAsyncioTestCase):
    async def test_task_send_passes_explicit_formatting_entities(self):
        class FakeClient:
            def __init__(self):
                self.args = None
                self.kwargs = None

            async def send_message(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs
                return SimpleNamespace(id=123)

        client = FakeClient()
        task = SimpleNamespace(
            task_id="task-1",
            text="有事情请找@meimei0418_Bot",
            buttons=None,
            media_type=MediaType.NONE,
            delete_previous=False,
            pin_message=False,
        )

        message_id = await do_send_message(
            client=client,
            task=task,
            send_target=10001,
            previous_message_id=None,
            media_ref_prefix="tgmsg://",
        )

        self.assertEqual(message_id, 123)
        self.assertIsNone(client.kwargs["parse_mode"])
        mentions = [
            entity
            for entity in client.kwargs["formatting_entities"]
            if isinstance(entity, types.MessageEntityMention)
        ]
        self.assertTrue(mentions)
        self.assertEqual(_entity_text(client.args[1], mentions[0]), "@meimei0418_Bot")
