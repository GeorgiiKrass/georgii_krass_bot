import asyncio
import contextlib
import json
import logging
import os
import uuid
from pathlib import Path
from urllib.parse import quote

import gspread
from google.oauth2.service_account import Credentials
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand, CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, MenuButtonCommands, Message, ReplyKeyboardMarkup

from store import EVENT_HEADERS, LEAD_HEADERS, USER_HEADERS, Store

ADMIN = int(os.getenv("ADMIN_CHAT_ID", "909231739"))
SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "1GwnxGQkD_h0bTLY5KELUE5s-mLWgzqZ-iFzd2iezC-s")
MANAGER_URL = "https://t.me/Manager_Georgii_Krass"
SALES_OFFICE_URL = "https://maps.app.goo.gl/7Je9qDcMVQQQ9VDL7"
ASSETS = Path(__file__).parent / "assets"
START_BUTTON = "▶️ СТАРТ"
BACK = "🏠 Головне меню"
MENU = ["🏙 ЖК GOLDEN CITY", "🤝 Співпраця зі мною", "👤 Про мене", "📱 Мої соцмережі", "💬 Залишити звернення"]
ADMIN_MENU = "📋 Мої заявки"
CATEGORIES = ["📹 Реклама та інтеграції", "🎬 Співпраця з блогерами", "🎓 Воркшопи та навчання", "🏢 Співпраця з бізнесом"]
SEND = "✅ Надіслати заявку"
CHAT = "Telegram"
PHONE = "Телефон"
SHARE = "📞 Поділитися номером"

PROJECTS = {
    "567": {
        "name": "GOLDEN CITY — 5, 6, 7 секції",
        "menu_photo": "golden_567.png",
        "visual_photo": "golden_567_1.png",
        "video": "golden_567.mp4",
        "presentation_url": "https://budsmart.od.ua/wp-content/uploads/2026/08/07-2026-albom-Golden-syty-3-4-ochered_compressed.pdf",
        "description": "🏙 <b>GOLDEN CITY — 5, 6, 7 секції</b>\n\nСучасний житловий квартал в Одесі із закритою територією, індивідуальним опаленням, резервним живленням та укриттям на кожному поверсі.\n\nДоступні квартири-студії, 1-, 2- та 3-кімнатні квартири. Розтермінування — до 40 місяців, перший внесок — від 10%.",
    },
    "paliia": {
        "name": "GOLDEN CITY на Семена Палія",
        "menu_photo": "golden_paliia.png",
        "visual_photo": "golden_paliia_1.png",
        "video": "golden_paliia.mp4",
        "presentation_url": "https://budsmart.od.ua/wp-content/uploads/2026/10/Golden-City-new-albom-1-3-sektsyy_compressed.pdf",
        "description": "🏙 <b>GOLDEN CITY на Семена Палія</b>\n\nНовий житловий проєкт в Одесі із сучасною архітектурою та продуманою територією.\n\nДоступні квартири-студії, 1- та 2-кімнатні квартири. Розтермінування — до 54 місяців, перший внесок — від 10%.",
    },
}

COLLAB_QUESTIONS = {
    CATEGORIES[0]: "Добрий день! Мене цікавить реклама та інтеграція з Georgii Krass. Хочу обговорити формат співпраці.",
    CATEGORIES[1]: "Добрий день! Мене цікавить співпраця з Georgii Krass як з блогером. Хочу запропонувати спільний контент або колаборацію.",
    CATEGORIES[2]: "Добрий день! Мене цікавить проведення воркшопу або навчання від Georgii Krass. Хочу обговорити формат, учасників і дату.",
    CATEGORIES[3]: "Добрий день! Мене цікавить співпраця бізнесу з Georgii Krass. Хочу обговорити свою пропозицію.",
}
SOCIALS = {"Instagram": "https://www.instagram.com/georgiikrass", "TikTok": "https://www.tiktok.com/@georgiikrass", "YouTube": "https://www.youtube.com/@georgiikrass", "Telegram": MANAGER_URL}

store = None
sheets = None
dp = Dispatcher()

SOURCE_NAMES = {
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "youtube": "YouTube",
    "facebook": "Facebook",
    "outdoor": "Наружка",
    "meta_ads": "Meta Ads",
    "partner": "Партнерка",
    "direct": "Прямой переход",
}


def reply_keyboard(items, add_home=True, contact=False):
    rows = [[KeyboardButton(text=item, request_contact=contact and item == SHARE)] for item in items]
    if add_home and BACK not in items:
        rows.append([KeyboardButton(text=BACK)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


def main_menu_items(uid):
    return MENU + ([ADMIN_MENU] if uid == ADMIN else [])


def url_keyboard(items):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=title, url=url)] for title, url in items])


def manager_link(question):
    return f"{MANAGER_URL}?text={quote(question)}"


def project_actions(project_id, include_visual=True):
    rows = []
    if include_visual:
        presentation_url = PROJECTS[project_id].get("presentation_url")
        if presentation_url:
            rows.append([InlineKeyboardButton(text="⭐️ ПРЕЗЕНТАЦІЯ ТА ПЛАНУВАННЯ", url=presentation_url)])
        else:
            rows.append([InlineKeyboardButton(text="▶️ Подивитися візуалізацію", callback_data=f"video:{project_id}")])
    rows.extend([
        [InlineKeyboardButton(text="📅 Записатися на консультацію", callback_data=f"consult:{project_id}")],
        [InlineKeyboardButton(text="📍 ВІДДІЛ ПРОДАЖУ", url=SALES_OFFICE_URL)],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ensure_worksheet(book, title, headers):
    try:
        worksheet = book.worksheet(title)
    except gspread.WorksheetNotFound:
        worksheet = book.add_worksheet(title, 1000, max(20, len(headers)))
    existing = worksheet.row_values(1)
    if existing and existing != headers:
        raise RuntimeError(f"Заголовки листа {title} відрізняються від шаблону")
    if not existing:
        last_column = gspread.utils.rowcol_to_a1(1, len(headers)).rstrip("1")
        worksheet.update(range_name=f"A1:{last_column}1", values=[headers])
    worksheet.freeze(rows=1)
    return worksheet


def connect_sheets():
    credentials = Credentials.from_service_account_info(json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]), scopes=["https://www.googleapis.com/auth/spreadsheets"])
    client = gspread.authorize(credentials)
    client.set_timeout(20)
    book = client.open_by_key(SHEET_ID)
    return {
        "leads": ensure_worksheet(book, "Заявки", LEAD_HEADERS),
        "users": ensure_worksheet(book, "Користувачі", USER_HEADERS),
        "events": ensure_worksheet(book, "Переходи", EVENT_HEADERS),
    }


def append_unique(worksheet, row):
    if row[0] not in worksheet.col_values(1):
        worksheet.append_row(row, value_input_option="RAW")


def upsert_user(worksheet, row):
    ids = worksheet.col_values(3)
    try:
        row_number = ids.index(row[2]) + 1
    except ValueError:
        worksheet.append_row(row, value_input_option="RAW")
    else:
        end = gspread.utils.rowcol_to_a1(row_number, len(row))
        worksheet.update(range_name=f"A{row_number}:{end}", values=[row])


async def deliver(bot):
    global sheets
    while True:
        if sheets is None:
            try:
                sheets = await asyncio.to_thread(connect_sheets)
            except Exception as error:
                logging.warning("Sheets connection failed: %s", type(error).__name__)
        if sheets is not None:
            try:
                for uid, row in store.pending_users():
                    await asyncio.to_thread(upsert_user, sheets["users"], row)
                    store.mark_user_synced(uid)
                for event_id, row in store.pending_events():
                    await asyncio.to_thread(append_unique, sheets["events"], row)
                    store.mark_event_synced(event_id)
            except Exception as error:
                logging.warning("Sheets analytics write failed: %s", type(error).__name__)
                sheets = None
        for lead_id, row, synced, notified in store.pending():
            if not synced and sheets is not None:
                try:
                    await asyncio.to_thread(append_unique, sheets["leads"], row)
                    store.mark(lead_id, "synced")
                    synced = True
                except Exception as error:
                    logging.warning("Sheets write failed: %s", type(error).__name__)
                    sheets = None
            if not notified:
                labels = ["Заявка", "Дата", "Telegram ID", "Ім’я", "Username", "Телефон", "Зв’язок", "Категорія", "Мета", "ЖК", "Секція", "Квартира", "Оплата", "Бюджет", "Профіль", "Повідомлення", "Джерело"]
                text = "\n".join(f"{label}: {value}" for label, value in zip(labels, row[:17]) if value)
                text += "\n\nGoogle Таблиця: " + ("збережено" if synced else "очікує синхронізації")
                user_url = "https://t.me/" + row[4] if row[4] else "tg://user?id=" + row[2]
                try:
                    await bot.send_message(ADMIN, text[:4000], reply_markup=url_keyboard([("Відкрити контакт", user_url), ("Заявки", f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit")]))
                    store.mark(lead_id, "notified")
                except Exception as error:
                    logging.warning("Telegram notification failed: %s", type(error).__name__)
        await asyncio.sleep(15)


async def send_photo_or_text(message, photo, text, markup=None):
    if photo:
        try:
            media = FSInputFile(photo) if isinstance(photo, Path) else photo
            await message.answer_photo(photo=media, caption=text, reply_markup=markup, parse_mode="HTML")
            return
        except Exception as error:
            logging.warning("Photo send failed: %s", type(error).__name__)
    await message.answer(text, reply_markup=markup, parse_mode="HTML")


async def show_welcome(message):
    text = "<b>GEORGII KRASS | ОДЕСА</b>\n\nНерухомість • Співпраця • Контент • Життя\n\nТут ви можете дізнатися про житлові комплекси GOLDEN CITY, записатися на консультацію або запропонувати співпрацю.\n\nПродовжуючи роботу з ботом, ви погоджуєтеся на обробку даних Telegram для відповіді на звернення."
    await send_photo_or_text(message, ASSETS / "main.png", text, reply_keyboard([START_BUTTON], add_home=False))


async def show_main_menu(message):
    await message.answer(
        "Оберіть потрібний розділ 👇",
        reply_markup=reply_keyboard(main_menu_items(message.from_user.id), add_home=False),
    )


async def show_projects(message):
    await message.answer("🏙 <b>ЖК GOLDEN CITY</b>\n\nОберіть житловий комплекс, який вас цікавить.", parse_mode="HTML")
    for project_id in ("567", "paliia"):
        project = PROJECTS[project_id]
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Відкрити комплекс", callback_data=f"project:{project_id}")]])
        await send_photo_or_text(message, ASSETS / project["menu_photo"], f"<b>{project['name']}</b>", markup)
    await message.answer("Повернутися до головного меню можна кнопкою нижче.", reply_markup=reply_keyboard([BACK], add_home=False))


async def show_collaboration(message):
    rows = [[InlineKeyboardButton(text=category, callback_data=f"collab:{index}")] for index, category in enumerate(CATEGORIES)]
    await message.answer("🤝 <b>СПІВПРАЦЯ ЗІ МНОЮ</b>\n\nОберіть формат співпраці:", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await message.answer("Для повернення використайте кнопку нижче.", reply_markup=reply_keyboard([BACK], add_home=False))


async def ask(message, data, step, prompt, items=None, contact=False):
    data["step"] = step
    store.put_session(message.from_user.id, data)
    await message.answer(prompt, reply_markup=reply_keyboard(items or [], contact=contact))


async def review(message, data):
    summary = "\n".join(f"{label}: {data[key]}" for label, key in [("Напрям", "category"), ("Повідомлення", "message"), ("Зв’язок", "contact"), ("Телефон", "phone")] if data.get(key))
    await ask(message, data, "confirm", "Перевірте звернення:\n\n" + summary, [SEND])


@dp.message(CommandStart())
async def start(message: Message):
    if message.chat.type != "private" or message.from_user is None:
        return
    code = message.text.split(maxsplit=1)[1][:64].lower() if len(message.text.split(maxsplit=1)) > 1 else "direct"
    source = SOURCE_NAMES.get(code, SOURCE_NAMES["direct"])
    store.put_session(message.from_user.id, {"step": "welcome", "source": source})
    store.touch_user(message.from_user, source, "Запуск бота", increment_start=True)
    store.add_event(message.from_user, source, "Запуск бота")
    await show_welcome(message)


@dp.message(Command("menu"))
async def menu_command(message: Message):
    if message.chat.type != "private" or message.from_user is None:
        return
    data = store.session(message.from_user.id)
    source = data.get("source", SOURCE_NAMES["direct"])
    store.put_session(message.from_user.id, {"step": "menu", "source": source})
    store.touch_user(message.from_user, source, "Головне меню")
    store.add_event(message.from_user, source, "Відкрив меню", "Команда /menu")
    await show_main_menu(message)


@dp.callback_query(F.data.startswith("project:"))
async def open_project(callback: CallbackQuery):
    project_id = callback.data.split(":", 1)[1]
    if project_id not in PROJECTS:
        await callback.answer("Комплекс не знайдено", show_alert=True)
        return
    await callback.answer()
    project = PROJECTS[project_id]
    source = store.session(callback.from_user.id).get("source", SOURCE_NAMES["direct"])
    store.touch_user(callback.from_user, source, "Відкрив ЖК")
    store.add_event(callback.from_user, source, "Відкрив ЖК", project["name"])
    await send_photo_or_text(callback.message, ASSETS / project["visual_photo"], project["description"], project_actions(project_id))


@dp.callback_query(F.data.startswith("video:"))
async def show_video(callback: CallbackQuery):
    project_id = callback.data.split(":", 1)[1]
    if project_id not in PROJECTS:
        await callback.answer("Комплекс не знайдено", show_alert=True)
        return
    project = PROJECTS[project_id]
    video = ASSETS / project["video"]
    if not video.exists():
        await callback.answer("Відео скоро буде додано", show_alert=True)
        return
    await callback.answer()
    source = store.session(callback.from_user.id).get("source", SOURCE_NAMES["direct"])
    store.touch_user(callback.from_user, source, "Переглянув візуалізацію")
    store.add_event(callback.from_user, source, "Переглянув візуалізацію", project["name"])
    try:
        await callback.message.answer_video(video=FSInputFile(video), caption=f"Візуалізація: {project['name']}", reply_markup=project_actions(project_id, include_visual=False))
    except Exception:
        await callback.message.answer("Не вдалося відкрити відео. Спробуйте пізніше.", reply_markup=project_actions(project_id, include_visual=False))


@dp.callback_query(F.data.startswith("consult:"))
async def consultation(callback: CallbackQuery):
    project_id = callback.data.split(":", 1)[1]
    if project_id not in PROJECTS:
        await callback.answer("Комплекс не знайдено", show_alert=True)
        return
    await callback.answer()
    project = PROJECTS[project_id]
    source = store.session(callback.from_user.id).get("source", SOURCE_NAMES["direct"])
    store.touch_user(callback.from_user, source, "Консультація")
    store.add_event(callback.from_user, source, "Запис на консультацію", project["name"])
    store.submit(callback.from_user.id, {
        "name": callback.from_user.full_name,
        "username": callback.from_user.username or "",
        "category": "Консультація у відділі продажу",
        "purpose": "Запис на консультацію",
        "project": project["name"],
        "message": "Користувач натиснув кнопку запису на консультацію",
        "source": source,
    })
    question = f"Добрий день! На коли можна записатися на консультацію у відділ продажу {project['name']}?"
    markup = url_keyboard([
        ("💬 Написати менеджеру", manager_link(question)),
        ("📍 ВІДДІЛ ПРОДАЖУ", SALES_OFFICE_URL),
    ])
    await callback.message.answer(
        "Натисніть кнопку нижче — Telegram відкриє чат із менеджером і підставить готове повідомлення.",
        reply_markup=markup,
    )


@dp.callback_query(F.data.startswith("collab:"))
async def collaboration(callback: CallbackQuery):
    try:
        index = int(callback.data.split(":", 1)[1])
        category = CATEGORIES[index]
    except (ValueError, IndexError):
        await callback.answer("Формат не знайдено", show_alert=True)
        return
    await callback.answer()
    source = store.session(callback.from_user.id).get("source", SOURCE_NAMES["direct"])
    store.touch_user(callback.from_user, source, "Співпраця")
    store.add_event(callback.from_user, source, "Співпраця", category)
    store.submit(callback.from_user.id, {
        "name": callback.from_user.full_name,
        "username": callback.from_user.username or "",
        "category": category,
        "purpose": "Запит на співпрацю",
        "message": "Користувач обрав формат співпраці та отримав посилання на менеджера",
        "source": source,
    })
    await callback.message.answer(
        f"Обрано: <b>{category}</b>\n\nНатисніть кнопку, щоб написати менеджеру.",
        parse_mode="HTML",
        reply_markup=url_keyboard([("💬 Написати менеджеру", manager_link(COLLAB_QUESTIONS[category]))]),
    )


@dp.message()
async def handle(message: Message):
    if message.chat.type != "private" or message.from_user is None:
        return
    uid = message.from_user.id
    text = message.text or ""
    data = store.session(uid)
    step = data.get("step", "welcome")
    source = data.get("source", SOURCE_NAMES["direct"])
    if text == "/myid":
        await message.answer(str(uid))
    elif text == START_BUTTON:
        data["step"] = "menu"
        store.put_session(uid, data)
        store.touch_user(message.from_user, source, "Головне меню")
        store.add_event(message.from_user, source, "Відкрив меню")
        await show_main_menu(message)
    elif text in (BACK, "/cancel"):
        data["step"] = "menu"
        store.put_session(uid, data)
        await show_main_menu(message)
    elif text == MENU[0]:
        store.touch_user(message.from_user, source, "ЖК GOLDEN CITY")
        store.add_event(message.from_user, source, "Відкрив розділ", "ЖК GOLDEN CITY")
        await show_projects(message)
    elif text == MENU[1]:
        store.touch_user(message.from_user, source, "Співпраця")
        store.add_event(message.from_user, source, "Відкрив розділ", "Співпраця зі мною")
        await show_collaboration(message)
    elif text == MENU[2]:
        about = "<b>Georgii Krass</b>\n\nЖиву та працюю в Одесі. Створюю контент про життя, місто та нерухомість. Проводжу практичні воркшопи зі зйомки коротких відео для компаній і студентів."
        store.touch_user(message.from_user, source, "Про мене")
        store.add_event(message.from_user, source, "Відкрив розділ", "Про мене")
        await send_photo_or_text(message, ASSETS / "main.png", about)
        await message.answer("Оберіть наступний розділ:", reply_markup=reply_keyboard([MENU[0], MENU[1], BACK], add_home=False))
    elif text == MENU[3]:
        store.touch_user(message.from_user, source, "Соцмережі")
        store.add_event(message.from_user, source, "Відкрив розділ", "Мої соцмережі")
        await message.answer("Мої соцмережі та особистий контакт:", reply_markup=url_keyboard(list(SOCIALS.items())))
    elif text == MENU[4]:
        store.touch_user(message.from_user, source, "Залишити звернення")
        store.add_event(message.from_user, source, "Почав звернення")
        data = {"step": "message", "source": source, "name": message.from_user.full_name, "username": message.from_user.username or "", "form_id": str(uuid.uuid4()), "category": "Загальне звернення"}
        await ask(message, data, "message", "Напишіть ваше питання або пропозицію (до 1500 символів).")
    elif text == ADMIN_MENU and uid == ADMIN:
        rows = store.mine(uid)
        result = "\n\n".join(f"{row[1]} · {row[7]}\nID: {row[0]}\nСтатус: {row[17]}" for row in rows)
        await message.answer(
            result or "Ви ще не надсилали звернень.",
            reply_markup=reply_keyboard(main_menu_items(uid), add_home=False),
        )
    elif step == "message" and text and len(text) <= 1500:
        data["message"] = text
        await ask(message, data, "contact", "Як вам зручніше отримати відповідь?", [CHAT, PHONE])
    elif step == "contact" and text in (CHAT, PHONE):
        data["contact"] = text
        if text == CHAT:
            await review(message, data)
        else:
            await ask(message, data, "phone", "Поділіться вашим номером кнопкою нижче:", [SHARE], contact=True)
    elif step == "phone" and message.contact:
        if message.contact.user_id != uid:
            await message.answer("Поділіться саме своїм номером за допомогою кнопки.")
            return
        data["phone"] = message.contact.phone_number
        await review(message, data)
    elif step == "confirm" and text == SEND:
        lead_id = store.submit(uid, data)
        store.put_session(uid, {"step": "menu", "source": data.get("source", SOURCE_NAMES["direct"])})
        store.touch_user(message.from_user, source, "Надіслав звернення")
        store.add_event(message.from_user, source, "Надіслав звернення", "Загальне звернення")
        await message.answer(
            f"✅ Ваше звернення прийнято.\n\nНомер: {lead_id}",
            reply_markup=reply_keyboard(main_menu_items(uid), add_home=False),
        )
    else:
        await message.answer("Натисніть «СТАРТ» або оберіть потрібний розділ.", reply_markup=reply_keyboard([START_BUTTON], add_home=False))


async def main():
    global store
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    token = os.environ["BOT_TOKEN"]
    json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    folder = Path(os.getenv("DATA_DIR", os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "./data")))
    folder.mkdir(parents=True, exist_ok=True)
    store = Store(folder / "bot.sqlite3")
    bot = Bot(token)
    await bot.set_my_commands([
        BotCommand(command="start", description="Запустити бота"),
        BotCommand(command="menu", description="Відкрити головне меню"),
    ])
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    await bot.delete_webhook(drop_pending_updates=False)
    worker = asyncio.create_task(deliver(bot))
    try:
        await dp.start_polling(bot, handle_as_tasks=False, close_bot_session=False)
    finally:
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
