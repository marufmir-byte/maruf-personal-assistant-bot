BANNED_PHRASES = [
    "отличный день",
    "давайте",
    "удачного дня",
    "вперёд к цели",
    "вперед к цели",
    "ты сможешь",
    "не сдавайся",
    "продуктивного дня",
    "сделаем его продуктивным",
]


def clean_banned_phrases(text):
    cleaned = text

    for phrase in BANNED_PHRASES:
        cleaned = cleaned.replace(phrase, "")
        cleaned = cleaned.replace(phrase.capitalize(), "")

    return cleaned.strip()


def build_news_block(news):
    if not news:
        return "Сегодня нет проверенной новости, которую стоит добавлять в отчёт."

    item = news[0]

    title = item.get("title", "").strip()
    source = item.get("source", "").strip()
    summary = item.get("summary", "").strip()
    link = item.get("link", "").strip()

    parts = []

    if title:
        parts.append(title)

    if summary:
        parts.append(summary[:300])

    if source:
        parts.append(f"Источник: {source}")

    if link:
        parts.append(f"Ссылка: {link}")

    return "\n".join(parts)


def build_fallback_digest(today, weather_block, tasks_block, news):
    news_block = build_news_block(news)

    return (
        f"🌅 Доброе утро, Маруф\n"
        f"{today}\n\n"
        f"🌤 Погода\n"
        f"{weather_block}\n\n"
        f"✅ Задачи\n"
        f"{tasks_block}\n\n"
        f"🤖 Одна важная новость\n"
        f"{news_block}\n\n"
        f"📌 Главное\n"
        f"Сначала выполни наиболее важную открытую задачу. "
        f"Если открытых задач действительно нет, новых рекомендаций сегодня нет. "
        f"Сосредоточься на текущей работе."
    )[:3900]


def generate_personal_digest(
    openai_client,
    model,
    today,
    weather_block,
    tasks_block,
    news
):
    news_block = build_news_block(news)

    prompt = f"""
Подготовь короткий утренний отчёт для Маруфа на русском языке.

Маруф руководит мебельным производством «Чинор».
Ему нужен не мотивационный текст, а краткая и полезная сводка.

ДАТА:
{today}

ПОГОДА:
{weather_block}

ОТКРЫТЫЕ ЗАДАЧИ:
{tasks_block}

ОДНА НОВОСТЬ:
{news_block}

Составь сообщение строго по структуре:

🌅 Доброе утро, Маруф
Одно короткое предложение о том, на чём сегодня сосредоточиться.

🌤 Погода
Кратко: Душанбе и Худжанд.
Добавь практическое предупреждение только при реальном риске:
сильная жара, дождь, ветер, снег или резкое похолодание.
Не придумывай влияние погоды на материалы и оборудование.

✅ Задачи
Покажи реальные открытые задачи из переданных данных.
Не добавляй задачи от себя.
Если задач нет, напиши:
«В таблице открытых задач нет».

🎯 Главное на сегодня
Выбери одну конкретную открытую задачу из данных.
Если задач нет, напиши:
«Сегодня новых рекомендаций нет. Сосредоточься на текущих задачах».

🤖 Одна важная новость
Укажи:
- что произошло;
- почему это может быть полезно Маруфу;
- источник;
- ссылку.

Если новость не связана с работой Маруфа, честно напиши:
«Сегодня нет новости, которая требует твоего внимания».

Правила:
- Всегда обращайся к Маруфу только на «ты». Никогда не используй «вы», «ваш», «обратите».
- Максимум 1500 символов.
- Не добавляй блоки «инструмент дня», «карточка дня»,
  «мысль дня», «идея для контента» и «идея для Чинор».
- Не предлагай чек-листы, анализ узких мест и улучшение передачи
  заказов, если этого нет в открытых задачах.
- Не повторяй общие советы.
- Не придумывай события, задачи, цифры и выводы.
- Не называй старую новость новой.
- Не пиши три новости. Нужна максимум одна.
- Пиши спокойно, конкретно и без мотивационных лозунгов.
"""

    try:
        response = openai_client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты составляешь краткую фактическую сводку "
                        "для руководителя мебельного производства. "
                        "Не придумывай информацию и не давай общих советов."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.2,
            max_tokens=650,
        )

        text = response.choices[0].message.content.strip()
        return clean_banned_phrases(text[:3900])

    except Exception as error:
        print(f"Ошибка создания утреннего дайджеста: {error}")

        return build_fallback_digest(
            today=today,
            weather_block=weather_block,
            tasks_block=tasks_block,
            news=news,
        )
