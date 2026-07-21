# Схема автоматизации

```mermaid
flowchart TD
    A[Google Sheets: таблица эталонных блогеров] --> B[Шаг 1. Чтение ссылок на профили]
    B --> C[Шаг 2. Сбор данных по профилям<br/>посты, подписи, метрики, визуал]
    C --> D[Шаг 3. Claude API: portrait_prompt.txt<br/>Портрет идеального блогера]
    D --> E[Шаг 4а. Поиск кандидатов<br/>influencer API / Apify-скрапинг]
    E --> F[Шаг 4б. Claude API: search_prompt.txt<br/>Скоринг каждого кандидата]
    F -->|match_score выше 70| G[Шаг 5. Claude API: offer_prompt.txt<br/>Генерация персонального оффера]
    F -->|match_score ниже 70| X[Исключён из шорт-листа]
    G --> H[output/result.md<br/>Портрет + шорт-лист + офферы]

    style A fill:#e8f0fe
    style D fill:#fef3e0
    style F fill:#fef3e0
    style G fill:#fef3e0
    style H fill:#e6f4ea
```

**Ручные точки в текущей версии** (см. `README.md`, раздел "Ограничения"):
- Шаг 2 требует подключения источника данных (Apify actor или ручной сбор в CSV)
- Шаг 4а требует подключения платного API инфлюенс-платформы или скрапера

Всё остальное — Шаги 3, 4б, 5 — выполняется автоматически через Claude API без участия человека.
