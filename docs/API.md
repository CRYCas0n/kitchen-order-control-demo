# HTTP API

Источник маршрутов — [app/main.py](../app/main.py), формы ответов — [app/database.py](../app/database.py) и [app/calculations.py](../app/calculations.py). Swagger/ReDoc/OpenAPI отключены: `/docs`, `/redoc`, `/openapi.json` не являются документацией приложения и возвращают 404.

## Общие условия

- Production origin: `https://kitchen.45-67-202-162.sslip.io`; локально `http://127.0.0.1:8000`.
- JSON использует snake_case, суммы — числа или null, сроки — YYYY-MM-DD, timestamps — ISO 8601 UTC.
- GET бизнес-данных публичны; pagination/search/query filters не реализованы. Фильтрация происходит в браузере.
- `order_id`: integer от 1 до 9223372036854775807; некорректный — 422, корректный отсутствующий — 404.
- API/admin штатно отдают `Cache-Control: no-store`. CORS не включён.
- Ошибки приложения: `{"detail":"текст причины"}`. Необработанная ошибка — 500 без stack trace в ответе; health имеет собственную форму 503.
- Полные ответы содержат больше полей, чем приведённые ниже **явно обозначенные фрагменты**. Это не отдельный режим сокращённого API.

Для примеров GET в Bash:

```bash
BASE_URL='http://127.0.0.1:8000'
```

В PowerShell используйте `curl.exe` и подставьте URL напрямую. Примеры write выполняйте в отдельной учебной базе; они действительно сохраняют изменения.

## GET /api/health

Проверяет возможность прочитать orders из SQLite. Авторизации, параметров и тела нет. Не проверяет Telegram, наполненность заказами, доставку сообщений или сертификат reverse proxy.

```bash
curl -fsS "$BASE_URL/api/health"
```

200, полный пример:

```json
{"status":"ok","database":"ok","timestamp":"2026-09-30T13:40:14+00:00","version":"1.0.0"}
```

Timestamp меняется; version — строка в коде, не Git hash. При SQLite error — 503:

```json
{"status":"unavailable","database":"unavailable"}
```

До запуска приложения или при отказе proxy возможны сетевой сбой/502, не этот JSON.

## Общий объект Order

Возвращается в GET orders/id, списке orders, dashboard.orders и успешном POST rework.

| Группа | Поля |
|---|---|
| Заказ | id, order_number, client_alias, sales_point_type, sales_point, city, coordinator, stage_executor, stage, project_version |
| Даты и действие | promised_date_initial, forecast_date, completed_date, next_action, next_action_due, created_at, updated_at |
| Проблема | problem_type, problem_comment, problem_help_needed, problem_status |
| Признаки | active, overdue, delay_risk, completed_late, deadline_label, open_problem, incomplete, low_margin, data_error |
| Суммы | costs: order_id, updated_at, семь полей *_plan и семь *_actual |
| Расчёты | economy.plan и economy.actual; при data_error — economy={} |
| История / задачи | history и tasks — массивы разрешённых публичных полей |

Economy для каждого kind:

```json
{"complete":true,"missing":[],"variable_costs":200000.0,"margin_income":100000.0,"margin_percent":33.33,"low_margin":false,"negative_margin":false}
```

При неполных расходах `complete=false`, missing содержит ключи статей без суффикса, три рассчитанных суммы/процент — null. При нулевой выручке и полном факте только процент null. Заказный low_margin объединяет low_margin и negative_margin факта. `data_error` обычно null; при ошибке некоторые deadline-поля могут отсутствовать, остальные признаки выставлены защитно — см. [BUSINESS_RULES.md](BUSINESS_RULES.md).

Public task содержит только id, role, status, due_date, accepted_at, completed_at, proposed_date, transfer_reason, comment. Нет assignee_code, checklist_result, photo_file_id. Public history содержит id, event_type, actor_type, actor_ref, source, comment, created_at. Нет private payload, task_id, telegram_update_id. Telegram user ID и raw update в Order не выдаются.

## GET /api/orders

Авторизация не нужна. Параметров, body и серверной пагинации нет. Возвращает 200 и массив **всех полных объектов Order** по возрастанию ID; пустая БД — `[]`.

```bash
curl -fsS "$BASE_URL/api/orders"
```

Пример проекции двух элементов нового seed (в настоящем ответе все поля Order и 24 элемента):

```json
[{"id":1,"order_number":"КФ-2601","stage":"Монтаж"},{"id":2,"order_number":"КФ-2602","stage":"Замер"}]
```

Ошибка чтения/сервера — 500. Повреждённый отдельный заказ обычно остаётся в массиве с data_error; это не HTTP-ошибка всего списка.

## GET /api/orders/{order_id}

Публичное чтение одной карточки. Body/query parameters нет.

```bash
curl -fsS "$BASE_URL/api/orders/1"
```

200, фрагмент Order свежего seed:

```json
{
  "id":1,
  "order_number":"КФ-2601",
  "stage":"Монтаж",
  "promised_date_initial":"2026-09-27",
  "forecast_date":"2026-10-02",
  "completed_date":null,
  "active":true,
  "overdue":true,
  "delay_risk":true,
  "open_problem":false,
  "incomplete":false,
  "low_margin":false,
  "data_error":null
}
```

Ошибки: 404 `Заказ не найден`; 422 `Некорректные параметры запроса.`; 500 при отказе сервера. Фактический production Order может отличаться от seed после реальных операций.

## GET /api/orders/{order_id}/history

Публичный массив истории, новые события первыми (`id DESC`). Только path parameter; body отсутствует.

```bash
curl -fsS "$BASE_URL/api/orders/1/history"
```

200, полный массив истории заказа 1 в свежем seed:

```json
[
  {
    "id":1,
    "event_type":"seed",
    "actor_type":"system",
    "actor_ref":"Система",
    "source":"system",
    "comment":"Создан учебный заказ. Все имена и суммы вымышлены.",
    "created_at":"2026-09-30T08:00:00+00:00"
  }
]
```

404/422/500 — как у чтения одной карточки. Параметров изменения/удаления истории нет.

## GET /api/dashboard

Публичный согласованный снимок заказов и сводки; параметров/body нет.

```bash
curl -fsS "$BASE_URL/api/dashboard"
```

200: объект с `demo_date`, `low_margin_threshold`, `source="backend"`, `stages` (10 строк), `generated_at`, `orders` (все Order), `kpis`, `summary`. Верхнеуровневый kpis равен summary.kpis и оставлен для совместимости.

Пример **полного summary** нового seed:

```json
{
  "kpis":{"active":22,"overdue":9,"open_problem":2,"delay_risk":5,"incomplete":1,"low_margin":2},
  "stages":[
    {"stage":"Замер","count":2},
    {"stage":"Проектирование","count":2},
    {"stage":"Согласование","count":2},
    {"stage":"Комплектация","count":2},
    {"stage":"Производство","count":3},
    {"stage":"Контроль качества","count":2},
    {"stage":"Доставка","count":3},
    {"stage":"Монтаж","count":4},
    {"stage":"Приёмка","count":2},
    {"stage":"Завершён","count":2}
  ],
  "deadlines":{"on_time":14,"risk":0,"overdue":9,"completed_late":1},
  "margins":{"normal":21,"low":1,"negative":1,"incomplete":1,"not_calculable":0},
  "finance":{"revenue_actual":7840000.0,"margin_income":2970000.0,"average_margin_percent":37.03,"complete_count":23,"average_count":23,"loss_count":1},
  "attention_ids":[4,5,18,24,7],
  "attention_total":9,
  "invalid_count":0,
  "total_count":24
}
```

Числа иллюстрируют новый seed, а не неизменяемый production baseline. Summary считается backend по готовым признакам карточек. При отсутствии подходящих фактических данных finance суммы/процент null. Ошибки — 500; некорректная строка возвращается с data_error и учитывается в invalid_count. Алгоритмы распределений — [BUSINESS_RULES.md](BUSINESS_RULES.md).

## POST /api/admin/orders/{order_id}/rework

Единственный admin write endpoint. **Заменяет** фактическую стоимость переделки. Требует Basic Auth, HTTPS (кроме разрешённого local HTTP), заголовок `X-Requested-With: kitchen-control`. Если прислан Origin, он должен точно совпасть с origin запроса. Сам браузер обычно передаёт Origin; CLI может его не передавать.

JSON body: ровно обязательное поле `rework_actual`, число или числовая строка, 0…1 000 000 000, максимум копейки. `null`, bool, NaN, Infinity, отрицательное и дополнительные поля запрещены.

Пример для отдельного тестового окружения; curl спросит пароль, секрет не включён в команду:

```bash
curl --user YOUR_ADMIN_USERNAME \
  -H 'Content-Type: application/json' \
  -H 'X-Requested-With: kitchen-control' \
  --data '{"rework_actual":"85000.00"}' \
  "$BASE_URL/api/admin/orders/1/rework"
```

200: **полный обновлённый Order**. Фрагмент результата для исходного КФ-2601:

```json
{"id":1,"low_margin":true,"economy":{"actual":{"complete":true,"missing":[],"variable_costs":275000.0,"margin_income":25000.0,"margin_percent":8.33,"low_margin":true,"negative_margin":false}}}
```

История получает rework_changed, source=admin, даже при повторном сохранении той же суммы. 200 может содержать data_error по другой части заказа; стоимость уже сохранена, хотя итоговая экономика тогда отсутствует.

| Код | Причина |
|---|---|
| 401 | Нет/неверны credentials; WWW-Authenticate Basic |
| 403 | Неподходящий HTTP, нет защитного заголовка или неверный Origin |
| 404 | Заказ или строка costs отсутствует |
| 422 | Невалидные path/body; детали сумм выдаются безопасным общим сообщением |
| 503 | ADMIN_PASSWORD не настроен |
| 500 | Неожиданная ошибка сервера |

У сетевого обрыва после записи нет гарантированного «не сохранено». Перед повтором прочитайте Order/историю. У endpoint нет отдельного idempotency key.

## POST /telegram/webhook

Telegram обращается сюда напрямую. Basic Auth не нужен; обязателен `X-Telegram-Bot-Api-Secret-Token`, совпадающий с TELEGRAM_WEBHOOK_SECRET. Максимальное тело backend — 262144 байта; на production Caddy дополнительно ограничивает request body своим 256KB.

Поддерживаемые поля Telegram: update_id, message (from, chat, text/photo) или callback_query (id, from, message, data). Обработчик ожидает личный чат; групповые сообщения/боты игнорируются. update_id — целое 0…2^63−1, bool не подходит. Пустой объект без update_id невалиден.

Пример **только для изолированного backend с тестовым секретом**: групповой update не создаёт ответ пользователю.

```bash
curl -H 'Content-Type: application/json' \
  -H 'X-Telegram-Bot-Api-Secret-Token: YOUR_WEBHOOK_SECRET' \
  --data '{"update_id":123456789,"message":{"from":{"id":1001},"chat":{"id":-1001,"type":"group"},"text":"/tasks"}}' \
  "$BASE_URL/telegram/webhook"
```

200, возможные полные ответы:

```json
{"ok":true,"ignored":true}
```

```json
{"ok":true}
```

```json
{"ok":true,"duplicate":true}
```

200 может сопровождать отказ пользователю в действии: ответ с пояснением помещён в outbox. HTTP-ответ не содержит само сообщение бота и не доказывает доставку координатору.

Ошибки: 403 — отсутствует/неверен/не настроен secret; 413 — превышен размер; 422 — некорректный JSON/update; 500 — неожиданная ошибка. При ошибке внутри транзакции изменения, включая регистрацию update_id, откатываются.

Команды: `/start`, `/tasks`, `/cancel`. Callback data создаёт сам бот: `task:ID`, `accept:ID`, `problem:ID`, `transfer:ID`, `done:ID`; затем `check:NONCE`, `skip:NONCE`, `confirm:NONCE`. Это внутренний протокол диалога, не публичный способ управлять произвольным заказом. Права, стадия и nonce проверяются повторно. Не подделывайте новые update_id на production ради проверки; используйте автоматические тесты или настоящий клиент.

## Страницы и static

| Метод / URL | Назначение и пример | Успех / ошибки |
|---|---|---|
| GET `/` | `curl "$BASE_URL/"` — главная, без auth/body/params | 200 text/html; ошибки сервера 500 |
| GET `/admin` | `curl --user YOUR_ADMIN_USERNAME "$BASE_URL/admin"` — форма; те же HTTPS/Basic правила, но X-Requested-With для GET не нужен | 200 text/html; 401/403/503, 500 |
| GET `/static/{path}` | `curl "$BASE_URL/static/app.js"`; public CSS/JS/HTML/учебный JSON, без auth/body | 200 содержимое файла; 404 для отсутствующего файла/каталога; StaticFiles поддерживает HEAD |

Пример начала HTML-ответа страниц: `<!doctype html><html lang="ru">` (пробельное форматирование может отличаться). `/static/demo-data.json` имеет source=simulation и дополнительный объект simulation, в отличие от рабочего dashboard. Листинг каталогов не включён. `.env`, SQLite, docs и Git tree не смонтированы как публичные файлы.
