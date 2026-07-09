import asyncio
import os
import json
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import feedparser
import gspread
from google.oauth2.service_account import Credentials
from openai import OpenAI

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

from digest_engine import generate_personal_digest


# =========================
# НАСТРОЙКИ ЧЕРЕЗ ПЕРЕМЕННЫЕ
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
MORNING_CHAT_ID = os.getenv("MORNING_CHAT_ID")

TABLE_NAME = os.getenv("TABLE_NAME", "Ассистент Маруфа")

# Время Душанбе: UTC+5
TJ_TZ = timezone(timedelta(hours=5))

# Во сколько присылать утренний отчёт
MORNING_HOUR = int(os.getenv("MORNING_HOUR", "8"))
MORNING_MINUTE = int(os.getenv("MORNING_MINUTE", "30"))

# Модель для мотивационной речи
MOTIVATION_MODEL = os.getenv("MOTIVATION_MODEL", "gpt-4o-mini")

AI_RSS_FEEDS = [
    "https://openai.com/news/rss.xml",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://venturebeat.com/category/ai/feed/",
    "https://www.artificialintelligence-news.com/feed/",
]

DAY_CARDS = [
    "Сегодня не туши все пожары сам. Найди один повторяющийся пожар и сделай правило.",
    "Один хороший чек-лист сегодня сэкономит один конфликт завтра. Скучно, зато работает.",
    "Выбери одну задачу, которая двигает систему, а не просто создаёт видимость занятости.",
    "Проверь слабое место: где заказ может застрять между распилом, кромкой и присадкой.",
    "Сегодня разговаривай цифрами: срок, сумма, количество, ошибка. Мнения оставим для семейных застолий.",
    "Не улучшай всё сразу. Улучши один процесс на 1%, чтобы завтра не начинать опять с нуля.",
]

FOCUS_LIST = [
    "Порядок в задачах и контроль передачи между людьми.",
    "Меньше ручного управления, больше понятных правил.",
    "Деньги, сроки, качество. Остальное красиво шумит на фоне.",
    "Найти одну ошибку в процессе до того, как её найдёт клиент.",
]


if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения.")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY не найден в переменных окружения.")

if not GOOGLE_CREDENTIALS:
    raise ValueError("GOOGLE_CREDENTIALS не найден в переменных окружения.")

if not MORNING_CHAT_ID:
    raise ValueError("MORNING_CHAT_ID не найден в переменных окружения.")

MORNING_CHAT_ID = int(MORNING_CHAT_ID)

openai_client = OpenAI(api_key=OPENAI_API_KEY)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds_dict = json.loads(GOOGLE_CREDENTIALS)

creds = Credentials.from_service_account_info(
    creds_dict,
    scopes=SCOPES
)

client = gspread.authorize(creds)
sheet = client.open(TABLE_NAME).sheet1

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

user_data = {}


# =========================
# КЛАВИАТУРА
# =========================

keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📝 Мысль"), KeyboardButton(text="✅ Задача")],
        [KeyboardButton(text="💡 Идея"), KeyboardButton(text="⚠️ Проблема")],
        [KeyboardButton(text="🎙 Голосовая заметка")],
        [KeyboardButton(text="📂 Открытые записи"), KeyboardButton(text="📋 Последние записи")],
        [KeyboardButton(text="🌅 Утренние задачи")],
        [KeyboardButton(text="✅ Закрыть запись"), KeyboardButton(text="❌ Отмена")]
    ],
    resize_keyboard=True
)


# =========================
# GOOGLE SHEETS
# =========================

def add_record(record_type, text):
    new_id = len(sheet.get_all_values())

    sheet.append_row([
        new_id,
        datetime.now(TJ_TZ).strftime("%d.%m.%Y %H:%M"),
        record_type,
        text,
        "Открыто"
    ])

    return new_id


def get_rows():
    headers = sheet.row_values(1)
    values = sheet.get_all_values()[1:]
    rows = []

    for row in values:
        item = {}
        for i, header in enumerate(headers):
            item[header] = row[i] if i < len(row) else ""
        rows.append(item)

    return rows


def close_record_by_id(record_id):
    values = sheet.get_all_values()

    for index, row in enumerate(values[1:], start=2):
        if len(row) > 0 and row[0] == str(record_id):
            sheet.update_cell(index, 5, "Закрыто")
            return True

    return False


def format_record(row):
    return (
        f"ID: {row.get('ID', '')}\n"
        f"{row.get('Дата', '')}\n"
        f"Тип: {row.get('Тип', '')}\n"
        f"Текст: {row.get('Текст', '')}\n"
        f"Статус: {row.get('Статус', '')}\n\n"
    )


def get_open_tasks():
    rows = get_rows()

    tasks = [
        row for row in rows
        if row.get("Тип", "").strip().lower() == "задача"
        and row.get("Статус", "").strip().lower() == "открыто"
    ]

    return tasks


def format_open_tasks():
    tasks = get_open_tasks()

    if not tasks:
        return "✅ Открытых задач нет."

    answer = "✅ Открытые задачи:\n\n"

    for task in tasks[:8]:
        answer += (
            f"ID: {task.get('ID', '')}\n"
            f"• {task.get('Текст', '')}\n\n"
        )

    if len(tasks) > 8:
        answer += f"Ещё открытых задач: {len(tasks) - 8}\n"

    return answer.strip()


# =========================
# ПОГОДА
# =========================

def weather_emoji(description):
    desc = description.lower()

    if "sunny" in desc or "clear" in desc:
        return "☀️"
    if "cloud" in desc or "overcast" in desc:
        return "☁️"
    if "rain" in desc or "drizzle" in desc or "shower" in desc:
        return "🌧"
    if "snow" in desc:
        return "❄️"
    if "thunder" in desc:
        return "⛈"
    if "mist" in desc or "fog" in desc:
        return "🌫"

    return "🌤"


def translate_weather(description):
    desc = description.lower()

    if "sunny" in desc:
        return "солнечно"
    if "clear" in desc:
        return "ясно"
    if "partly cloudy" in desc:
        return "переменная облачность"
    if "cloudy" in desc:
        return "облачно"
    if "overcast" in desc:
        return "пасмурно"
    if "rain" in desc:
        return "дождь"
    if "drizzle" in desc:
        return "морось"
    if "shower" in desc:
        return "ливень"
    if "snow" in desc:
        return "снег"
    if "thunder" in desc:
        return "гроза"
    if "mist" in desc:
        return "дымка"
    if "fog" in desc:
        return "туман"

    return description


def get_weather_for_city(city_name, city_label):
    try:
        url = f"https://wttr.in/{city_name}?format=j1"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        current = data["current_condition"][0]
        today = data["weather"][0]
        tomorrow = data["weather"][1]

        current_desc = current["weatherDesc"][0]["value"]
        today_hourly = today["hourly"][4] if len(today["hourly"]) > 4 else today["hourly"][0]
        tomorrow_hourly = tomorrow["hourly"][4] if len(tomorrow["hourly"]) > 4 else tomorrow["hourly"][0]

        today_desc = today_hourly["weatherDesc"][0]["value"]
        tomorrow_desc = tomorrow_hourly["weatherDesc"][0]["value"]

        current_text = translate_weather(current_desc)
        today_text = translate_weather(today_desc)
        tomorrow_text = translate_weather(tomorrow_desc)

        current_icon = weather_emoji(current_desc)
        tomorrow_icon = weather_emoji(tomorrow_desc)

        return (
            f"{city_label}:\n"
            f"{current_icon} Сейчас: {current.get('temp_C', '?')}°C, ощущается как {current.get('FeelsLikeC', '?')}°C, {current_text}\n"
            f"📌 Сегодня: {today.get('mintempC', '?')}…{today.get('maxtempC', '?')}°C, {today_text}\n"
            f"{tomorrow_icon} Завтра: {tomorrow.get('mintempC', '?')}…{tomorrow.get('maxtempC', '?')}°C, {tomorrow_text}\n"
        )

    except Exception as e:
        return (
            f"{city_label}:\n"
            f"⚠️ Не смог получить погоду. Ошибка: {e}\n"
        )


def format_weather_block():
    dushanbe = get_weather_for_city("Dushanbe", "Душанбе")
    khujand = get_weather_for_city("Khujand", "Худжанд")

    return (
        "🌤 Погода сегодня и завтра:\n\n"
        f"{dushanbe}\n"
        f"{khujand}"
    )


# =========================
# НОВОСТИ ИИ
# =========================

def clean_text(text):
    return " ".join(str(text or "").replace("\n", " ").split())


def get_ai_news(limit=3):
    items = []
    seen = set()

    for feed_url in AI_RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            source = clean_text(feed.feed.get("title", "AI news"))

            for entry in feed.entries[:8]:
                title = clean_text(entry.get("title", ""))
                link = clean_text(entry.get("link", ""))
                summary = clean_text(entry.get("summary", ""))[:350]

                if not title:
                    continue

                key = title.lower()
                if key in seen:
                    continue

                seen.add(key)
                items.append({
                    "title": title,
                    "link": link,
                    "source": source,
                    "summary": summary,
                })
        except Exception:
            continue

    hot_words = [
        "openai", "chatgpt", "gpt", "claude", "anthropic",
        "google", "gemini", "agent", "agents", "video", "image",
        "runway", "midjourney", "sora", "elevenlabs", "codex"
    ]

    def score(item):
        title = item["title"].lower()
        return sum(2 for word in hot_words if word in title)

    items.sort(key=score, reverse=True)
    return items[:limit]


def format_ai_news_fallback(news):
    if not news:
        return (
            "🤖 ИИ за ночь:\n\n"
            "Новости ИИ не загрузились. Возможно, интернет решил, что человечество уже достаточно напугало себя нейросетями.\n"
        )

    answer = "🤖 ИИ за ночь:\n\n"

    for i, item in enumerate(news, start=1):
        answer += (
            f"{i}. {item['title']}\n"
            f"Почему важно: это показывает, куда движутся инструменты, автоматизация и работа с файлами.\n"
            f"Что сделать тебе: подумать, можно ли применить это для Чинор, контента или личного ассистента.\n"
            f"Источник: {item['source']}\n\n"
        )

    return answer.strip()


def format_focus_block():
    return f"🎯 Фокус дня:\n\n{random.choice(FOCUS_LIST)}\n"


def format_day_card_block():
    return f"🎲 Карточка дня:\n\n{random.choice(DAY_CARDS)}\n"


# =========================
# МОТИВАЦИЯ
# =========================

def generate_motivation():
    today = datetime.now(TJ_TZ).strftime("%d.%m.%Y")

    prompt = f"""
Напиши короткую утреннюю мотивационную речь для Маруфа на русском языке.

Контекст:
- Маруф строит мебельное производство «Чинор».
- У него есть шоурум, цех, операторы распила, кромки, присадки.
- Его цель — построить систему, порядок, ответственность и стабильный бизнес.
- Стиль: по-мужски, спокойно, без пафоса, без банальных цитат.
- 5–7 строк.
- Каждый день формулируй по-новому.
- Дата сегодня: {today}.
- Не используй длинные вступления.
- Не пиши “дорогой Маруф”.
"""

    try:
        response = openai_client.chat.completions.create(
            model=MOTIVATION_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "Ты пишешь короткие, сильные утренние речи для предпринимателя. Без воды, без пафоса."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.9,
            max_tokens=220
        )

        text = response.choices[0].message.content.strip()
        return f"🔥 Речь дня:\n\n{text}"

    except Exception as e:
        return (
            "🔥 Речь дня:\n\n"
            "Сегодня не жди идеального настроения. Начни с одной ясной задачи, наведи порядок в одном месте, закрой один хвост. "
            "Система строится не вдохновением, а повторением.\n\n"
            f"⚠️ Мотивацию от ИИ не удалось получить: {e}"
        )


# =========================
# УТРЕННИЙ ОТЧЁТ
# =========================

def format_morning_report():
    today = datetime.now(TJ_TZ).strftime("%d.%m.%Y")

    weather_block = format_weather_block()
    tasks_block = format_open_tasks()
    news = get_ai_news(3)

    return generate_personal_digest(
        openai_client=openai_client,
        model=MOTIVATION_MODEL,
        today=today,
        weather_block=weather_block,
        tasks_block=tasks_block,
        news=news,
    )


# Старое имя функции оставляем, чтобы кнопка и команда работали без сюрпризов
def format_morning_tasks():
    return format_morning_report()


# =========================
# ГОЛОС
# =========================

def transcribe_audio(file_path):
    with open(file_path, "rb") as audio_file:
        transcription = openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="ru"
        )

    return transcription.text


# =========================
# УТРЕННИЙ ПЛАНИРОВЩИК
# =========================

async def morning_scheduler():
    last_sent_date = None

    while True:
        now = datetime.now(TJ_TZ)
        today = now.strftime("%Y-%m-%d")

        if (
            now.hour == MORNING_HOUR
            and now.minute == MORNING_MINUTE
            and last_sent_date != today
        ):
            try:
                await bot.send_message(
                    chat_id=MORNING_CHAT_ID,
                    text=format_morning_report(),
                    reply_markup=keyboard
                )
                last_sent_date = today
                print(f"Утренний отчёт отправлен: {today}")
            except Exception as e:
                print(f"Ошибка отправки утреннего отчёта: {e}")

        await asyncio.sleep(30)


# =========================
# КОМАНДЫ
# =========================

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "Личный ассистент Маруфа запущен.\n\n"
        "Можно писать текстом или отправлять голосовые сообщения.",
        reply_markup=keyboard
    )


@dp.message(Command("myid"))
async def myid(message: types.Message):
    await message.answer(
        f"Ваш Telegram ID:\n\n{message.from_user.id}",
        reply_markup=keyboard
    )


@dp.message(Command("morning"))
async def morning_command(message: types.Message):
    await message.answer(
        format_morning_report(),
        reply_markup=keyboard
    )


# =========================
# ГОЛОСОВЫЕ СООБЩЕНИЯ
# =========================

@dp.message(F.voice)
async def handle_voice(message: types.Message):
    user_id = message.from_user.id

    await message.answer("🎙 Принял голосовое. Сейчас расшифрую...")

    voice = message.voice
    file = await bot.get_file(voice.file_id)

    voices_dir = Path("voices")
    voices_dir.mkdir(exist_ok=True)

    file_path = voices_dir / f"voice_{user_id}_{message.message_id}.ogg"

    with open(file_path, "wb") as f:
        await bot.download_file(file.file_path, destination=f)

    try:
        text = transcribe_audio(file_path)

        if not text.strip():
            await message.answer("Не смог разобрать голосовое.", reply_markup=keyboard)
            return

        record_type = user_data.get(user_id, "Голос")
        new_id = add_record(record_type, text)

        await message.answer(
            f"✅ Голос записан\n\n"
            f"ID: {new_id}\n"
            f"Тип: {record_type}\n"
            f"Текст: {text}",
            reply_markup=keyboard
        )

        if user_id in user_data:
            del user_data[user_id]

    except Exception as e:
        await message.answer(
            "Ошибка при распознавании голосового.\n\n"
            f"{e}",
            reply_markup=keyboard
        )

    finally:
        try:
            file_path.unlink()
        except Exception:
            pass


# =========================
# ТЕКСТОВЫЕ СООБЩЕНИЯ
# =========================

@dp.message(F.text)
async def handle_text(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()
    text_lower = text.lower()

    if text == "❌ Отмена" or text_lower in ["отмена", "отменить"]:
        if user_id in user_data:
            del user_data[user_id]

        await message.answer("Отменил.", reply_markup=keyboard)
        return

    if text in ["📝 Мысль", "✅ Задача", "💡 Идея", "⚠️ Проблема"]:
        type_map = {
            "📝 Мысль": "Мысль",
            "✅ Задача": "Задача",
            "💡 Идея": "Идея",
            "⚠️ Проблема": "Проблема"
        }

        user_data[user_id] = type_map[text]

        await message.answer(
            f"Напишите текст или отправьте голос для записи: {type_map[text]}",
            reply_markup=keyboard
        )
        return

    if text == "🎙 Голосовая заметка":
        user_data[user_id] = "Голос"
        await message.answer("Отправьте голосовое сообщение.", reply_markup=keyboard)
        return

    if text == "🌅 Утренние задачи":
        await message.answer(
            format_morning_report(),
            reply_markup=keyboard
        )
        return

    if text in ["📋 Последние записи", "📋 Показать записи"]:
        rows = get_rows()

        if not rows:
            await message.answer("Пока записей нет.", reply_markup=keyboard)
            return

        answer = "📋 Последние записи:\n\n"

        for row in rows[-10:]:
            answer += format_record(row)

        await message.answer(answer, reply_markup=keyboard)
        return

    if text == "📂 Открытые записи":
        rows = get_rows()
        open_rows = [
            row for row in rows
            if row.get("Статус", "").strip().lower() == "открыто"
        ]

        if not open_rows:
            await message.answer(
                "Открытых записей нет. Подозрительно организованная жизнь.",
                reply_markup=keyboard
            )
            return

        answer = "📂 Открытые записи:\n\n"

        for row in open_rows[-15:]:
            answer += format_record(row)

        await message.answer(answer, reply_markup=keyboard)
        return

    close_commands = [
        "✅ закрыть запись",
        "закрыть",
        "закрыть запись",
        "закрыть мысль",
        "закрыть задачу",
        "закрыть идею",
        "закрыть проблему"
    ]

    if text_lower in close_commands:
        user_data[user_id] = "Закрыть"
        await message.answer("Введите ID записи, которую нужно закрыть:", reply_markup=keyboard)
        return

    if user_data.get(user_id) == "Закрыть":
        if not text.isdigit():
            await message.answer(
                "ID должен быть числом. Например: 2\n\n"
                "Чтобы отменить, нажмите ❌ Отмена.",
                reply_markup=keyboard
            )
            return

        success = close_record_by_id(text)

        if success:
            await message.answer(
                f"✅ Запись ID {text} закрыта.",
                reply_markup=keyboard
            )
        else:
            await message.answer(
                "Такой ID не найден.",
                reply_markup=keyboard
            )

        del user_data[user_id]
        return

    record_type = user_data.get(user_id, "Мысль")
    new_id = add_record(record_type, text)

    await message.answer(
        f"✅ Записал\n\n"
        f"ID: {new_id}\n"
        f"Тип: {record_type}\n"
        f"Текст: {text}",
        reply_markup=keyboard
    )

    if user_id in user_data:
        del user_data[user_id]


# =========================
# ЗАПУСК
# =========================

async def main():
    print("Личный бот запущен")
    asyncio.create_task(morning_scheduler())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
