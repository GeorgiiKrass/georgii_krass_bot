import tempfile
import unittest
from pathlib import Path
from store import Store, HEADERS


class User:
    id = 12
    first_name = 'Test'
    last_name = 'User'
    username = 'tester'
    language_code = 'uk'
    full_name = 'Test User'

class StoreTests(unittest.TestCase):
    def test_submission_retry_and_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'test.sqlite3'
            first = Store(path)
            data = {'form_id':'stable-id','category':'Нерухомість','source':'instagram_test','phone':'+380123456789','project':'GOLDEN CITY на Семена Палія','message':'=IMPORTXML("x")'}
            first.put_session(12,data)
            first.touch_user(User(), 'Instagram', 'Запуск бота', increment_start=True)
            first.add_event(User(), 'Instagram', 'Запуск бота')
            first.submit(12,data)
            first.submit(12,data)
            first.db.close()
            second = Store(path)
            self.assertEqual(second.session(12),data)
            rows = second.mine(12)
            self.assertEqual(len(rows),1)
            self.assertEqual(len(rows[0]),len(HEADERS))
            self.assertEqual(rows[0][16],'instagram_test')
            self.assertEqual(rows[0][15],data['message'])
            self.assertEqual(second.mine(13),[])
            self.assertEqual(len(second.pending_users()), 1)
            self.assertEqual(len(second.pending_events()), 1)
            second.mark('stable-id','synced')
            self.assertEqual(len(second.pending()),1)
            second.mark('stable-id','notified')
            self.assertEqual(second.pending(),[])
            second.db.close()

if __name__ == '__main__':
    unittest.main()
