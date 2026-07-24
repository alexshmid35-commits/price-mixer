# Контекст рабочей сессии Price Mixer — 2026-07-24

Это актуальная точка восстановления. Сначала прочитать этот файл, затем
[REMAINING_WORK.md](./REMAINING_WORK.md). История предыдущего этапа сохранена
в [SESSION_CONTEXT_2026-07-23.md](./SESSION_CONTEXT_2026-07-23.md).

Секреты, пароли и содержимое `.env` здесь не записывались.

## Итог этапа 1–6

Шесть пунктов технического плана выполнены в коде:

1. Рабочие события внешних API, загрузки прайсов, фоновых задач, XLSX,
   supplier diff и Google export переведены на общий структурированный logger.
   Request/job ID проходят через web и worker-контуры.
2. Добавлен ежедневный verified backup:
   `deploy/price-mixer-backup.service`, `.timer` и `scheduled_backup.py`.
   Backup проверяет manifest/хэши и не удаляет старые копии автоматически.
3. Добавлены отдельные state/data/cache/uploads/logs каталоги, централизованные
   runtime paths и безопасная copy-only миграция без удаления/перезаписи
   исходников.
4. Добавлена SQLite durable queue и отдельный worker service. В него вынесены
   coalesced XLSX jobs и API-source downloads; есть atomic claim, lease
   recovery, heartbeat, retries, dedupe и ограниченная очистка успешной
   истории. Validate/verify уже выполняются изолированными subprocess workers.
5. Добавлен изолированный Playwright E2E на `127.0.0.1:5011`. Он запускает
   отдельные web+worker, использует только `test-results/e2e-runtime` и
   синтетический CSV, проверяет health/version/request ID/auth/worker,
   upload, stats и XLSX download.
6. Усилен deploy-ready контур: runtime/SQLite preflight,
   `deploy/smoke_production.py`, порядок запуска systemd, worker hardening,
   инструкции E2E/production smoke и актуализированный runbook.

## Контрольные результаты

```text
763 passed in 11.50s
3 Playwright E2E passed
production smoke: 4/4 passed на изолированном web+worker
local smoke: 4/4 passed на актуальном процессе 127.0.0.1:5001
compileall: passed
```

Ruff в локальном virtualenv не установлен, поэтому отдельно не запускался;
это не потребовало загрузки новых пакетов. Python tests, compileall и E2E
прошли.

После создания и проверки backup локальный сервер повторно запущен на
`http://127.0.0.1:5001`. Локальный smoke прошёл `4/4`. Локальный профиль
использует прежний inline background режим; production-профиль требует
отдельный durable worker.

## Основные новые файлы

- `price_mixer/runtime_paths.py`
- `price_mixer/services/runtime_migration.py`
- `price_mixer/services/backup_schedule.py`
- `price_mixer/services/durable_jobs.py`
- `price_mixer/services/preflight.py`
- `price_mixer/workers/durable_worker.py`
- `deploy/migrate_runtime_layout.py`
- `deploy/scheduled_backup.py`
- `deploy/smoke_production.py`
- `deploy/price-mixer-worker.service`
- `deploy/price-mixer-backup.service`
- `deploy/price-mixer-backup.timer`
- `WORKER_OPERATIONS.md`
- `E2E_PREFLIGHT.md`

## Deployment-продолжение 2026-07-24

Пользователь подтвердил успешную ручную приёмку пунктов 1–6 и дал явную
команду продолжать deployment-этап.

Выполнено:

- создан первый verified backup пользовательских state/DB:
  `backups/verified-2026-07-24T0845`;
- backup содержит 13 manifest-объектов, занимает 761,57 МБ и не содержит
  `.env` или Google service-account;
- отдельная команда `verify` успешно проверила 13/13 объектов, SHA-256 и
  SQLite `quick_check`;
- успешно построен restore-plan для всех 13 объектов;
- dry-run copy-only migration успешно построил 13 операций: 12 state-файлов
  и `onliner_products.db`; `source_files_removed=false`.

Реальная copy-only migration и установка production-служб не запущены,
поскольку в рабочем каталоге нет адреса целевого Linux-сервера, SSH-профиля
или реального домена. Шаблон nginx всё ещё содержит
`price-mixer.example.com`. Локальная копия в `C:\tmp` не создавалась, чтобы
не подменять ею миграцию на целевую машину.

Пользователь уточнил, что пока работа продолжается только на localhost.
Linux deployment, systemd/nginx/TLS и перенос runtime в production-пути
отложены до отдельной команды.

## Что не выполнялось до команды на deployment

- Реальный большой backup пользовательской БД до этого этапа не запускался.
- Runtime-миграция пользовательских файлов до этого этапа не выполнялась.
- Production-сервер, nginx, systemd и внешнее backup-хранилище не изменялись:
  доступа к целевой машине не было.
- Не вызывались реальные внешние API в E2E.
- Пользовательские state/upload/DB не удалялись и не перезаписывались.

## Точный следующий шаг

Продолжать локальное тестирование на `http://127.0.0.1:5001`. Когда будет
принято решение о Linux deployment, получить адрес/имя сервера, способ
SSH-доступа и реальный домен; затем проверить машину и выполнить migration
plan с реальными путями.
