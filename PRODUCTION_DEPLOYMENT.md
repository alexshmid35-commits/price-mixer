# Price Mixer production profile

Профиль подготовлен для одного Linux-сервера с `systemd`, Gunicorn и nginx.
Это шаблон развёртывания; он не выполняет публикацию автоматически.

## Архитектурное ограничение

Текущая версия должна работать с одним Gunicorn worker. XLSX и загрузки
API-источников выполняются отдельным durable worker, а очередь и статусы этих
задач хранятся в SQLite. Часть коротких интерактивных mutation locks и
статусов пока остаётся в web-процессе, поэтому несколько Gunicorn workers
ещё не являются поддерживаемым профилем.

Профиль использует:

- `workers = 1`;
- `gthread`;
- четыре потока по умолчанию;
- bind только на `127.0.0.1:5001`;
- nginx как единственную внешнюю точку входа.

Масштабирование web-части на несколько workers допустимо после выноса
оставшихся интерактивных статусов и межпроцессных блокировок.

## Файлы профиля

- `wsgi.py` — WSGI entrypoint, проверка production env и миграции БД;
- `deploy/gunicorn.conf.py` — однопроцессный Gunicorn;
- `deploy/price-mixer.service` — шаблон systemd;
- `deploy/price-mixer-worker.service` — отдельный durable worker для XLSX и
  API-source jobs;
- `deploy/nginx-price-mixer.conf` — шаблон HTTPS reverse proxy;
- `deploy/price-mixer.env.example` — перечень переменных без секретов;
- `deploy/check_production.py` — fail-fast проверка конфигурации;
- `deploy/smoke_production.py` — безопасный post-start smoke через loopback;
- `deploy/backup_restore.py` — verified backup и restore dry-run;
- `deploy/scheduled_backup.py` и `price-mixer-backup.{service,timer}` —
  ежедневный verified backup без secrets и без автоматического удаления;
- `requirements-prod.txt` — runtime/test зависимости плюс Gunicorn.

Gunicorn `26.0.0` требует Python 3.10 или новее; для проекта рекомендуется
Python 3.11.

## Подготовка каталога

Пример целевых путей:

```text
/opt/price-mixer/current
/etc/price-mixer/price-mixer.env
/etc/price-mixer/google-service-account.json
```

До первого запуска:

1. Создать отдельного системного пользователя `price-mixer`.
2. Скопировать код в `/opt/price-mixer/current`.
3. Создать Python 3.11 virtualenv.
4. Установить `requirements-prod.txt`.
5. Дать пользователю сервиса права на текущий runtime layout.
6. Сделать backup согласно `RUNTIME_LAYOUT.md`.

Команды и правила проверки backup: [BACKUP_RESTORE.md](./BACKUP_RESTORE.md).
Операции очереди и worker: [WORKER_OPERATIONS.md](./WORKER_OPERATIONS.md).

Production service монтирует каталог кода read-only и разрешает запись только
в отдельные state/data/cache/uploads/logs пути из `RUNTIME_LAYOUT.md`.
Существующие legacy-файлы копируются инструментом миграции только после
backup и остановки сервиса; автоматически они не удаляются.

## Конфигурация

Скопировать `deploy/price-mixer.env.example` в защищённый
`/etc/price-mixer/price-mixer.env`, заменить placeholders и выставить права,
доступные только root и группе сервиса.

Обязательные условия:

- `PRICE_MIXER_ENV=production`;
- `PRICE_MIXER_WORKERS=1`;
- `PRICE_MIXER_BIND` использует loopback или Unix socket;
- `ADMIN_PASSWORD` содержит не менее 12 символов;
- `FLASK_SECRET_KEY` содержит не менее 32 символов;
- пароль администратора и Flask secret различаются.

Проверка не печатает значения секретов:

```bash
/opt/price-mixer/current/.venv/bin/python deploy/check_production.py
```

## systemd

После проверки путей в шаблоне:

```bash
sudo install -m 0644 deploy/price-mixer.service /etc/systemd/system/price-mixer.service
sudo install -m 0644 deploy/price-mixer-worker.service /etc/systemd/system/price-mixer-worker.service
sudo install -m 0644 deploy/price-mixer-backup.service /etc/systemd/system/price-mixer-backup.service
sudo install -m 0644 deploy/price-mixer-backup.timer /etc/systemd/system/price-mixer-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now price-mixer-worker price-mixer
sudo systemctl enable --now price-mixer-backup.timer
sudo systemctl status price-mixer
curl --fail http://127.0.0.1:5001/api/health
/opt/price-mixer/current/.venv/bin/python deploy/smoke_production.py
```

Логи:

```bash
journalctl -u price-mixer -f
journalctl -u price-mixer-worker -f
```

Приложение пишет структурированные JSON-логи при
`PRICE_MIXER_LOG_FORMAT=json`. Каждый HTTP-ответ содержит `X-Request-ID`;
тот же идентификатор присутствует в access/error log и помогает собрать
события одного запроса. Query string и заголовок Authorization в access log
не записываются, а типовые значения паролей, токенов и API-ключей маскируются.
`/api/health` и статические файлы исключены из access log, чтобы не создавать
шум. Дублирующий Gunicorn access log отключён, а nginx использует безопасный
формат на основе `$uri` без query string. Уровень регулируется через
`PRICE_MIXER_LOG_LEVEL`.

Для первичной диагностики без выгрузки пользовательских данных:

```bash
/opt/price-mixer/current/.venv/bin/python deploy/diagnostics.py \
  /tmp/price-mixer-diagnostics.zip
```

Состав и privacy-ограничения описаны в
[DIAGNOSTICS.md](./DIAGNOSTICS.md).

Не запускать параллельно старый `app.py`, watchdog или второй Gunicorn на том
же каталоге.

## nginx и TLS

Перед установкой шаблона заменить `price-mixer.example.com` на реальный домен
и подготовить сертификат.

```bash
sudo nginx -t
sudo systemctl reload nginx
curl --fail https://REAL_DOMAIN/api/health
```

nginx принимает загрузки до `200m`, совпадая с лимитом Flask. Длинные
таймауты оставлены для тяжёлых операций. Доступ к интерфейсу дополнительно
защищён HTTP Basic Auth приложения, поэтому внешний доступ разрешается только
через HTTPS.

## Smoke-проверка

После запуска проверить:

1. `/api/health` без авторизации;
2. `401` на `/` без авторизации;
3. вход с production credentials;
4. небольшой upload и создание сводного прайса;
5. ручной выбор ID и review queue;
6. category visibility/markup/override;
7. Excel export;
8. журналы systemd/nginx без traceback.

Полную тяжёлую проверку на 30 000 строках выполнять только после малого smoke.

## Обновление

Безопасный порядок:

1. backup durable state и `onliner_products.db`;
2. развернуть новую версию в отдельный каталог;
3. установить зависимости;
4. выполнить unit-тесты и production env check;
5. остановить сервис;
6. переключить `current`;
7. запустить сервис и выполнить smoke;
8. сохранить предыдущий release до завершения приёмки.

## Rollback

Если health или smoke не проходит:

1. остановить `price-mixer`;
2. вернуть ссылку/каталог `current` на предыдущий release;
3. восстановить state/DB только если новая версия успела изменить их формат;
4. запустить сервис;
5. проверить `/api/health` и контрольный малый прайс.

Нельзя выполнять автоматический rollback файлов state без проверки версии и
целостности backup.
