# Техническое руководство

Срез приложения: `2d5ae5c`, 30.09.2026. Документы опираются на исходники, тесты и чтение текущего deployment. Для запуска начните с [SETUP.md](SETUP.md); полевые контракты вынесены в [API.md](API.md) и [DATABASE.md](DATABASE.md).

## Общая архитектура

Python 3.12+, FastAPI/Uvicorn, стандартный `sqlite3`, Decimal, HTTPX и python-dotenv. Pydantic используется для admin input. Frontend: HTML/CSS/vanilla JavaScript без сборки, фреймворка и библиотеки графиков. Закреплённые версии — [requirements-lock.txt](../requirements-lock.txt); браузерные инструменты — [requirements-dev.txt](../requirements-dev.txt).

```text
Браузер
 ├─ GET /                  → HTML / static CSS, JS
 ├─ GET /api/dashboard     → Python enrich + summary → SQLite
 └─ POST /api/admin/...    → Basic Auth + validation → SQLite + history

Telegram
 └─ POST /telegram/webhook → secret + update validation
                            → BEGIN IMMEDIATE
                            → user/task authorization + dialogue
                            → orders/tasks/history/session/outbox → COMMIT

Фоновая asyncio-задача → pending outbox → sending → Telegram Bot API
                                           └→ sent / failed / uncertain + history

Production: HTTPS → Caddy (Docker) → Uvicorn (systemd, один worker) → SQLite
```

Сеть Telegram не удерживает SQLite write lock. Сайт и API имеют один origin. WebSocket и периодического fetch нет. Секреты не передаются JavaScript. Уведомления используют глобальный Telegram ID, а не текстовое поле координатора заказа.

## Структура проекта

```text
app/
  main.py               create_app, routes, защита, lifespan
  config.py             Settings, ROOT, стадии, DEMO_DATE, порог, статьи затрат
  database.py           соединения, DDL, история, чтение/обогащение заказов
  calculations.py       economics, deadlines, enrich, summarize_orders
  validation.py         money, iso_date, ReworkInput
  telegram.py           диалоги, права, outbox, TelegramAPI, delivery_loop
static/
  index.html            главная страница
  app.js                получение снимка, сводка, фильтры, dialog
  admin.js              запросы и состояние формы координатора
  styles.css            общая адаптивная сетка, карточки, progress-графики
  demo-data.json        явно выбранный offline snapshot + сценарий имитации
templates/admin.html    защищённая страница; серверной шаблонизации нет
scripts/
  seed.py               24 заказа, повторный seed, явный reset, offline export
  correct_demo_dates.py узкая одноразовая коррекция прежнего seed
  manage.py             add-user, backup, outbox, telegram-info, webhook
  offline.py            отдельный локальный HTTP-сервер только для static
  browser_check.py      изолированный backend + настоящие браузерные проверки
  dashboard_check.py    чтение публичного dashboard и браузерные проверки
  public_check.py       публичная admin-запись с возвратом исходной суммы
  test_report.py        unittest → фактический отчёт и screenshot
  security_check.py     скан файлов, индекса и Git-истории на секреты
  docs_check.py         ссылки, контракты и примеры документации на временной БД
tests/
  test_app.py           финансы, API, Telegram, безопасность, persistence
  test_dashboard.py     агрегаты, NULL/0, сроки, внимание, invalid rows
deploy/
  push.py               архив + scp, приватный .env, вызов install.sh
  install.sh            venv, зависимости, seed без reset, tests, systemd, Caddy
  kitchen-control.service
  Caddyfile.snippet
  remote.py             отправка локального Python-скрипта через SSH stdin
  inspect_state.py      диагностика SQLite/outbox/service
  review_state.py       состояние БД, сервиса и getWebhookInfo; известный demo
  check_lifecycle.py    stop/start/restart и проверка persistence; меняет сервис
data/                   SQLite, WAL/SHM, backup; вне Git и static
docs/                   руководства, правила, отчёты
artifacts/              проверочные отчёты и настоящие скриншоты
.env.example            безопасные пустые настройки
.gitignore              исключает .env, БД, ключи, logs, backup, временные файлы
```

## Backend

### Запуск и конфигурация

Entry point — `app.main:app`. При импорте вызывается `create_app()`, читаются настройки и выполняется `initialize`: создаются каталог БД и отсутствующие таблицы. Заказы автоматически не создаются: seed — отдельная команда. В тестах используется `create_app(settings, telegram_api, worker=False)` с временной SQLite.

`Settings.from_env()` загружает корневой `.env`; уже заданные переменные процесса имеют приоритет. Относительный DATABASE_PATH считается от корня проекта. PUBLIC_BASE_URL лишается завершающего `/`; COORDINATOR_TELEGRAM_ID должен быть целым или пустым, ALLOW_LOCAL_HTTP включается строкой `true` без учёта регистра. Параметры читаются при создании приложения; изменение `.env` требует restart.

### SQLite и транзакции

`connect()` включает foreign_keys и busy_timeout=10000, возвращает строки `sqlite3.Row`, commit при успехе, rollback при исключении, всегда закрывает соединение. При инициализации включается WAL. ORM и миграционного framework нет.

`get_order()` читает заказ, cost row, разрешённые поля истории и задач, затем возвращает `enrich`. `dashboard()` открывает читающую транзакцию, получает все заказы по ID и агрегирует их одним согласованным снимком. Отдельный endpoint одной карточки выполняет последовательные SELECT через get_order, без дополнительного BEGIN; не следует приписывать ему отдельную гарантию снимка всех таблиц. Admin и webhook используют BEGIN IMMEDIATE.

### Расчёты и validation

`economics(costs, kind)` не смешивает plan/actual. `deadlines(order)` использует фиксированную DEMO_DATE, первоначальный срок, прогноз и фактическое завершение. `enrich` добавляет признаки карточки и перехватывает ошибки её данных. `summarize_orders` агрегирует уже рассчитанные признаки; JS не повторяет бизнес-расчёты.

`money` принимает число/числовую строку/Decimal, отклоняет bool, NULL, NaN/Infinity, отрицательное, сумму > 1e9 и лишние значащие копейки. `iso_date` требует календарную дату YYYY-MM-DD. `ReworkInput` запрещает лишние JSON-поля. ID маршрута заказа ограничен диапазоном 1…2^63−1; update_id — 0…2^63−1.

Ошибочная запись получает `data_error`, пустую economy и безопасные признаки; остальные заказы продолжают отображаться. Даты/обязательные поля и точность денег проверяются приложением, не все эти условия выражены SQLite CHECK.

### Ошибки и HTTP

Ожидаемые ошибки имеют JSON `detail` и HTTP-код. Validation — 422; admin 401/403/503; неизвестный заказ — 404; недоступная БД в health — 503. Необработанная ошибка возвращает нейтральный 500, а приложение логирует только имя типа исключения. Debug, Swagger, ReDoc и OpenAPI endpoints отключены.

На обычные ответы ставятся Cache-Control, nosniff, Referrer-Policy и CSP. API/admin — no-store, остальные пути — no-cache. CORS не настроен. CSP разрешает ресурсы только своего origin, запрещает embedding и inline scripts/styles. Подробности — [SECURITY.md](SECURITY.md).

## Frontend

`index.html` и `templates/admin.html` — готовые файлы, FileResponse без Jinja. Все JS/CSS доступны через StaticFiles `/static`; наличие публичного admin.js не открывает защищённую HTML-страницу или write endpoint.

`refresh()` вызывается при загрузке, кнопке «Обновить» и смене режима. Fetch использует no-store и timeout 12 секунд. Номер запроса защищает от запоздавшего ответа при смене источника. `validSnapshot` проверяет структуру; при ошибке render предыдущий снимок восстанавливается. Последнее успешное время — время браузера после успешного рендера, не `generated_at` сервера. Старые данные при сбое сопровождаются предупреждением.

Фильтры локальны, в API параметры не передаются. Клик KPI выбирает один признак и сбрасывает select-фильтры. Select-условия затем соединяются через AND. Общая сводка и attention не фильтруются. Карточка открывается из уже загруженного snapshot; отдельный GET при открытии не выполняется.

Графики — нативные HTML progress и CSS, с текстовыми числами. Стадии масштабируются по самому большому количеству; сроки и маржинальность — по общему числу заказов. Сетка перестраивается на tablet/mobile, доска и таблица внимания допускают внутренний горизонтальный скролл.

`admin.js` загружает `/api/orders`, блокирует форму на время fetch, записывает только rework_actual и показывает ответ. При неоднозначном результате предлагает проверить фактическую сумму перед повтором. Другие открытые вкладки автоматически не обновляются.

### Simulation

При явном выборе режима загружается `/static/demo-data.json`. Он содержит тот же формат summary и заранее рассчитанный сценарий для заказа 1. Кнопка меняет локальную копию полей, заменяет summary и добавляет локальную history с `source=simulation`. SQLite и Telegram не используются. Refresh сбрасывает локальные изменения. При сбое backend автоматического переключения нет.

`scripts.offline` раздаёт только static на 127.0.0.1:8080; admin/backend там отсутствуют. Export читает выбранную БД, поэтому публичный demo-data следует генерировать из отдельного чистого учебного seed, не из базы с чувствительными сообщениями.

## Telegram: полный путь

1. Webhook сверяет secret header, затем читает не более 262144 байт и разбирает JSON-объект.
2. BEGIN IMMEDIATE; update_id вставляется в таблицу обработанных updates. Повтор немедленно возвращает duplicate.
3. Поддерживаются message/callback_query; только личный чат, положительный ID отправителя, совпадающий с chat.id, не бот.
4. Для callback ставится answerCallbackQuery. Неизвестный/неактивный человек получает только свой ID.
5. Проверяются активная роль, код назначения, текущее состояние задания и стадия заказа.
6. Диалог сохраняется в telegram_sessions; nonce, step, payload и updated_at защищают последовательность. После 24 часов простоя он отклоняется при следующем действии.
7. Финальное подтверждение меняет заказ/задание, пишет историю, создаёт reply и нужное coordinator notification. Всё commit вместе.
8. delivery_loop примерно раз в 2 секунды забирает pending последовательно. Перед сетью фиксирует sending. TelegramAPI имеет timeout 12 секунд.
9. Результат sent/failed/uncertain сохраняется; уведомление даёт отдельную системную историю. После restart оставшиеся sending переводятся в uncertain; автоматического повтора нет.

Webhook HTTP 200 подтверждает обработку/игнорирование update, а не получение исходящего сообщения человеком. Фотографии не скачиваются; в tasks остаётся file_id, исключённый из публичного API. Команды и callback contract — [API.md](API.md), пользовательские шаги — [TELEGRAM_GUIDE.md](TELEGRAM_GUIDE.md).

## Admin и история

Admin использует один набор Basic Auth из окружения. HTTPS обязателен, кроме явно разрешённой локальной разработки. Write дополнительно требует X-Requested-With и допустимый Origin, если он прислан. Пароли сравниваются constant-time. Telegram-роли и Basic Auth — отдельные механизмы, общей пользовательской сессии нет.

Каждая admin-запись меняет costs.rework_actual, timestamps costs/orders и создаёт rework_changed с old/new в private payload. Telegram-события имеют source=telegram, доставка — system. В публичной истории остаются ID события, тип, источник, actor_type/ref, комментарий, created_at; payload, telegram_update_id, task_id скрыты. История не является отдельным редактируемым журналом в UI.

## Проверки и ограничения

39 unittest методов проверяют расчёты, API, SQLite и Telegram со fake transport. Реальный браузер запускается отдельными scripts. Клиентский живой Telegram-прогон и исторические подтверждения явно отделены от автоматических тестов. Команды и риск изменения публичного demo — [TESTING.md](TESTING.md).

Один worker, файловая БД, общая Basic Auth и публичные учебные данные — сознательные границы этого прототипа. Нет встроенного мониторинга, scheduler backup, автоматических миграций, CI workflow и интерфейса для всех стадий. Эксплуатация — [DEPLOYMENT.md](DEPLOYMENT.md), [OPERATIONS.md](OPERATIONS.md).
