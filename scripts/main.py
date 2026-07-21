"""
Blogger Outreach Agent — pipeline для поиска блогеров под бартер.

ЧТО ДЕЛАЕТ:
1. Читает таблицу Google Sheets со ссылками на эталонных блогеров
2. Собирает данные по каждому профилю (см. функцию fetch_profile_data — требует подключения
   реального источника данных, см. комментарии внутри)
3. Отправляет собранные данные в Claude API -> получает "портрет идеального блогера"
4. Ищет кандидатов через выбранный источник (Apify actor / influencer API) и скорит их
   относительно портрета
5. Для кандидатов с высоким match_score генерирует персональный оффер
6. Сохраняет результат в output/result.md

ЗАПУСК:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY="sk-ant-..."
    export GOOGLE_SHEET_CSV_URL="https://docs.google.com/spreadsheets/d/<ID>/export?format=csv&gid=0"
    python main.py

ВАЖНО:
Функция fetch_profile_data() и функция search_candidates() — это единственные два места,
где нужен реальный внешний источник данных (Instagram/YouTube/Telegram не дают официального
публичного API для чтения чужих профилей и поиска "по эстетике"). Ниже — рабочие заглушки
с чёткими точками подключения:
  - для fetch_profile_data: Apify actor (instagram-scraper) или ручной ввод данных в CSV
  - для search_candidates: платный API инфлюенс-платформы (Perfluence/Modash/HypeAuditor)
    или тот же Apify-скрапер по хэштегам/гео
Без реального источника скрипт всё равно работает целиком на CSV-заглушках (см. sample_data/),
чтобы можно было проверить логику pipeline end-to-end.
"""

import os
import csv
import json
import re
import requests

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")


def load_prompt(name: str) -> str:
    with open(os.path.join(PROMPTS_DIR, name), encoding="utf-8") as f:
        return f.read()


def call_claude(system_prompt: str, user_content: str) -> str:
    """Единая обёртка над Anthropic Messages API."""
    resp = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 1500,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_content}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")


# ---------- ШАГ 1: чтение таблицы ----------

def read_sheet(csv_url: str) -> list[str]:
    """Читает Google Sheet, экспортированный как CSV, и достаёт ссылки на профили из колонки B."""
    resp = requests.get(csv_url, timeout=30)
    resp.raise_for_status()
    reader = csv.reader(resp.text.splitlines())
    links = []
    for row in reader:
        if len(row) > 1 and row[1].strip().startswith("http"):
            links.append(row[1].strip())
    return links


# ---------- ШАГ 2: сбор данных по эталонным профилям ----------

def fetch_profile_data(profile_url: str) -> dict:
    """
    ТОЧКА ПОДКЛЮЧЕНИЯ РЕАЛЬНОГО ИСТОЧНИКА.

    Вариант А (рекомендуется для старта): Apify actor "instagram-scraper" —
        https://apify.com/apify/instagram-scraper
        actor возвращает JSON с постами, подписями, лайками, комментариями.

    Вариант Б: платный API инфлюенс-платформы, если у неё есть эндпоинт
        "получить профиль по username".

    Ниже — заглушка, которая возвращает структуру с пустыми полями,
    чтобы pipeline не падал при отсутствии подключённого источника.
    """
    username_match = re.search(r"instagram\.com/([^/?]+)", profile_url)
    username = username_match.group(1) if username_match else profile_url
    return {
        "url": profile_url,
        "username": username,
        "captions": [],       # сюда: список подписей последних постов
        "followers": None,    # сюда: число подписчиков
        "engagement_rate": None,
        "visual_style_notes": "",  # сюда: описание стиля (можно получить через vision-модель по скринам)
    }


# ---------- ШАГ 3: портрет идеального блогера ----------

def build_portrait(profiles: list[dict]) -> str:
    system_prompt = load_prompt("portrait_prompt.txt")
    user_content = "Данные по эталонным блогерам:\n\n" + json.dumps(profiles, ensure_ascii=False, indent=2)
    return call_claude(system_prompt, user_content)


# ---------- ШАГ 4: поиск и скоринг кандидатов ----------

def search_candidates(portrait: str) -> list[dict]:
    """
    ТОЧКА ПОДКЛЮЧЕНИЯ ПОИСКА.
    Вариант А: вызов API инфлюенс-платформы с параметрами из портрета (ниша, размер аудитории).
    Вариант Б: Apify-скрапер по хэштегам/гео из блока "ПОИСКОВЫЕ КРИТЕРИИ" портрета.

    Заглушка ниже читает кандидатов из sample_data/candidates.csv, чтобы pipeline
    можно было проверить целиком без платных доступов.
    """
    candidates_path = os.path.join(os.path.dirname(__file__), "..", "output", "sample_candidates.csv")
    candidates = []
    if os.path.exists(candidates_path):
        with open(candidates_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                candidates.append(row)
    return candidates


def score_candidate(portrait: str, candidate: dict) -> dict:
    system_prompt = load_prompt("search_prompt.txt")
    user_content = f"Портрет идеального блогера:\n{portrait}\n\nКандидат:\n{json.dumps(candidate, ensure_ascii=False)}"
    raw = call_claude(system_prompt, user_content)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"username": candidate.get("username"), "match_score": 0, "recommendation": "exclude", "reasoning": "parse_error", "raw": raw}


# ---------- ШАГ 5: генерация оффера ----------

def generate_offer(brand_description: str, portrait: str, candidate: dict, score: dict) -> str:
    system_prompt = load_prompt("offer_prompt.txt")
    user_content = (
        f"Бренд:\n{brand_description}\n\n"
        f"Портрет идеального блогера:\n{portrait}\n\n"
        f"Кандидат:\n{json.dumps(candidate, ensure_ascii=False)}\n\n"
        f"Совпадения:\n{json.dumps(score.get('matches', []), ensure_ascii=False)}"
    )
    return call_claude(system_prompt, user_content)


# ---------- ГЛАВНЫЙ PIPELINE ----------

def run(brand_description: str = "Бренд одежды/аксессуаров, ищем блогеров для бартер-коллабораций"):
    sheet_url = os.environ["GOOGLE_SHEET_CSV_URL"]

    print("[1/5] Чтение таблицы...")
    links = read_sheet(sheet_url)
    print(f"    Найдено {len(links)} ссылок")

    print("[2/5] Сбор данных по эталонным профилям...")
    profiles = [fetch_profile_data(url) for url in links]

    print("[3/5] Построение портрета идеального блогера...")
    portrait = build_portrait(profiles)

    print("[4/5] Поиск и оценка кандидатов...")
    candidates = search_candidates(portrait)
    scored = [score_candidate(portrait, c) for c in candidates]
    shortlist = [s for s in scored if s.get("recommendation") == "include"]

    print("[5/5] Генерация офферов...")
    results = []
    for cand, score in zip(candidates, scored):
        if score.get("recommendation") == "include":
            offer = generate_offer(brand_description, portrait, cand, score)
            results.append({"candidate": cand, "score": score, "offer": offer})

    out_path = os.path.join(os.path.dirname(__file__), "..", "output", "result.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Портрет идеального блогера\n\n" + portrait + "\n\n---\n\n# Найденные кандидаты и офферы\n\n")
        for r in results:
            f.write(f"## @{r['candidate'].get('username')}\n\n")
            f.write(f"**Match score:** {r['score'].get('match_score')}\n\n")
            f.write(f"**Обоснование:** {r['score'].get('reasoning')}\n\n")
            f.write(f"**Текст оффера:**\n\n{r['offer']}\n\n---\n\n")

    print(f"Готово. Результат: {out_path}")


if __name__ == "__main__":
    run()
