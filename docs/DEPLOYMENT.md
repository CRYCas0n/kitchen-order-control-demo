# Production deployment

Документ описывает **существующий** VPS. Скрипты привязаны к его каталогам, сети Docker и hostname; они не являются универсальным установщиком нового сервера.

## Фактическая схема

| Компонент | Настройка |
|---|---|
| ОС / runtime | Ubuntu 24.04 LTS, Python 3.12, отдельный venv |
| Каталог | /opt/kitchen-control |
| Backend | Uvicorn, app.main:app, один worker, systemd kitchen-control |
| Пользователь | kitchen-control, системный, без interactive shell |
| Слушающий адрес | 172.18.0.1:18080, Docker bridge хоста |
| Доверенный proxy IP | 172.18.0.3 — адрес существующего Caddy |
| Reverse proxy | Caddy в Docker; nginx не используется |
| Конфигурация Caddy | /opt/caddy/Caddyfile → /etc/caddy/Caddyfile контейнера caddy |
| Публичный сайт | https://kitchen.45-67-202-162.sslip.io |
| БД | data/app.db, WAL, каталог принадлежит пользователю сервиса |
| Настройки | /opt/kitchen-control/.env; systemd EnvironmentFile + dotenv |
| Static | Раздаёт FastAPI через /static; Caddy проксирует весь host |

Серверу нужны python3/venv, systemd, tar, curl, пользовательские права для настройки сервиса и работающий Docker/Caddy. Клиенту выкладки нужны Python, ssh/scp и доступ по существующему ключу с проверенным host key. Скрипт не устанавливает Docker, не покупает домен и не создаёт DNS-зону.

Для другого VPS сначала определите адрес доступного Caddy upstream и proxy IP, обновите service/snippet/install проверку host и PUBLIC_BASE_URL. Нельзя без проверки копировать 172.18.0.1/172.18.0.3 на другое окружение. В текущей схеме localhost хоста недоступен из Caddy-контейнера.

## Что делают скрипты

[push.py](../deploy/push.py) собирает архив app/static/templates/scripts/tests/deploy/docs и основных файлов зависимостей/README. Не отправляет data, .git, .venv и artifacts. Отдельно копирует локальный `.env`, затем распаковывает код и вызывает install.sh через SSH. **Локальный .env заменяет серверный**: перед обновлением сверяйте его актуальность приватно. Автоматической резервной копии приложения/SQLite этот скрипт не делает.

[install.sh](../deploy/install.sh):

1. Создаёт системного пользователя при отсутствии, выставляет права каталога и `.env`.
2. Создаёт/обновляет venv, устанавливает requirements-lock.txt.
3. Запускает seed от пользователя сервиса **без --reset**.
4. Выполняет unittest. При неуспехе выполнение останавливается; архив уже распакован, автоматического rollback кода нет.
5. Устанавливает systemd unit, проверяет его, daemon-reload, enable/start и restart только kitchen-control.
6. Ждёт локальный health и проверяет его ещё раз.
7. Если проектного virtual host ещё нет, сохраняет backup Caddyfile, добавляет snippet, выполняет validate/reload; при ошибке восстанавливает файл. Существующий блок при последующих выкладках автоматически не обновляется.

Выкладка выполняется с root-правами на сервере: скрипт не добавляет sudo к каждой операции. Она не атомарна и не обеспечивает zero downtime. На update возможен короткий перерыв.

## systemd и права

Точный unit — [kitchen-control.service](../deploy/kitchen-control.service). Требует Docker/network-online, один worker, `Restart=on-failure`, RestartSec=5, TimeoutStopSec=25, MemoryMax=220M. `UMask=0027`, NoNewPrivileges, PrivateTmp, ProtectSystem=strict, ProtectHome=true; запись разрешена в data. Access log Uvicorn отключён, Python output без буферизации.

Корень /opt/kitchen-control — root:kitchen-control, 750; `.env` — root:kitchen-control, 640; data — kitchen-control:kitchen-control, 750. Код принадлежит root. Публичный API не предоставляет файлового доступа к `.env`/SQLite. Backend не слушает внешний IP; прокси-заголовки доверяются только указанному Caddy IP.

## HTTPS и webhook

Текущий Caddy обслуживает 80/443 и получает сертификат host. Snippet включает gzip/zstd, request_body max_size 256KB и reverse_proxy. Общий Caddy содержит другие сайты; нельзя заменять весь файл проектным snippet.

В production `.env` задаются PUBLIC_BASE_URL с HTTPS, токен отдельного бота, webhook secret, coordinator ID, admin credentials и `ALLOW_LOCAL_HTTP=false`. Секреты не помещаются в unit, CLI URL, Git или screenshots.

После первичной настройки/изменения адреса или webhook secret, на сервере из корня проекта:

```bash
sudo -u kitchen-control .venv/bin/python -m scripts.manage webhook
sudo -u kitchen-control .venv/bin/python -m scripts.manage telegram-info
```

Обычная выкладка сама не вызывает setWebhook. Проверка getWebhookInfo не заменяет живой пользовательский E2E.

## Безопасное обновление production

### 1. Подготовить код

На рабочей машине, из клона с доступом к private origin:

```bash
git status --short
git switch main
git pull --ff-only
```

Если есть незавершённые локальные изменения, сначала разберите их; не сбрасывайте рабочее дерево. Запустите тесты и security scan по [TESTING.md](TESTING.md). На сервере не требуется Git clone: текущий deployment доставляется архивом.

### 2. Сохранить резервную копию

На сервере:

```bash
cd /opt/kitchen-control
stamp=$(date -u +%Y%m%dT%H%M%SZ)
sudo -u kitchen-control .venv/bin/python -m scripts.manage backup "data/before-update-$stamp.db"
sudo install -d -m 700 "/root/kitchen-backups/$stamp"
sudo tar -czf "/root/kitchen-backups/$stamp/code.tar.gz" app static templates scripts tests deploy docs README.md requirements-lock.txt
sudo cp -p .env "/root/kitchen-backups/$stamp/service.env"
```

Это приватные backup: не копируйте их в Git. Проверку и восстановление SQLite см. [OPERATIONS.md](OPERATIONS.md). Перед изменением reverse proxy также сохраните его конфигурацию; скрипт делает это лишь при добавлении отсутствующего host.

### 3. Доставить проверенную версию

На Windows-клиенте (подставьте сервер и путь существующего приватного ключа):

```powershell
.venv\Scripts\python deploy/push.py DEPLOY_USER@SERVER_HOST --key 'C:\PATH\TO\PRIVATE_KEY'
```

На Linux-клиенте замените путь Python на `.venv/bin/python`, ключ — на свой путь. StrictHostKeyChecking=yes требует уже проверенного known_hosts; не отключайте проверку ради успешной выкладки. Данные `.env` должны относиться именно к этому серверу и боту.

Не выполняйте reset/удаление data. У проекта нет универсальной команды migrate. Единственная отдельная коррекция — старой учебной даты КФ-2611 через scripts.correct_demo_dates, только если она применима и после backup; install.sh её не вызывает.

### 4. Проверить после обновления

```bash
sudo systemctl is-active kitchen-control
sudo systemctl is-enabled kitchen-control
curl -fsS http://172.18.0.1:18080/api/health
curl -fsS https://kitchen.45-67-202-162.sslip.io/api/health
sudo -u kitchen-control .venv/bin/python -m scripts.manage telegram-info
sudo -u kitchen-control .venv/bin/python -m scripts.manage outbox
```

Откройте сайт, нажмите «Обновить», проверьте admin и существующие события. При изменении Caddy: `docker exec caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile`, затем только адресный reload и проверка соседних сайтов. Без изменения Caddy его reload не нужен.

## Ручной restart и откат

```bash
sudo systemctl restart kitchen-control
sudo journalctl -u kitchen-control -n 80 --no-pager
```

Restart нужен при изменении Python/настроек; static читается с диска, но стандартный push всё равно перезапускает сервис. При изменении только документации достаточно Git commit/push — production restart не требуется.

Для отката сначала остановите только kitchen-control, восстановите проверенный архив кода и при необходимости зависимости/config, затем запустите сервис и health. SQLite не откатывайте автоматически вместе с кодом: можно потерять новые сообщения и действия. Восстановление БД — отдельная согласованная операция по [OPERATIONS.md](OPERATIONS.md). Общий VPS, Docker и Caddy ради отката этого приложения не перезапускаются.
