# .env и Docker: почему нет данных

## Что проверить

### 1. После любого изменения `.env` перезапусти контейнеры

Переменные подхватываются только при старте контейнера:

```bash
docker compose up -d --build
# или точечно:
docker compose restart backend celery_beat celery_betsapi_worker celery_betsapi_worker_2
```

### 2. Критичные переменные для матчей (линия, лайв, результаты)

| Переменная | Назначение |
|------------|------------|
| `BETSAPI_TOKEN` | Токен BetsAPI. Без него линия и лайв не загружаются. |
| `ENABLE_SCHEDULED_COLLECTORS` | Должно быть `true`, иначе Celery Beat не ставит в расписание задачи линии/лайва. |

В `docker-compose.yml` они явно пробрасываются в backend и воркеры BetsAPI/Beat.

### 3. Доступ к сайту по IP (192.168.31.130)

- В `.env` задан `FRONTEND_URL=http://192.168.31.130:11000`.
- В `CORS_EXTRA_ORIGINS` должен быть тот же origin, с которого открываете сайт (например `http://192.168.31.130:11000`), иначе бэкенд может отклонить запросы при прямом обращении.

Запросы с фронта идут на тот же хост (`/api/v1/...`), Next.js проксирует их на backend, поэтому при открытии по IP главное — чтобы в CORS был этот origin, если что-то пойдёт напрямую на бэкенд.

### 4. Проверка, что контейнер видит переменные

```bash
# Backend
docker compose run --rm backend env | grep -E "BETSAPI_TOKEN|ENABLE_SCHEDULED|DATABASE_URL"

# Воркер BetsAPI
docker compose run --rm celery_betsapi_worker env | grep -E "BETSAPI_TOKEN|ENABLE_SCHEDULED"
```

`BETSAPI_TOKEN` не должен быть пустым; `ENABLE_SCHEDULED_COLLECTORS` должно быть `true`.

### 5. Логи

- **Beat (расписание):**  
  `docker compose logs celery_beat --tail 30`  
  Должно быть сообщение о том, что line/live запланированы, а не предупреждение про отключённые коллекторы.

- **Воркер BetsAPI (линия):**  
  `docker compose logs celery_betsapi_worker --tail 80`  
  Ищи строки `BetsAPI fetch started mode=line` и отсутствие `BETSAPI_TOKEN не задан` / `BetsAPI line: BETSAPI_TOKEN не задан`.

## Итог

- В `.env`: `BETSAPI_TOKEN` задан, `ENABLE_SCHEDULED_COLLECTORS=true`, в `CORS_EXTRA_ORIGINS` есть адрес, с которого открываете сайт.
- После правок `.env`: перезапуск backend, celery_beat и celery_betsapi_worker (и при необходимости полный `docker compose up -d`).

После этого подожди 1–2 минуты (цикл линии по расписанию), затем обнови страницу «Линия» и при необходимости проверь логи по пункту 5.
