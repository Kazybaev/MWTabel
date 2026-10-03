# Ручная очередь ежемесячных отчётов

Эта процедура разделяет восстановление старой очереди B3–B7 и постоянную
работу кнопки. Она не разрешает отправки сама по себе. Пакеты для обработки,
отмены или сохранения без изменений выбирает оператор, а не runbook.

Во всех фазах остаются выключенными:

```text
AUTO_MONTHLY_REPORTS=false
REPORT_SCHEDULER_RUN_ON_START=false
```

Сохранение оценки и запуск web не создают отправку. Новое ручное задание
создаётся только POST-запросом кнопки и обрабатывается отдельным worker.

## Фаза 0. Развёртывание без отправок

1. Зафиксировать утверждённые commit/image, состояние Compose и migration plan.
2. Сделать свежий приватный dump, записать checksum и восстановить dump в
   отдельной PostgreSQL-базе.
3. На восстановленной базе проверить переход с `0017` на `0018`, числа и
   статусы очереди. Миграция не должна удалять задания или менять их статусы.
4. Развернуть web/nginx с обоими worker выключенными:

```text
REPORT_WORKER_ENABLED=false
REPORT_LEGACY_QUEUE_REVIEWED=false
```

5. Применить только согласованную миграцию и проверить web/nginx. Обычный
   worker при `REPORT_LEGACY_QUEUE_REVIEWED=false` завершится до захвата задания.

`0018` помечает все существовавшие элементы как `requires_operator_review`.
Обычный worker такие элементы не захватывает. Одинаковые активные элементы
старых B5/B6 сохраняются оба: первый получает канонический dedupe-ключ, второй —
детерминированный legacy-ключ. Поэтому partial unique constraint создаётся без
удаления, выбора пакета или изменения статусов.

## Фаза 1. Разовое восстановление B3–B7

Сначала зафиксировать явное решение для каждого точного batch ID: отменить,
обработать или оставить без изменений. Отдельно согласовать B5/B6. До этого
обычный worker не запускать и `REPORT_LEGACY_QUEUE_REVIEWED` не менять.

### Отмена только оставшихся queued

Read-only dry-run:

```bash
python manage.py cancel_report_batches --batch-ids <ID> [<ID> ...]
```

После отдельного подтверждения тех же ID:

```bash
python manage.py cancel_report_batches --batch-ids <ID> [<ID> ...] --apply
```

Отмена блокирует строки заданий и меняет только оставшиеся `queued` на
`cancelled`. `processing`, `pending`, `accepted`, `delivered`, `failed`,
`skipped`, dispatch и attempt сохраняются. Если worker успел захватить строку
первым, она остаётся `processing`, а остальные queued отменяются. Если отмена
заблокировала строки первой, worker использует `SKIP LOCKED` и их не захватывает.
Результат dry-run содержит `will_cancel` и `will_preserve`.

### Одноразовая обработка явно выбранных старых пакетов

Только после отдельного разрешения реальных отправок:

```bash
REPORT_WORKER_ENABLED=true \
REPORT_WORKER_MODE=recovery \
REPORT_RECOVERY_BATCH_IDS=<ID>[,<ID>...] \
docker compose --profile report-recovery run --rm --no-deps report-recovery-worker
```

Recovery-worker требует точные существующие ID, работает с `--once`, имеет
`restart: "no"` и не захватывает другие пакеты. После каждой операции повторно
сверить `queued`, `processing`, `accepted`, `delivered`, `failed`, `skipped` и
`cancelled`. `accepted` означает только принятие Meta, не доставку.

## Фаза 2. Постоянная работа кнопки

Эта фаза разрешена только после документированного разбора всех 452 старых
queued-заданий B3–B7. После отдельного согласования выставить startup-gate:

```text
REPORT_WORKER_ENABLED=true
REPORT_LEGACY_QUEUE_REVIEWED=true
```

Затем один раз запустить постоянный сервис:

```bash
docker compose --profile reports up -d report-worker
```

`report-worker` имеет `restart: unless-stopped`, при пустой очереди ждёт и берёт
только новые элементы с `requires_operator_review=false`. После этого обычный
сценарий не требует batch ID или терминальной команды: администратор нажимает
кнопку, backend создаёт пакет, уже работающий worker его обрабатывает, frontend
polling показывает состояние до терминального результата.

## Проверка финального состояния

- web и nginx healthy;
- ровно один постоянный `report-worker` работает;
- `AUTO_MONTHLY_REPORTS=false` и `REPORT_SCHEDULER_RUN_ON_START=false`;
- recovery-worker отсутствует;
- сохранение оценки и старт приложения не создают задания;
- новый пакет кнопки переходит `queued` -> `processing` -> терминальный статус;
- `accepted` отображается отдельно от `delivered`; «доставлено» показывается
  только для статуса/counter `delivered`;
- для `accepted`, `pending` и спорных ошибок нет автоматической повторной
  отправки.
