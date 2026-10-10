import json
import sqlite3
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

HEADERS = ['ID заявки', 'Дата й час', 'Telegram ID', 'Ім’я', 'Username', 'Телефон', 'Спосіб зв’язку', 'Категорія', 'Мета звернення', 'ЖК', 'Секція', 'Тип квартири', 'Спосіб оплати', 'Бюджет', 'Компанія або профіль', 'Повідомлення', 'Джерело переходу', 'Статус', 'Дата консультації', 'Коментар']

class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('CREATE TABLE IF NOT EXISTS sessions (uid INTEGER PRIMARY KEY, payload TEXT); CREATE TABLE IF NOT EXISTS leads (id TEXT PRIMARY KEY, uid INTEGER, payload TEXT, synced INTEGER DEFAULT 0, notified INTEGER DEFAULT 0);')

    def session(self, uid):
        row = self.db.execute('SELECT payload FROM sessions WHERE uid=?', (uid,)).fetchone()
        return json.loads(row[0]) if row else {'source': 'direct', 'step': 'menu'}

    def put_session(self, uid, data):
        self.db.execute('INSERT OR REPLACE INTO sessions VALUES (?,?)', (uid, json.dumps(data, ensure_ascii=False)))
        self.db.commit()

    def submit(self, uid, data):
        # Same form cannot create a second lead after a retry or restart.
        lead_id = data.setdefault('form_id', str(uuid.uuid4()))
        row = [lead_id, datetime.now(ZoneInfo('Europe/Kyiv')).strftime('%Y-%m-%d %H:%M:%S'), str(uid), data.get('name',''), data.get('username',''), data.get('phone',''), data.get('contact',''), data.get('category',''), data.get('purpose',''), data.get('project',''), data.get('section',''), data.get('apartment',''), data.get('payment',''), data.get('budget',''), data.get('profile',''), data.get('message',''), data.get('source','direct'), 'Нова', '', '']
        self.db.execute('INSERT OR IGNORE INTO leads (id,uid,payload) VALUES (?,?,?)', (lead_id, uid, json.dumps(row, ensure_ascii=False)))
        self.db.commit()
        return lead_id

    def pending(self):
        return [(r[0], json.loads(r[1]), r[2], r[3]) for r in self.db.execute('SELECT id,payload,synced,notified FROM leads WHERE synced=0 OR notified=0 ORDER BY rowid LIMIT 25')]

    def mark(self, lead_id, field):
        assert field in ('synced','notified')
        self.db.execute(f'UPDATE leads SET {field}=1 WHERE id=?', (lead_id,))
        self.db.commit()

    def mine(self, uid):
        return [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM leads WHERE uid=? ORDER BY rowid DESC LIMIT 5', (uid,))]
