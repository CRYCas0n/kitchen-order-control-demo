# База данных

Источник схемы — [app/database.py](../app/database.py), seed — [scripts/seed.py](../scripts/seed.py). Используется встроенный Python `sqlite3`, без ORM.

## Файл и создание

По умолчанию `DATABASE_PATH=data/app.db`, относительно корня проекта; допустим абсолютный путь. SQLite работает в WAL: рядом могут быть `app.db-wal` и `app.db-shm`. Все эти файлы приватны, исключены из Git и находятся вне static.

`initialize()` создаёт каталог и отсутствующие таблицы/индекс (`CREATE ... IF NOT EXISTS`), включает WAL. Вызывается при создании приложения, seed и operational CLI. Это не механизм миграции уже существующих столбцов. foreign_keys и busy_timeout=10000 включаются на каждом соединении.

## Модель данных

```text
orders
 ├─ costs             0..1 строка, order_id одновременно PK и FK
 ├─ tasks             0..N заданий, FK order_id
 ├─ history           0..N событий, FK order_id, необязательный FK task_id
 └─ telegram_outbox   необязательная связь сообщения с заказом

telegram_users
 └─ telegram_sessions 0..1 диалог на Telegram ID → FK tasks.id

telegram_updates
 └─ telegram_outbox   0..N сообщений на update_id

telegram_users.(assignee_code, role) ↔ tasks.(assignee_code, role)
   логическое сопоставление, НЕ внешний ключ и НЕ уникальное назначение
```

`history.telegram_update_id` уникален, но **не является FK** на telegram_updates. Имена coordinator/stage_executor в orders — обычные строки, без FK на пользователей.

## Таблицы

### orders

`id` — INTEGER PRIMARY KEY; `order_number` — обязательный UNIQUE. Обязательные описательные поля: client_alias, sales_point_type, sales_point, city, coordinator, stage_executor, stage, next_action, project_version. Даты: promised_date_initial, forecast_date, next_action_due обязательны; completed_date nullable. created_at/updated_at обязательны.

Проблема: problem_type, problem_comment, problem_help_needed nullable; problem_status по умолчанию none, CHECK none/open/resolved. Один текущий набор проблемы на заказ. Тип точки продаж ограничен «Шоурум»/«Дилер», стадия — десятью значениями из STAGES. Валидность календарных дат контролирует Python, SQLite хранит TEXT.

### tasks

PK id, обязательный FK order_id. role: measurer/installer. assignee_code — код назначения, не Telegram ID. status: new/accepted/problem/transfer_requested/completed. due_date обязателен; accepted_at/completed_at nullable.

Запрос переноса хранится в proposed_date/transfer_reason. Выполнение — checklist_result (JSON-текст), comment, photo_file_id. created_at/updated_at обязательны. Ограничения «одно задание на заказ» нет; seed создаёт по одному для выбранных стадий. `ON DELETE CASCADE` не задан.

### costs

PK/FK order_id, updated_at и 14 NUMERIC-полей: каждая статья `revenue`, `materials`, `manufacturing`, `delivery`, `installation`, `commission`, `rework` имеет суффикс `_plan` и `_actual`.

Любое значение может быть NULL. CHECK допускает NULL либо SQLite integer/real от 0 до 1 000 000 000 включительно. Точность копеек проверяет `money`, а не SQL CHECK. Доход и процент не сохраняются в таблице: рассчитываются при чтении. SQLite может вернуть int или float; Python переводит через строку в Decimal для расчётов.

### history

PK id, обязательный FK order_id, необязательный FK task_id. event_type — строка без ограниченного enum. actor_type/ref, source, comment, created_at обязательны. source ограничен telegram/admin/simulation/system. payload — JSON-текст, по умолчанию `{}`. telegram_update_id nullable и UNIQUE; несколько NULL разрешены.

Реальные типы событий: seed, accepted, problem, transfer_requested, completed, rework_changed, notification_sent/failed/uncertain, demo_dates_corrected. В существующей истории могут быть системные события ручного восстановления уведомления. Не все действия бота создают бизнес-событие: просмотр `/tasks`, шаги до подтверждения и повтор принятия — нет.

Индекс `history_order(order_id,id)` ускоряет чтение истории заказа. Публичный API сортирует по id DESC и не возвращает payload/telegram_update_id/task_id.

### telegram_users

PK telegram_id, display_name, role (measurer/installer/coordinator), assignee_code, active (0/1, default 1). Seed не добавляет пользователей. `manage add-user` вставляет или обновляет роль/код/имя, включает active и удаляет текущий диалог. Отключение — административный SQL, отдельной CLI-команды нет.

### telegram_sessions

PK/FK telegram_id обеспечивает один диалог на пользователя. task_id — обязательный FK, action, step, nonce, payload и updated_at обязательны. Action/step не ограничены SQL CHECK; допустимые значения задаёт код диалога. Payload содержит промежуточные ответы и возможный file_id. Незавершённый диалог переживает restart; TTL проверяется кодом при следующем сообщении, фонового удаления старых строк нет.

### telegram_updates

PK update_id, created_at. Это журнал дедупликации, не архив полного update JSON. Вставка `INSERT OR IGNORE` внутри BEGIN IMMEDIATE определяет, новый ли update. При rollback вставка также откатывается. Игнорируемый корректный update может быть зарегистрирован без истории и outbox.

### telegram_outbox

PK id; обязательный FK update_id; UNIQUE dedupe_key вида `update_id:reply`, `:ack`, `:coordinator`. method и body (JSON-текст) обязательны; order_id nullable FK. notification 0/1 отличает сообщение координатору. status: pending/sending/sent/failed/uncertain; error nullable; created_at/updated_at обязательны.

Body может содержать настоящий chat_id и текст сообщения. Поэтому production DB, её backup и полные выборки outbox нельзя публиковать. Отдельного индекса status нет. Записи не очищаются по расписанию.

## Транзакции и идемпотентность

Webhook атомарно записывает update, бизнес-состояние, историю, session и outbox. Уникальности update_id и dedupe_key защищают повторную доставку одного update. История Telegram-бизнес-операции дополнительно имеет UNIQUE telegram_update_id.

Это не идемпотентность произвольных действий с разными update_id и не гарантия доставки сообщения ровно один раз. После неизвестного результата сети outbox остаётся uncertain и не переотправляется. При старте sending → uncertain фиксируется с историей уведомления.

Admin также использует BEGIN IMMEDIATE. Одинаковая сумма rework при повторном успешном HTTP-запросе создаёт ещё одно событие — отдельного idempotency key у admin нет.

## NULL и timestamps

NULL расход — неизвестное значение, 0 — подтверждённый ноль. NULL completed_date обязателен для активного заказа по правилам Python. NULL accepted_at/completed_at у задачи означает, что соответствующее действие не записано. Nullable FK означает отсутствие связи, не ID=0.

`now()` пишет ISO 8601 UTC с точностью до секунды. Seed использует `2026-09-30T08:00:00+00:00` для учебных событий и записей. Даты сроков — отдельные YYYY-MM-DD без времени. created_at сохраняется при изменениях; updated_at обновляется конкретными обработчиками, это не SQL-trigger. Например, системное уведомление добавляет историю, но не меняет orders.updated_at.

## Seed и безопасный учебный reset

```bash
python -m scripts.seed
```

При наличии хотя бы одного заказа seed сохраняет БД без дозаполнения. В пустой создаёт 24 заказа КФ-2601…КФ-2624, 24 costs, 6 tasks, 24 seed-события, 3 шоурума и 5 дилерских городов. Код INSTALL-01 получает задачи заказов 1/3, MEASURE-01 — 2; INSTALL-02 — 20/22, MEASURE-02 — 13. Все сроки этих заданий — 2026-10-01. Пользователей в свежем seed нет.

Полный reset демонстрационных бизнес-данных **разрушителен**: удаляет orders/costs/tasks/history/telegram_updates/sessions/outbox; telegram_users сохраняется. На действующем deployment не используйте его для подготовки показа: старые update_id будут забыты, доказательства потеряны. Для отдельной локальной учебной БД:

```bash
DATABASE_PATH=data/sandbox.db python -m scripts.seed --reset
```

В PowerShell:

```powershell
$env:DATABASE_PATH='data/sandbox.db'
.venv\Scripts\python -m scripts.seed --reset
Remove-Item Env:DATABASE_PATH
```

`--export` пишет static/demo-data.json из выбранной БД. Используйте только отдельный чистый учебный seed; export не является обезличиванием production. Старую ошибку даты КФ-2611 исправляет `scripts.correct_demo_dates` после backup: только точное исходное состояние без бизнес-истории, с аудитом, повторный запуск безопасен.

## Проверка, backup и восстановление

В активированном окружении, из корня проекта:

```bash
python -c "from app.config import Settings; from app.database import connect; s=Settings.from_env(); c=connect(s.database_path); db=c.__enter__(); print(db.execute('PRAGMA integrity_check').fetchone()[0]); print(db.execute('PRAGMA foreign_key_check').fetchall()); c.__exit__(None,None,None)"
python -m scripts.manage backup data/backup-YYYYMMDDTHHMMSSZ.db
```

Замените имя backup новым уникальным именем. CLI не перезаписывает существующий файл и использует SQLite backup API, учитывающий WAL. Обычное копирование одного app.db работающего процесса не обеспечивает согласованную копию.

Восстановление выполняется при остановленном только kitchen-control, после проверки backup и сохранения текущей базы. Нельзя оставлять WAL/SHM от другой версии app.db. Подробная последовательность с ограничением путей — [OPERATIONS.md](OPERATIONS.md). Автоматического расписания backup, шифрования копий и проверенного внешнего хранилища в проекте нет.
