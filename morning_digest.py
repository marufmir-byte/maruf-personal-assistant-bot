import os
import random
from datetime import datetime
from zoneinfo import ZoneInfo
from html import escape

import feedparser
import requests

TZ = os.getenv("TZ", "Asia/Dushanbe")
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")

WEATHER_CITIES = [
    ("Душанбе", "Dushanbe"),
    ("Худжанд", "Khujand"),
]

AI_RSS_FEEDS = [
    "https://openai.com/news/rss.xml",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://venturebeat.com/category/ai/feed/",
    "https://www.artificialintelligence-news.com/feed/",
]

DAY_CARDS = [
    "Сегодня не туши все пожары сам. Найди один повторяющийся пожар и сделай правило.",
    "Один хороший чек-лист сегодня сэкономит один конфликт завтра. Скучно, зато работает, как и вся взрослая жизнь.",
    "Выбери одну задачу, которая двигает систему, а не просто создаёт видимость героического страдания.",
    "Проверь слабое место: где заказ может застрять между распилом, кромкой и присадкой.",
    "Сегодня разговаривай цифрами: срок, сумма, количество, ошибка. Мнения оставим для семейных застолий.",
    "Не улучшай всё сразу. Улучши один процесс на 1%, чтобы завтра не начинать опять с нуля.",
]

FOCUS_LIST = [
    "Главный фокус: порядок в задачах и контроль передачи между людьми.",
    "Главный фокус: меньше ручного управления, больше понятных правил.",
    "Главный фокус: деньги, сроки, качество. Остальное красиво шумит на фоне.",
    "Главный фокус: найти одну ошибку в процессе до того, как её найдёт клиент.",
]


def get_weather(city_query: str) -> dict | None:
    try:
        url = f"https://wttr.in/{city_query}?format=j1&lang=ru"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        current = data["current_condition"][0]
        today = data["weather"][0]
        tomorrow = data["weather"][1] if len(data.get("weather", [])) > 1 else None
        return {
            "temp": current.get("temp_C"),
            "feels": current.get("FeelsLikeC"),
            "desc": current.get("lang_ru", [{}])[0].get("value") or current.get("weatherDesc", [{}])[0].get("value"),
            "today_min": today.get("mintempC"),
            "today_max": today.get("maxtempC"),
            "tomorrow_min": tomorrow.get("mintempC") if tomorrow else None,
            "tomorrow_max": tomorrow.get("maxtempC") if tomorrow else None,
        }
    except Exception:
        return None


def get_ai_news(limit: int = 3) -> list[dict]:
    items: list[dict] = []
    seen_titles: set[str] = set()

    for feed_url in AI_RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            source = feed.feed.get("title", "AI news")
            for entry in feed.entries[:8]:
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()
                summary = (entry.get("summary") or entry.get("description") or "").strip()
                key = title.lower()
                if not title or key in seen_titles:
                    continue
                seen_titles.add(key)
                items.append({"title": title, "link": link, "source": source, "summary": summary})
        except Exception:
            continue

    scored = []
    hot_words = ["openai", "chatgpt", "claude", "google", "gemini", "anthropic", "agent", "video", "image", "robot", "ai"]
    for item in items:
        title_lower = item["title"].lower()
        score = sum(1 for word in hot_words if word in title_lower)
        scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:limit]]


def build_weather_block() -> str:
    lines = ["☀️ <b>Погода сегодня и завтра</b>", ""]
    for city_name, city_query in WEATHER_CITIES:
        weather = get_weather(city_query)
        lines.append(f"<b>{city_name}:</b>")
        if not weather:
            lines.append("Не удалось получить погоду. Интернет, видимо, тоже решил начать день с саботажа.")
            lines.append("")
            continue
        lines.append(f"🌡 Сейчас: {weather['temp']}°C, ощущается как {weather['feels']}°C, {escape(str(weather['desc']).lower())}")
        lines.append(f"📌 Сегодня: {weather['today_min']}...{weather['today_max']}°C")
        if weather.get("tomorrow_min") is not None:
            lines.append(f"☀️ Завтра: {weather['tomorrow_min']}...{weather['tomorrow_max']}°C")
        lines.append("")
    return "\n".join(lines).strip()


def build_ai_news_block() -> str:
    news = get_ai_news(3)
    lines = ["🤖 <b>ИИ за ночь</b>", ""]
    if not news:
        lines.append("Новости ИИ не загрузились. Возможно, человечество на минуту перестало объявлять революцию каждые 6 часов.")
        return "\n".join(lines)

    for index, item in enumerate(news, start=1):
        title = escape(item["title"])
        source = escape(item["source"])
        link = escape(item["link"])
        lines.append(f"{index}. <b>{title}</b>")
        lines.append(f"Источник: {source}")
        if link:
            lines.append(f"🔗 {link}")
        lines.append("")

    lines.append("🛠 <b>Что проверить тебе:</b>")
    lines.append("Есть ли среди новостей инструмент для видео, изображений, автоматизации или контента. Если есть, тестировать 20 минут, не жениться на сервисе сразу.")
    return "\n".join(lines).strip()


def build_message() -> str:
    now = datetime.now(ZoneInfo(TZ))
    date_text = now.strftime("%d.%m.%Y")

    parts = [
        f"🌅 <b>Доброе утро, Маруф.</b>\n\nСегодня {date_text}.",
        build_weather_block(),
        build_ai_news_block(),
        f"🎯 <b>Фокус дня</b>\n\n{random.choice(FOCUS_LIST)}",
        f"🎲 <b>Карточка дня</b>\n\n{random.choice(DAY_CARDS)}",
        "🏭 <b>Мысль для Чинор</b>\n\nТы не просто производишь мебель. Ты строишь систему, где заказ проходит путь без крика, угадывания и героического хаоса. Удивительно, но цивилизация иногда начинается с таблицы.",
    ]
    return "\n\n".join(parts)


def send_telegram_message(text: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("Не заданы BOT_TOKEN/TELEGRAM_BOT_TOKEN или CHAT_ID/TELEGRAM_CHAT_ID")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    response = requests.post(url, json=payload, timeout=20)
    response.raise_for_status()


def main() -> None:
    message = build_message()
    send_telegram_message(message)


if __name__ == "__main__":
    main()
