import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import main
from store import Store


class FlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        main.store = Store(Path(self.folder.name) / "test.sqlite3")
        main.sheets = None
        self.m = SimpleNamespace(
            from_user=SimpleNamespace(id=42, full_name="Test User", first_name="Test", last_name="User", username=None, language_code="uk"),
            chat=SimpleNamespace(type="private"), text="", contact=None,
            answer=AsyncMock(), answer_photo=AsyncMock(), answer_video=AsyncMock(),
        )

    def tearDown(self):
        main.store.db.close()
        self.folder.cleanup()

    async def say(self, text):
        self.m.text = text
        await main.handle(self.m)

    async def test_start_then_main_menu(self):
        self.m.text = "/start instagram"
        await main.start(self.m)
        self.assertEqual(main.store.session(42)["step"], "welcome")
        self.assertEqual(main.store.session(42)["source"], "Instagram")
        await self.say(main.START_BUTTON)
        self.assertEqual(main.store.session(42)["step"], "menu")

    async def test_project_cards_and_visual(self):
        await self.say(main.MENU[0])
        self.assertEqual(self.m.answer_photo.call_count, 2)
        self.assertGreaterEqual(self.m.answer.call_count, 2)
        callback = SimpleNamespace(data="project:567", message=self.m, from_user=self.m.from_user, answer=AsyncMock())
        await main.open_project(callback)
        callback.answer.assert_awaited_once()
        self.m.answer_photo.assert_awaited()

    async def test_video_missing_shows_alert(self):
        callback = SimpleNamespace(data="video:paliia", message=self.m, from_user=self.m.from_user, answer=AsyncMock())
        with tempfile.TemporaryDirectory() as empty, patch.object(main, "ASSETS", Path(empty)):
            await main.show_video(callback)
        callback.answer.assert_awaited_once_with("Відео скоро буде додано", show_alert=True)

    def test_prefilled_manager_links(self):
        markup = main.project_actions("paliia")
        self.assertEqual(markup.inline_keyboard[1][0].callback_data, "consult:paliia")
        self.assertIn("maps.app.goo.gl", markup.inline_keyboard[2][0].url)
        for question in main.COLLAB_QUESTIONS.values():
            self.assertIn("text=", main.manager_link(question))

    async def test_consultation_and_collaboration_create_leads(self):
        consultation = SimpleNamespace(
            data="consult:567", message=self.m, from_user=self.m.from_user, answer=AsyncMock()
        )
        await main.consultation(consultation)
        collaboration = SimpleNamespace(
            data="collab:0", message=self.m, from_user=self.m.from_user, answer=AsyncMock()
        )
        await main.collaboration(collaboration)
        rows = main.store.mine(42)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][7], main.CATEGORIES[0])
        self.assertEqual(rows[1][9], main.PROJECTS["567"]["name"])

    async def test_general_request_still_saved(self):
        for value in [main.MENU[4], "Тестове звернення", main.CHAT, main.SEND]:
            await self.say(value)
        rows = main.store.mine(42)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][7], "Загальне звернення")

    def test_sheets_retry_does_not_duplicate(self):
        fake = SimpleNamespace(col_values=lambda _: ["ID заявки", "existing-id"], append_row=lambda *a, **k: self.fail("Duplicate append"))
        main.sheets = {"leads": fake}
        main.append_unique(fake, ["existing-id"])


if __name__ == "__main__":
    unittest.main()
