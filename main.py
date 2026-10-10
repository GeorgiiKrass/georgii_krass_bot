import asyncio
import contextlib
import json
import logging
import os
import uuid
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from store import Store, HEADERS

ADMIN = int(os.getenv('ADMIN_CHAT_ID', '909231739'))
SHEET_ID = os.getenv('GOOGLE_SHEET_ID', '1GwnxGQkD_h0bTLY5KELUE5s-mLWgzqZ-iFzd2iezC-s')
MENU = ['🏙 Обрати квартиру', '🤝 Співпраця зі мною', '👤 Про мене', '📱 Мої соцмережі', '💬 Залишити звернення', '📋 Мої заявки']
PROJECTS = ['GOLDEN CITY — 5, 6, 7 секції', 'GOLDEN CITY на Семена Палія']
SECTIONS = ['5 секція', '6 секція', '7 секція', 'Допоможіть обрати']
ACTIONS = ['Підібрати квартиру', 'Дізнатися вартість', 'Записатися на консультацію']
CATEGORIES = ['Реклама та інтеграції', 'Співпраця з блогерами', 'Воркшопи', 'Інша бізнес-пропозиція']
BACK = '🏠 Головне меню'
SKIP = 'Пропустити'
SEND = '✅ Надіслати заявку'
CHAT = 'Telegram'
PHONE = 'Телефон'
SHARE = '📞 Поділитися номером'
PAYMENTS = ['Повна оплата', 'Розтермінування', 'Потрібна консультація']
SOCIALS = {'Instagram': 'https://www.instagram.com/georgiikrass', 'TikTok': 'https://www.tiktok.com/@georgiikrass', 'YouTube': 'https://www.youtube.com/@georgiikrass', 'Telegram': 'https://t.me/Manager_Georgii_Krass'}
store = None
sheet = None
dp = Dispatcher()

def kb(items, contact=False):
    rows = [[KeyboardButton(text=i, request_contact=True)] if contact and i == SHARE else [KeyboardButton(text=i)] for i in items]
    if BACK not in items:
        rows.append([KeyboardButton(text=BACK)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def links(items):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=k, url=v)] for k,v in items.items()])

def connect_sheet():
    raw = os.environ['GOOGLE_SERVICE_ACCOUNT_JSON']
    creds = Credentials.from_service_account_info(json.loads(raw), scopes=['https://www.googleapis.com/auth/spreadsheets'])
    client = gspread.authorize(creds)
    client.set_timeout(20)
    book = client.open_by_key(SHEET_ID)
    try:
        ws = book.worksheet('Заявки')
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet('Заявки', 1000, 20)
    existing = ws.row_values(1)
    if existing and existing != HEADERS:
        raise RuntimeError('Заголовки листа Заявки відрізняються від шаблону. Дані не змінено.')
    if not existing:
        ws.update(range_name='A1:T1', values=[HEADERS])
    ws.freeze(rows=1)
    views = {'Нерухомість':'Нерухомість', 'Реклама':'Реклама та інтеграції', 'Блогери':'Співпраця з блогерами', 'Воркшопи':'Воркшопи', 'Бізнес':'Інша бізнес-пропозиція', 'Інші звернення':'Загальне звернення'}
    for title, category in views.items():
        try:
            book.worksheet(title)
        except gspread.WorksheetNotFound:
            view = book.add_worksheet(title, 1000, 20)
            view.update(range_name='A1:T1', values=[HEADERS])
            formula = '=IFERROR(FILTER(\'Заявки\'!A2:T;\'Заявки\'!H2:H="' + category + '");"")'
            view.update(range_name='A2', values=[[formula]], value_input_option='USER_ENTERED')
            view.freeze(rows=1)
    return ws

def append_unique(row):
    # Recover safely if Google accepted an append but its response was lost.
    if row[0] not in sheet.col_values(1):
        sheet.append_row(row, value_input_option='RAW')

async def deliver(bot):
    global sheet
    while True:
        if sheet is None:
            try:
                sheet = await asyncio.to_thread(connect_sheet)
            except Exception as e:
                logging.warning('Sheets connection failed: %s', type(e).__name__)
        for lead_id, row, synced, notified in store.pending():
            if not synced and sheet is not None:
                try:
                    await asyncio.to_thread(append_unique, row)
                    store.mark(lead_id, 'synced')
                    synced = True
                except Exception as e:
                    logging.warning('Sheets write failed: %s', type(e).__name__)
                    sheet = None
            if not notified:
                labels = ['Заявка', 'Дата', 'Telegram ID', 'Ім’я', 'Username', 'Телефон', 'Зв’язок', 'Категорія', 'Мета', 'ЖК', 'Секція', 'Квартира', 'Оплата', 'Бюджет', 'Профіль', 'Повідомлення', 'Джерело']
                text = '\n'.join(f'{label}: {value}' for label,value in zip(labels, row[:17]) if value)
                text += '\n\nGoogle Таблиця: ' + ('збережено' if synced else 'очікує синхронізації')
                user_url = 'https://t.me/' + row[4] if row[4] else 'tg://user?id=' + row[2]
                try:
                    await bot.send_message(ADMIN, text[:4000], reply_markup=links({'Відкрити контакт':user_url, 'Заявки':'https://docs.google.com/spreadsheets/d/'+SHEET_ID+'/edit'}))
                    store.mark(lead_id, 'notified')
                except Exception as e:
                    logging.warning('Telegram notification failed: %s', type(e).__name__)
        await asyncio.sleep(15)

async def ask(m, data, step, prompt, items=None, contact=False):
    data['step'] = step
    store.put_session(m.from_user.id, data)
    await m.answer(prompt, reply_markup=kb(items or [], contact))

async def contact_step(m, data):
    await ask(m, data, 'contact', 'Як вам зручніше отримати відповідь?', [CHAT, PHONE])

async def review(m, data):
    fields = [('Напрям','category'), ('Мета','purpose'), ('ЖК','project'), ('Секція','section'), ('Квартира','apartment'), ('Оплата','payment'), ('Бюджет','budget'), ('Компанія / профіль','profile'), ('Повідомлення','message'), ('Зв’язок','contact'), ('Телефон','phone')]
    summary = '\n'.join(f'{label}: {data[key]}' for label,key in fields if data.get(key))
    await ask(m, data, 'confirm', 'Перевірте заявку:\n\n'+summary+'\n\nНатискаючи «Надіслати заявку», ви погоджуєтеся на збереження контактів і цього звернення для відповіді на ваш запит.', [SEND])

@dp.message(CommandStart())
async def start(m: Message):
    if m.chat.type != 'private' or m.from_user is None:
        return
    source = (m.text.split(maxsplit=1)[1][:64] if len(m.text.split(maxsplit=1)) > 1 else 'direct')
    store.put_session(m.from_user.id, {'step':'menu','source':source})
    await m.answer('Привіт! Я Georgii Krass.\n\nЖиву та працюю в Одесі, створюю контент і допомагаю підібрати квартиру в GOLDEN CITY.\n\nТут можна залишити запит на консультацію або запропонувати співпрацю. Оберіть розділ 👇', reply_markup=kb(MENU))

@dp.message()
async def handle(m: Message):
    if m.chat.type != 'private' or m.from_user is None:
        return
    uid = m.from_user.id
    t = m.text or ''
    data = store.session(uid)
    step = data.get('step','menu')
    if t == '/myid':
        await m.answer(str(uid))
        return
    if t in MENU or t in (BACK, '/cancel'):
        data = {'step':'menu','source':data.get('source','direct'), 'name':m.from_user.full_name, 'username':m.from_user.username or '', 'form_id':str(uuid.uuid4())}
        store.put_session(uid, data)
        if t == MENU[0]:
            data['category'] = 'Нерухомість'
            await ask(m,data,'project','Оберіть комплекс:',PROJECTS)
        elif t == MENU[1]:
            await ask(m,data,'category','Оберіть формат співпраці:',CATEGORIES)
        elif t == MENU[2]:
            text = 'Я Georgii Krass. Живу в Одесі та ЖК GOLDEN CITY.\n\nСтворюю короткі відео про життя, місто й нерухомість. Проводжу практичні воркшопи зі зйомки контенту для компаній і студентів.\n\nДопоможу з підбором квартири або обговорю вашу ідею співпраці.'
            photo = os.getenv('ABOUT_PHOTO','')
            if photo:
                try:
                    await m.answer_photo(photo, caption=text)
                except Exception:
                    await m.answer(text)
            else:
                await m.answer(text)
            await m.answer('Оберіть наступний крок:',reply_markup=kb([MENU[0],MENU[1],MENU[4]]))
        elif t == MENU[3]:
            await m.answer('Мої соцмережі та особистий контакт:',reply_markup=links(SOCIALS))
        elif t == MENU[4]:
            data['category'] = 'Загальне звернення'
            await ask(m,data,'message','Напишіть ваше питання або пропозицію (до 1500 символів).')
        elif t == MENU[5]:
            rows = store.mine(uid)
            statuses = {}
            if sheet is not None:
                try:
                    values = await asyncio.to_thread(sheet.get_all_values)
                    statuses = {r[0]:r[17] for r in values[1:] if len(r)>17}
                except Exception:
                    pass
            text = '\n\n'.join(f'{r[1]} · {r[7]}\nID: {r[0]}\nСтатус: {statuses.get(r[0], "Прийнята ботом; статус у таблиці зараз недоступний")}' for r in rows)
            await m.answer(text or 'Ви ще не надсилали заявок.',reply_markup=kb(MENU))
        else:
            await m.answer('Головне меню:',reply_markup=kb(MENU))
        return
    if step == 'project' and t in PROJECTS:
        data['project'] = t
        if t == PROJECTS[0]:
            await ask(m,data,'section','Оберіть секцію або залиште вибір мені:',SECTIONS)
        else:
            await card(m,data)
    elif step == 'section' and t in SECTIONS:
        data['section'] = t
        await card(m,data)
    elif step == 'action' and t in ACTIONS:
        data['purpose'] = t
        if t == ACTIONS[2]:
            await ask(m,data,'message','Яке питання хочете обговорити? Можете вказати бажаний час зустрічі.',[SKIP])
        else:
            apartments = ['Квартира-студія','1-кімнатна','2-кімнатна']
            if data['project'] == PROJECTS[0]:
                apartments.append('3-кімнатна')
            await ask(m,data,'apartment','Яка квартира вас цікавить?',apartments+['Допоможіть обрати'])
    elif step == 'apartment' and t in ['Квартира-студія','1-кімнатна','2-кімнатна','Допоможіть обрати'] + (['3-кімнатна'] if data.get('project')==PROJECTS[0] else []):
        data['apartment'] = t
        await ask(m,data,'payment','Який спосіб оплати розглядаєте?',PAYMENTS)
    elif step == 'payment' and t in PAYMENTS:
        data['payment'] = t
        await ask(m,data,'budget','Який бюджет розглядаєте? Вкажіть суму та валюту або пропустіть.',[SKIP])
    elif step == 'budget' and t and len(t)<=200:
        data['budget'] = '' if t==SKIP else t
        await ask(m,data,'message','Додайте побажання або запитання:',[SKIP])
    elif step == 'category' and t in CATEGORIES:
        data['category'] = t
        await ask(m,data,'profile','Напишіть назву компанії або посилання на ваш профіль.',[SKIP])
    elif step == 'profile' and t and len(t)<=500:
        data['profile'] = '' if t==SKIP else t
        prompt = 'Розкажіть про воркшоп: для кого, місто, кількість учасників і бажана дата.' if data['category']=='Воркшопи' else 'Коротко опишіть вашу ідею співпраці.'
        await ask(m,data,'message',prompt)
    elif step == 'message' and t and len(t)<=1500:
        if t == SKIP and data['category'] not in ('Нерухомість',):
            await m.answer('Будь ласка, опишіть ваше звернення.')
            return
        data['message'] = '' if t==SKIP else t
        await contact_step(m,data)
    elif step == 'contact' and t in [CHAT,PHONE]:
        data['contact'] = t
        if t == CHAT:
            await review(m,data)
        else:
            await ask(m,data,'phone','Поділіться вашим номером кнопкою нижче:',[SHARE],contact=True)
    elif step == 'phone' and m.contact:
        if m.contact.user_id != uid:
            await m.answer('Поділіться саме своїм номером за допомогою кнопки.')
            return
        data['phone'] = m.contact.phone_number
        await review(m,data)
    elif step == 'confirm' and t == SEND:
        lead_id = store.submit(uid,data)
        store.put_session(uid, {'step':'menu','source':data.get('source','direct')})
        await m.answer('✅ Вашу заявку прийнято.\n\nЯ зв’яжуся з вами обраним способом, щоб уточнити деталі. Час консультації узгодимо особисто.\n\nНомер заявки: '+lead_id,reply_markup=kb(MENU))
        await m.answer('За потреби можете написати мені:',reply_markup=links({'Написати Георгію':SOCIALS['Telegram']}))
    else:
        await m.answer('Оберіть запропоновану кнопку або введіть відповідь на останнє запитання. Для виходу: /cancel')

async def card(m,data):
    text = data['project'] + ('\n'+data['section'] if data.get('section') else '') + '\n\nДопоможу обрати квартиру, уточнити актуальну вартість і умови оплати та узгодити особисту консультацію.'
    photo = os.getenv('GOLDEN_567_PHOTO' if data['project']==PROJECTS[0] else 'GOLDEN_PALIIA_PHOTO','')
    if photo:
        try:
            await m.answer_photo(photo, caption=text)
        except Exception:
            await m.answer(text)
    else:
        await m.answer(text)
    await ask(m,data,'action','Що вас цікавить?',ACTIONS)

async def main():
    global store
    logging.basicConfig(level=logging.INFO)
    logging.getLogger('aiogram.event').setLevel(logging.WARNING)
    token = os.environ['BOT_TOKEN']
    json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON'])
    folder = Path(os.getenv('DATA_DIR', os.getenv('RAILWAY_VOLUME_MOUNT_PATH','./data')))
    folder.mkdir(parents=True,exist_ok=True)
    store = Store(folder/'bot.sqlite3')
    bot = Bot(token)
    await bot.delete_webhook(drop_pending_updates=False)
    worker = asyncio.create_task(deliver(bot))
    try:
        await dp.start_polling(bot,handle_as_tasks=False,close_bot_session=False)
    finally:
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
        await bot.session.close()

if __name__ == '__main__':
    asyncio.run(main())
