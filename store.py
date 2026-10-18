import json
import sqlite3
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo


KYIV = ZoneInfo("Europe/Kyiv")

LEAD_HEADERS = [
    "ID заявки", "Дата й час", "Telegram ID", "Ім’я", "Username", "Телефон",
    "Спосіб зв’язку", "Категорія", "Мета звернення", "ЖК", "Секція",
    "Тип квартири", "Спосіб оплати", "Бюджет", "Компанія або профіль",
    "Повідомлення", "Джерело переходу", "Статус", "Дата консультації", "Коментар",
]
USER_HEADERS = [
    "Перша активність", "Остання активність", "Telegram ID", "Ім’я", "Прізвище",
    "Username", "Мова Telegram", "Перше джерело", "Останнє джерело",
    "Кількість запусків", "Остання дія",
]
EVENT_HEADERS = [
    "ID події", "Дата й час", "Telegram ID", "Ім’я", "Username",
    "Джерело переходу", "Дія", "Розділ або ЖК",
]

# Compatibility with previous code/tests.
HEADERS = LEAD_HEADERS


def now_text():
    return datetime.now(KYIV).strftime("%Y-%m-%d %H:%M:%S")


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(
            "CREATE TABLE IF NOT EXISTS sessions (uid INTEGER PRIMARY KEY, payload TEXT);"
            "CREATE TABLE IF NOT EXISTS leads (id TEXT PRIMARY KEY, uid INTEGER, payload TEXT, synced INTEGER DEFAULT 0, notified INTEGER DEFAULT 0);"
            "CREATE TABLE IF NOT EXISTS users (uid INTEGER PRIMARY KEY, payload TEXT, synced INTEGER DEFAULT 0);"
            "CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, uid INTEGER, payload TEXT, synced INTEGER DEFAULT 0);"
        )

    def session(self, uid):
        row = self.db.execute("SELECT payload FROM sessions WHERE uid=?", (uid,)).fetchone()
        return json.loads(row[0]) if row else {"source": "Прямой переход", "step": "menu"}

    def put_session(self, uid, data):
        self.db.execute(
            "INSERT OR REPLACE INTO sessions VALUES (?,?)",
            (uid, json.dumps(data, ensure_ascii=False)),
        )
        self.db.commit()

    def touch_user(self, user, source, action, increment_start=False):
        uid = user.id
        existing = self.db.execute("SELECT payload FROM users WHERE uid=?", (uid,)).fetchone()
        current = json.loads(existing[0]) if existing else None
        now = now_text()
        first_source = current[7] if current else source
        starts = int(current[9]) if current else 0
        if increment_start:
            starts += 1
        row = [
            current[0] if current else now,
            now,
            str(uid),
            getattr(user, "first_name", "") or "",
            getattr(user, "last_name", "") or "",
            getattr(user, "username", "") or "",
            getattr(user, "language_code", "") or "",
            first_source,
            source,
            starts,
            action,
        ]
        self.db.execute(
            "INSERT INTO users (uid,payload,synced) VALUES (?,?,0) "
            "ON CONFLICT(uid) DO UPDATE SET payload=excluded.payload,synced=0",
            (uid, json.dumps(row, ensure_ascii=False)),
        )
        self.db.commit()

    def add_event(self, user, source, action, section=""):
        event_id = str(uuid.uuid4())
        row = [
            event_id,
            now_text(),
            str(user.id),
            getattr(user, "full_name", "") or "",
            getattr(user, "username", "") or "",
            source,
            action,
            section,
        ]
        self.db.execute(
            "INSERT INTO events (id,uid,payload) VALUES (?,?,?)",
            (event_id, user.id, json.dumps(row, ensure_ascii=False)),
        )
        self.db.commit()
        return event_id

    def submit(self, uid, data):
        lead_id = data.setdefault("form_id", str(uuid.uuid4()))
        row = [
            lead_id, now_text(), str(uid), data.get("name", ""), data.get("username", ""),
            data.get("phone", ""), data.get("contact", ""), data.get("category", ""),
            data.get("purpose", ""), data.get("project", ""), data.get("section", ""),
            data.get("apartment", ""), data.get("payment", ""), data.get("budget", ""),
            data.get("profile", ""), data.get("message", ""), data.get("source", "Прямой переход"),
            "Нова", "", "",
        ]
        self.db.execute(
            "INSERT OR IGNORE INTO leads (id,uid,payload) VALUES (?,?,?)",
            (lead_id, uid, json.dumps(row, ensure_ascii=False)),
        )
        self.db.commit()
        return lead_id

    def pending(self):
        return [
            (row[0], json.loads(row[1]), row[2], row[3])
            for row in self.db.execute(
                "SELECT id,payload,synced,notified FROM leads "
                "WHERE synced=0 OR notified=0 ORDER BY rowid LIMIT 25"
            )
        ]

    def pending_users(self):
        return [
            (row[0], json.loads(row[1]))
            for row in self.db.execute("SELECT uid,payload FROM users WHERE synced=0 ORDER BY uid LIMIT 50")
        ]

    def pending_events(self):
        return [
            (row[0], json.loads(row[1]))
            for row in self.db.execute("SELECT id,payload FROM events WHERE synced=0 ORDER BY rowid LIMIT 100")
        ]

    def mark(self, lead_id, field):
        assert field in ("synced", "notified")
        self.db.execute(f"UPDATE leads SET {field}=1 WHERE id=?", (lead_id,))
        self.db.commit()

    def mark_user_synced(self, uid):
        self.db.execute("UPDATE users SET synced=1 WHERE uid=?", (uid,))
        self.db.commit()

    def mark_event_synced(self, event_id):
        self.db.execute("UPDATE events SET synced=1 WHERE id=?", (event_id,))
        self.db.commit()

    def mine(self, uid):
        return [
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT payload FROM leads WHERE uid=? ORDER BY rowid DESC LIMIT 5", (uid,)
            )
        ]
