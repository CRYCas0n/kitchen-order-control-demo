# Эксплуатация

Команды Linux ниже выполняются администратором текущего VPS из `/opt/kitchen-control`. Они относятся только к сервису `kitchen-control`. Не выводите `.env` в общий терминальный лог и не публикуйте полные rows Telegram-таблиц.

## Быстрая проверка

```bash
cd /opt/kitchen-control
sudo systemctl is-active kitchen-control
sudo systemctl is-enabled kitchen-control
curl -fsS http://172.18.0.1:18080/api/health
curl -fsS https://kitchen.45-67-202-162.sslip.io/api/health
sudo -u kitchen-control .venv/bin/python -m scripts.manage telegram-info
sudo -u kitchen-control .venv/bin/python -m scripts.manage outbox
```

Норма: service active/enabled, health status/database=ok, webhook указывает на PUBLIC_BASE_URL + `/telegram/webhook`. pending_update_count=0 означает отсутствие ожидающих входящих updates у Telegram, а не отсутствие исходящего outbox. `manage outbox` выводит только исходящие строки, которые ещё не sent; пустой вывод означает отсутствие таких строк.

Откройте сайт и нажмите «Обновить». Проверьте время, число заказов и историю известного заказа. API health не проверяет бизнес-правильность данных или доставку координатору.

`deploy/review_state.py` — дополнительная диагностика конкретного demo: она ожидает известные события КФ-2603. На свежем seed без этих событий скрипт неприменим; это не универсальный health check. `deploy/inspect_state.py` показывает также подключённых пользователей, поэтому его вывод приватен.

## Логи, restart и ресурсы

```bash
sudo journalctl -u kitchen-control -n 100 --no-pager
sudo journalctl -u kitchen-control --since '30 minutes ago' --no-pager
sudo systemctl restart kitchen-control
sudo systemctl status kitchen-control --no-pager
df -h /opt/kitchen-control
du -sh data
free -h
ss -ltn
```

После restart повторите health. Access log приложения отключён; runtime ошибки и состояния outbox попадают в journald. Не включайте HTTPX debug с настоящим токеном: URL Telegram API содержит токен. Общий журнал Caddy может включать другие сайты; используйте его только для диагностики proxy и не публикуйте необработанный вывод.

Restart восстанавливает сохранённые диалоги и продолжает pending outbox. Прерванные sending становятся uncertain без автоматического повтора. Реальный reboot всего общего VPS не нужен для обновления приложения и в проверках проекта не выполнялся.

## Проверка SQLite

Без полного вывода личных данных:

```bash
sudo -u kitchen-control .venv/bin/python - <<'PY'
from app.config import Settings
from app.database import connect
with connect(Settings.from_env().database_path) as db:
    print('integrity:', db.execute('PRAGMA integrity_check').fetchone()[0])
    print('foreign keys:', db.execute('PRAGMA foreign_key_check').fetchall())
    print('orders:', db.execute('SELECT COUNT(*) FROM orders').fetchone()[0])
    print('outbox:', [tuple(r) for r in db.execute('SELECT status,COUNT(*) FROM telegram_outbox GROUP BY status')])
PY
```

Ожидаются integrity=ok, пустой foreign_key_check. Для проверки прикладных ошибок прочитайте `/api/dashboard`: data_error и summary.invalid_count. Корректность SQLite-файла не гарантирует корректность дат/бизнес-состояний.

## Backup

```bash
stamp=$(date -u +%Y%m%dT%H%M%SZ)
sudo -u kitchen-control .venv/bin/python -m scripts.manage backup "data/backup-$stamp.db"
```

Команда использует SQLite backup API и не перезаписывает существующий файл. Проверяйте созданную копию через integrity_check, храните приватно и контролируйте свободное место. В проекте нет автоматического расписания и удаления старых backup.

## Восстановление backup

Это отдельная операция с потерей изменений после даты копии. Внешние Telegram-сообщения восстановление не отменяет; старый backup может содержать pending/outdated updates. Не делайте restore для обычной демонстрации или вместо исправления одной строки.

Порядок для подтверждённого стандартного пути **data/app.db**:

1. Сохраните текущую БД отдельным backup командой выше и приватно сохраните `.env`/код.
2. Выберите существующий проверенный файл. Подставьте его вместо `YOUR_VERIFIED_BACKUP.db` в следующем коде.
3. Остановите только сервис:

```bash
sudo systemctl stop kitchen-control
```

4. Проверьте файл и перенесите прежние app.db/WAL/SHM в отдельный rollback-каталог; затем установите копию:

```bash
sudo .venv/bin/python - <<'PY'
from datetime import datetime, timezone
from pathlib import Path
import os
import shutil
import sqlite3
from app.config import Settings

data = Path('/opt/kitchen-control/data').resolve()
target = data / 'app.db'
source = (data / 'YOUR_VERIFIED_BACKUP.db').resolve()
assert Path(Settings.from_env().database_path).resolve() == target, 'Configured DB differs; stop and review paths'
assert source.is_file() and source != target and source.parent == data, 'Choose a verified backup inside data'
with sqlite3.connect(source) as db:
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    print('Backup orders:', db.execute('SELECT COUNT(*) FROM orders').fetchone()[0])
rollback = data / ('before-restore-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
rollback.mkdir(mode=0o700)
for name in ('app.db', 'app.db-wal', 'app.db-shm'):
    old = (data / name).resolve()
    assert old.parent == data
    if old.exists():
        shutil.move(str(old), str(rollback / name))
shutil.copy2(source, target)
shutil.chown(target, user='kitchen-control', group='kitchen-control')
os.chmod(target, 0o640)
print('Restored; previous database retained in', rollback)
PY
```

Если проверка не прошла, не продолжайте запуск вслепую. При другом DATABASE_PATH эта процедура намеренно останавливается: сначала адаптируйте и проверьте все пути. Старые sidecar-файлы не удаляются безвозвратно и не смешиваются с новым app.db.

5. До запуска проверьте outbox восстановленной БД; pending после старого backup требует решения оператора. Не меняйте массово failed/uncertain на pending.
6. Запустите только kitchen-control, проверьте health, сайт, webhook и известные заказы:

```bash
sudo -u kitchen-control .venv/bin/python -m scripts.manage outbox
sudo systemctl start kitchen-control
curl -fsS https://kitchen.45-67-202-162.sslip.io/api/health
```

Полная замена рабочей production DB в целях тестирования не выполнялась; проверены создание согласованной копии и её integrity. Последовательность выше — инструкция восстановления, не отчёт о выполненном disaster recovery.

## Добавить Telegram-пользователя

Человек должен открыть бота и нажать `/start`, затем передать свой ID администратору. Подставьте его целое положительное значение вместо YOUR_TELEGRAM_ID:

```bash
sudo -u kitchen-control .venv/bin/python -m scripts.manage add-user YOUR_TELEGRAM_ID installer INSTALL-01 'Учебный монтажник'
```

Для замерщика: role `measurer`, код `MEASURE-01`. Для координатора: role `coordinator`, код `COORD-01`. Коды исполнителя должны совпадать с tasks.assignee_code. Команда не создаёт задания; повторная регистрация обновляет имя/роль/код, включает active=1 и удаляет незаконченный диалог. Затем пользователь снова вызывает `/tasks`.

Не назначайте один код разным людям, если они не должны иметь общий доступ к задачам. Отображаемое имя в заказе не выдаёт права.

## Отключить Telegram-пользователя

Отдельной команды disable-user и экрана управления пользователями нет. После backup примените ограниченное изменение SQL; placeholder должен быть заменён на нужный ID:

```bash
sudo -u kitchen-control .venv/bin/python - <<'PY'
from app.config import Settings
from app.database import connect
telegram_id = int('YOUR_TELEGRAM_ID')
with connect(Settings.from_env().database_path) as db:
    changed = db.execute('UPDATE telegram_users SET active=0 WHERE telegram_id=?', (telegram_id,)).rowcount
    if changed != 1:
        raise ValueError('User not found; nothing committed')
    db.execute('DELETE FROM telegram_sessions WHERE telegram_id=?', (telegram_id,))
print('User disabled')
PY
```

Следующий update будет обработан как от неизвестного пользователя; активные задачи и история не удаляются. Уже поставленные исходящие сообщения не отменяются автоматически. Повторное add-user включает пользователя обратно.

## Сменить координатора

1. Новый человек запускает бота. Добавьте его с role=coordinator.
2. Приватно измените COORDINATOR_TELEGRAM_ID в серверном `.env` на его ID.
3. Обновите соответствующую локальную deploy-копию `.env`, иначе следующий push вернёт старое значение.
4. Restart kitchen-control, затем новый человек вызывает `/tasks`.
5. На согласованном учебном заказе проверьте новую проблему и получение уведомления.

В приложении один глобальный адресат. Уже существующий outbox хранит chat_id в body, поэтому его адресат не меняется при смене настройки. Ранее не созданные уведомления из-за отсутствия координатора автоматически задним числом не отправляются.

## Сменить admin credentials или токены

Редактируйте `.env` приватным редактором (`sudoedit /opt/kitchen-control/.env`), не передавайте пароль как часть общей shell-команды. Сохраните владельца root:kitchen-control и режим 640. Обновите локальную deploy-копию. Restart применяет ADMIN_USERNAME/ADMIN_PASSWORD, токен и другие Settings.

После изменения Basic Auth закройте старое приватное окно и войдите заново. Нет приложения logout или индивидуальных web-ролей.

При ротации токена через @BotFather либо изменении webhook secret/URL дополнительно выполните `scripts.manage webhook`, затем `telegram-info`. Не используйте `drop_pending_updates=true` для сокрытия ошибок: штатная команда сохраняет ожидающие updates.

## Исходящие сообщения

`pending` ждут worker; `sending` отправляются; `sent` подтверждены API; `failed` отвергнуты; `uncertain` могли быть доставлены. Проверьте причину и Telegram-клиент перед ручным решением. Универсальной безопасной CLI-команды resend нет. Подробности предыдущего ручного восстановления — история [ISSUE_LOG.md](ISSUE_LOG.md), а не автоматически запускаемый рецепт.

## Обновление и устаревшие данные

Обновление приложения — [DEPLOYMENT.md](DEPLOYMENT.md). Документы сами по себе не требуют restart. Если UI открыт давно, нажмите «Обновить»: таймерного refresh нет. Предупреждение и старое время означают, что последнее получение/отображение не удалось; наличие HTTP 200 у главной страницы ещё не означает успешный API.
