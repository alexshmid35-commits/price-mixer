# Price Mixer — оставшаяся приёмка и deployment

Дата фиксации: 2026-07-24

## Технический статус

Пункты 1–6 текущего плана реализованы и автоматически проверены:

- observability внешних API и background jobs;
- ежедневный verified backup schedule;
- физическое разделение code/runtime и copy-only migration;
- SQLite durable queue и отдельный worker;
- изолированный E2E/preflight;
- deploy-ready systemd/nginx/runbook/smoke контур.

Контроль: `763 passed`, `3 E2E passed`, production smoke `4/4`.

## Ручная приёмка

Ручная проверка на небольшом реальном прайсе завершена пользователем
2026-07-24. Подтверждены:

1. вход и загрузку файла;
2. количество строк/поставщиков и товары с/без Onliner ID;
3. ручной выбор/очистку ID и review queue;
4. N-Tech проверки и карточки отчётов;
5. visibility/override/наценку категории;
6. скачивание итогового XLSX;
7. при необходимости — экспорт Google Sheets и API-источник с реальными
   настройками.

E2E-порт 5011 поднимается только на время `npm run test:e2e` и затем
останавливается.

## Deployment-этап

Выполнено 2026-07-24:

- создан `backups/verified-2026-07-24T0845`;
- backup содержит 13 manifest-объектов state/DB, занимает 761,57 МБ;
- независимый `verify` проверил 13/13 объектов, SQLite `quick_check` и хэши;
- restore-plan успешно построен;
- `.env` и Google service-account в backup не включены;
- dry-run copy-only migration успешно построил 13 операций без удаления
  исходников.

Пользователь уточнил, что пока приложение продолжает работать только локально
на `http://127.0.0.1:5001`. Сервер повторно запущен после backup; локальный
smoke прошёл `4/4`. Миграция runtime в production-пути, systemd, nginx и TLS
отложены до отдельной команды на Linux deployment.

После появления целевого Linux-сервера останется:

1. получить и проверить адрес сервера, SSH-доступ и реальный домен;
2. подготовить каталоги и права;
3. повторить dry-run с Linux-путями и выполнить copy-only migration;
4. установить env/secrets вне каталога кода;
5. установить и включить web, durable worker и backup timer services;
6. проверить nginx/TLS, `deploy/check_production.py` и
   `deploy/smoke_production.py`;
7. провести малый реальный smoke, затем тяжёлый контрольный прайс;
8. зафиксировать rollback release и внешнее защищённое хранение backup.

Не подставлять вместо реальных реквизитов шаблонные
`price-mixer.example.com` и `/opt/price-mixer/current`. Перед продолжением
проверить целевую машину и пути.
