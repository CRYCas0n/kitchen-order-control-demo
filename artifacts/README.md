# Доказательства проверок

Все PNG сняты настоящим Chromium/Google Chrome через Playwright. Это скриншоты реализованного приложения, не сгенерированные изображения.

| Файлы | Что показывают | Источник |
|---|---|---|
| 01-dashboard-local.png | Главная панель | Изолированная локальная SQLite |
| 02-problem-detail-local.png | Проблемный заказ, отрицательный доход | Локальная SQLite |
| 03-economy-local.png | План/факт заказа | Локальная SQLite |
| 04-stale-data-local.png | Сбой API, старое время и предупреждение | Реальный сетевой abort в браузерном тесте |
| 05-admin-local.png | Сохранение переделки | Локальный backend |
| 06-rework-result-local.png | Пересчёт дохода после admin | Локальный backend |
| 07-mobile-local.png | Адаптивность 390px | Локальный backend |
| 10-dashboard-public.png | Главный dashboard на HTTPS | Публичный production backend |
| 11-board-public.png | Доска по стадиям | Публичный backend |
| 12-problem-public.png | Детальная карточка проблемного заказа | Публичный backend |
| 13-admin-public.png | Защищённый admin после сохранения | Публичный backend |
| 14-rework-detail-public.png | Заказ после изменения переделки | Публичный backend |
| 15-rework-economy-public.png | Доход 25 000 ₽ и маржинальность 8,33% | Публичный backend |
| 16-mobile-public.png | Мобильный публичный сайт | Публичный backend |
| 20-automated-tests.png | 39 тестов PASS и полный вывод unittest | Скриншот HTML-отчёта, построенного из фактического запуска |
| 21-real-telegram-problem-public.png | Реальная проблема монтажника в публичной карточке | Настоящий Telegram update_id=586212949 → production SQLite → браузер |
| 22-real-telegram-history-public.png | История после настоящего Telegram-сообщения | Production backend; это не simulation |
| telegram-live-evidence.json | Публичные данные реально полученной проблемы | Production API, source=telegram; без Telegram user ID и секретов |
| 23-automatic-telegram-problem-public.png | Проблема КФ-2603 после автоматического уведомления координатору | Настоящий update_id=586212957; ко времени снимка монтаж уже завершён |
| 24-automatic-notification-history-public.png | История настоящей проблемы и автоматической отправки | Production backend |
| 25-real-telegram-acceptance-board.png | КФ-2603 в колонке «Приёмка» | Реальное выполнение монтажником, update_id=586212965 |
| 26-real-telegram-acceptance-detail.png | Детальная карточка после монтажа | Заказ ещё не завершён |
| 27-real-telegram-completion-history.png | История завершения задания через Telegram | Production backend |
| telegram-automatic-evidence.json | Доказательство автоматического уведомления | API и текстовое подтверждение владельца |
| telegram-completion-evidence.json | SQLite, checklist, уведомление, стадия и проверка повторного update_id | Настоящие серверные данные; без user IDs и секретов |
| automated-tests.txt / automated-tests.html | Сохранённый фактический вывод unittest | Локальная проверка, тестовый Telegram transport |
| browser-results.json | Итоги браузерных сценариев | Локальные фактические проверки |
| public-results.json | Итоги публичной проверки | Настоящий HTTPS endpoint |
| 30–33, dashboard-public-results.json | Дашборд руководителя, KPI, графики, desktop/mobile | Локальный и публичный backend |
| production-review.json | Read-only состояние сервиса, БД, webhook и прежнего Telegram E2E после финальной выкладки | VPS + настоящий Telegram getWebhookInfo |
| security-review.json | Сканирование credentials и запрещённых файлов, включая индекс и историю Git | Фактический локальный запуск; значения секретов не выводятся |
| dependency-audit.json | Аудит закреплённых зависимостей | pip-audit, известные advisory на момент проверки |
| restore-results.json | Восстановление и тесты без существующей среды, SQLite и credentials | Новый временный каталог и virtualenv, зависимости из lock-файла |

Скриншоты самого Telegram-клиента не имитируются HTML-макетом и не заменяются тестовым payload. Их сохраняет владелец; пока получены текстовые подтверждения из настоящего клиента (docs/TELEGRAM_RECEIPTS.md). Живые проверки Telegram уже выполнены и имеют отдельные доказательства в SQLite, API, публичном браузере и переписке.

Пароли вводятся через HTTP authentication context вне видимой страницы; секретных заголовков, `.env`, bot token и SSH-ключей в скриншотах нет.
