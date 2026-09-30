# Установка и локальный запуск

Нужны Git и Python 3.12+. Проверены Python 3.12 на Ubuntu и 3.14 на Windows. Node.js, Docker, Telegram и отдельный frontend-сервер для обычного локального запуска не нужны.

## Получить проект

Репозиторий приватный; аккаунту GitHub нужен доступ. При необходимости войдите через `gh auth login` или настроенный Git credential helper, не включайте токен в URL.

```bash
git clone https://github.com/CRYCas0n/kitchen-order-control-demo.git
cd kitchen-order-control-demo
git switch main
```

Все дальнейшие команды — из корня клона. Не переносите production `.env` и SQLite в учебную установку без необходимости.

## Linux / macOS

```bash
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
test -e .env || cp .env.example .env
.venv/bin/python -m scripts.seed
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Если в Ubuntu отсутствует модуль venv, установите пакет python3-venv через администратора ОС. Активация venv не обязательна, так как путь к Python указан явно.

## Windows PowerShell

```powershell
python --version
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-lock.txt
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
.venv\Scripts\python -m scripts.seed
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Откройте http://127.0.0.1:8000. FastAPI раздаёт и HTML/CSS/JS, и API. Отдельной команды `npm install/build/start` нет. Ctrl+C останавливает локальный сервер. Изменение `.env` требует перезапуска.

## Environment variables

Файл [`.env.example`](../.env.example) содержит имена без реальных секретов. Настройки читает [Settings.from_env](../app/config.py); переменная процесса имеет приоритет над `.env`.

| Переменная | По умолчанию / назначение |
|---|---|
| DATABASE_PATH | data/app.db; относительный путь считается от корня проекта |
| PUBLIC_BASE_URL | Пусто; публичный HTTPS origin для webhook и ссылки из бота |
| ADMIN_USERNAME | coordinator; имя Basic Auth |
| ADMIN_PASSWORD | Пусто; admin закрыт, пока пароль не настроен |
| TELEGRAM_BOT_TOKEN | Пусто; без него отправка Telegram не работает |
| TELEGRAM_WEBHOOK_SECRET | Пусто; входящий webhook тогда отклоняется |
| COORDINATOR_TELEGRAM_ID | Пусто; без ID и активного пользователя уведомление не ставится в очередь |
| ALLOW_LOCAL_HTTP | false; true разрешает admin по HTTP только для localhost/127.0.0.1/testserver |

Для разработки admin отредактируйте локальный `.env`:

```dotenv
ADMIN_USERNAME=coordinator
ADMIN_PASSWORD=YOUR_LOCAL_ADMIN_PASSWORD
ALLOW_LOCAL_HTTP=true
```

Замените placeholder собственным случайным паролем. Production использует false и HTTPS. Пустой пароль даёт 503 после проверки допустимой схемы URL; запрещённый HTTP даст 403 раньше проверки пароля.

Константы DEMO_DATE и LOW_MARGIN_THRESHOLD не являются environment variables: они задаются в config.py, сейчас 2026-09-30 и 15. Не добавляйте одноимённые строки в `.env` в ожидании изменения расчётов.

## База и seed

При создании приложения схема может быть создана автоматически, но заказы добавляет `scripts.seed`. Повтор команды при существующих заказах пишет `Existing database preserved` и не делает reset. Свежий seed содержит 24 заказа, 6 задач, но не содержит Telegram-пользователей.

Команды отдельного sandbox/reset и безопасного export — [DATABASE.md](DATABASE.md). Не используйте `--reset` для обычного обновления приложения.

## Проверить запуск

В другом терминале Linux/macOS:

```bash
curl -fsS http://127.0.0.1:8000/api/health
curl -fsS http://127.0.0.1:8000/api/dashboard
```

В PowerShell:

```powershell
curl.exe -fsS http://127.0.0.1:8000/api/health
curl.exe -fsS http://127.0.0.1:8000/api/dashboard
```

Health должен иметь status/database=ok. Dashboard — 24 заказа после нового seed. Проверьте открытие карточки, KPI и кнопку обновления. Admin доступен по `/admin`, логин/пароль берутся из вашего `.env`.

## Автоматические тесты

```bash
.venv/bin/python -m unittest discover -s tests -v
```

```powershell
.venv\Scripts\python -m unittest discover -s tests -v
```

Текущий набор — 39 тестов. Каждому интеграционному тесту создаётся временная SQLite; исходящий Telegram transport подменён. HTTP-сервер отдельно запускать не требуется. При импорте app.main также инициализируется схема стандартной локальной БД, но тестовые бизнес-операции выполняются в временных базах.

Браузерные проверки требуют `requirements-dev.txt` и Chrome/Playwright Chromium. Какие scripts работают локально, а какие меняют публичный demo, описано в [TESTING.md](TESTING.md).

## Подключить Telegram, если нужен живой сценарий

1. Создайте отдельного бота через @BotFather и сохраните токен только в `.env`: `TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN`.
2. Создайте собственный случайный webhook secret (например, `python -c "import secrets; print(secrets.token_urlsafe(32))"`) и сохраните приватно. Не коммитьте вывод.
3. Нужен доступный Telegram публичный HTTPS origin. Сам локальный 127.0.0.1 таким адресом не является; проект не создаёт туннель.
4. Задайте PUBLIC_BASE_URL и TELEGRAM_WEBHOOK_SECRET, перезапустите backend. Из окружения, связанного с нужным deployment, выполните `python -m scripts.manage webhook`.
5. Каждый человек открывает `/start`, передаёт администратору ID; тот добавляет роль/назначение. Примеры — [OPERATIONS.md](OPERATIONS.md).
6. Настройте COORDINATOR_TELEGRAM_ID и активную роль coordinator. Применение переменной требует restart.

Не подключайте локальные эксперименты к production-боту: `setWebhook` меняет адрес доставки этого бота. `manage webhook` также устанавливает три команды, allowed_updates message/callback_query, max_connections=4 и не удаляет pending updates.

## Показ без backend

```bash
.venv/bin/python -m scripts.offline --port 8080
```

Windows: `.venv\Scripts\python -m scripts.offline --port 8080`. Откройте http://127.0.0.1:8080 и **вручную выберите «Режим имитации»**. Первоначальный рабочий API в этом режиме сервера недоступен — это ожидаемо. Нет записи в БД, admin и настоящего Telegram. Не запускайте обычный файловый сервер на корне репозитория: он мог бы открыть приватные файлы.
