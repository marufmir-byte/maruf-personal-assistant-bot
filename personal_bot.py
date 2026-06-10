import asyncio
import os
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from openai import OpenAI

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


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

# Во сколько присылать утренние задачи
MORNING_HOUR = int(os.getenv("MORNING_HOUR", "8"))
MORNING_MINUTE = int(os.getenv("MORNING_MINUTE", "30"))


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


def format_morning_tasks():
    tasks = get_open_tasks()
    today = datetime.now(TJ_TZ).strftime("%d.%m.%Y")

    if not tasks:
        return (
            f"🌅 Доброе утро, Маруф.\n\n"
            f"Сегодня {today}.\n\n"
            f"Открытых задач нет.\n"
            f"Подозрительно спокойно. Проверь, не забыли ли мы вообще жить. 😄"
        )

    answer = (
        f"🌅 Доброе утро, Маруф.\n\n"
        f"Сегодня {today}.\n\n"
        f"Открытые задачи:\n\n"
    )

    for task in tasks:
        answer += (
            f"ID: {task.get('ID', '')}\n"
            f"✅ {task.get('Текст', '')}\n\n"
        )

    answer += "Чтобы закрыть задачу, нажми ✅ Закрыть запись и введи ID."

    return answer


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
                    text=format_morning_tasks(),
                    reply_markup=keyboard
                )
                last_sent_date = today
                print(f"Утренние задачи отправлены: {today}")
            except Exception as e:
                print(f"Ошибка отправки утренних задач: {e}")

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
        format_morning_tasks(),
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
            format_morning_tasks(),
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