import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import main
from store import Store

class FlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        main.store = Store(Path(self.folder.name)/'test.sqlite3')
        main.sheet = None
        self.m = SimpleNamespace(from_user=SimpleNamespace(id=42,full_name='Test User',username=None),chat=SimpleNamespace(type='private'),text='',contact=None,answer=AsyncMock(),answer_photo=AsyncMock())

    def tearDown(self):
        main.store.db.close()
        self.folder.cleanup()

    async def say(self,text):
        self.m.text = text
        await main.handle(self.m)

    async def test_apartment_with_source_and_no_phone(self):
        self.m.text='/start instagram_test'
        await main.start(self.m)
        for t in [main.MENU[0],main.PROJECTS[0],'6 секція',main.ACTIONS[0],'3-кімнатна',main.PAYMENTS[1],main.SKIP,'Хочу консультацію',main.CHAT,main.SEND]:
            await self.say(t)
        row = main.store.mine(42)[0]
        self.assertEqual(row[10],'6 секція')
        self.assertEqual(row[11],'3-кімнатна')
        self.assertEqual(row[16],'instagram_test')
        self.assertEqual(row[5],'')
        await self.say(main.SEND)
        self.assertEqual(len(main.store.mine(42)),1)

    async def test_consultation_and_contact_ownership(self):
        for t in [main.MENU[0],main.PROJECTS[1],main.ACTIONS[2],'У суботу',main.PHONE]:
            await self.say(t)
        self.m.contact=SimpleNamespace(user_id=99,phone_number='+380bad')
        await self.say('')
        self.assertEqual(main.store.session(42)['step'],'phone')
        self.m.contact=SimpleNamespace(user_id=42,phone_number='+380123456789')
        await self.say('')
        self.m.contact=None
        await self.say(main.SEND)
        row=main.store.mine(42)[0]
        self.assertEqual(row[5],'+380123456789')
        self.assertEqual(row[9],main.PROJECTS[1])
        self.assertEqual(row[11],'')

    async def test_collaboration_categories(self):
        for category in main.CATEGORIES:
            for t in [main.MENU[1],category,'https://example.com','Пропозиція',main.CHAT,main.SEND]:
                await self.say(t)
        self.assertEqual({r[7] for r in main.store.mine(42)},set(main.CATEGORIES))

    async def test_cancel_removes_previous_answers(self):
        for t in [main.MENU[0],main.PROJECTS[0],'5 секція','/cancel',main.MENU[4],'Питання',main.CHAT,main.SEND]:
            await self.say(t)
        row = main.store.mine(42)[0]
        self.assertEqual(row[7],'Загальне звернення')
        self.assertEqual(row[9:14],['']*5)

    def test_sheets_retry_does_not_duplicate(self):
        fake=SimpleNamespace(col_values=lambda _:['ID заявки','existing-id'],append_row=lambda *args,**kwargs: self.fail('Duplicate append'))
        main.sheet=fake
        main.append_unique(['existing-id'])

if __name__ == '__main__':
    unittest.main()
