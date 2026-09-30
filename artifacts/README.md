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
| 20-automated-tests.png | 25 тестов PASS и полный вывод unittest | Скриншот HTML-отчёта, построенного из фактического запуска |
| automated-tests.txt / automated-tests.html | Сохранённый фактический вывод unittest | Локальная проверка, тестовый Telegram transport |
| browser-results.json | Итоги браузерных сценариев | Локальные фактические проверки |
| public-results.json | Итоги публичной проверки | Настоящий HTTPS endpoint |

Скриншоты Telegram не имитируются HTML-макетом и не заменяются тестовым payload. Если их ещё нет, соответствующие пункты в TEST_RESULTS остаются NOT TESTED. Состояние Telegram после реального пользовательского действия проверяется отдельно.

Пароли вводятся через HTTP authentication context вне видимой страницы; секретных заголовков, `.env`, bot token и SSH-ключей в скриншотах нет.
