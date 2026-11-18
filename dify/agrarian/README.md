# Аграрный workflow

Приложение Dify: `a67fd500-51ca-486a-9088-7b9bda934563`. Production-маршрут не включён. `AGRARIAN_SEND_ENABLED=false` должен сохраняться в draft и опубликованной версии.

## Форматтер

`formatter.py` использует буквальный BODY сохранённого подтверждённого шаблона Кувейта `student_monthsly_send_v5`, `ky_KG`; файл источника находится в `dify/kuveit/meta_body.user_provided.txt`. Новый Meta-шаблон не требуется. Параметры: 1 группа, 2 студент, 3 период, 4–8 / 9–13 / 14–18 / 19–23 четыре предмета с числом оценок 5/4/3/2, 24 сведения о занятиях. Для отсутствующего предмета все пять значений — `—`; параметр 24 объясняет эти знаки. Более четырёх предметов дают ошибку вместимости. Для существующего предмета нули означают подсчитанное отсутствие числовых оценок.

Расчёт собирает все LessonRecord по `(group_id, lesson_id)` и сохраняет `lesson_details`. Каждое занятие классифицируется как `graded`, `absent` (только Н), `mixed` (Н и число) или `unmarked`; последним двум статус пропуска не приписывается. Число `graded` остаётся в snapshot, а не в параметре под заголовком «Сабактан калуулар». Полный BODY, порядок и однострочные значения проверяются до выдачи 24 параметров.

`code_node.py` содержит самодостаточный Code-узел; `workflow_graph.json` содержит подготовленный граф. `prepare_graph.py` воспроизводит их из read-only скелета. [Обезличенные полные предпросмотры](../../docs/agrarian_formatter_previews.json) построены по трём локальным примерам. Они не подменяют проверку всех 103 production payload. Студент 236 остаётся отдельным исключением.

## Проверка 18 ноября 2026

`audit_payloads.py` проверил read-only поток всех 104 октябрьских сборок из production backend: 103 готовых payload прошли, единственный `skipped` — студент 236. Проверены порядок 24 параметров, самостоятельный пересчёт всех числовых LessonRecord, категории 3 601 `graded`, 1 005 `absent`, 9 `mixed`, 2 747 `unmarked`, сохранность `lesson_details`, однострочность и точная подстановка в BODY. Максимальная длина с фактическими ФИО — 832 символа. Ошибок вместимости или локального ограничения 1024 символа нет. Предел 1024 — локальный guard, а не объявленное ограничение Meta. Персональные данные и телефоны проверка не печатает.

GraphEngine mock-аудит пройден в `docker_ssrf_proxy_network` с `CODE_EXECUTION_ENDPOINT=http://sandbox:8194`. Причиной прежней недоступности был DNS: имя `sandbox` не разрешалось в `docker_default`. Работающие сервисы не менялись. Gate=false дал ноль HTTP; accepted, HTTP 400, timeout, ответ без ID и сбой callback после accepted дали по одному mock Meta и callback вызову. Meta не повторялся. В графе по-прежнему `AGRARIAN_SEND_ENABLED=false`.

## Guarded publication

`publish_checked.py` изменяет только приложение `a67fd500-51ca-486a-9088-7b9bda934563`. Он сверяет текущие настройки отправителя с приватным проверенным снимком, берёт непустые Meta URL/authorization от текущего опубликованного отправителя, callback URL из его действующего HTTP-узла и callback token из backend. Значения не выводятся. Скрипт проверяет tenant, draft ID, исходный граф, типы и ID переменных, сохраняет и перечитывает draft, затем публикует через console API и повторно проверяет граф, gate и отсутствие workflow runs. Существующие секреты и ID переменных должны сохраняться; любое расхождение останавливает запись.

Сохранённая console-сессия на 18 ноября возвращала HTTP 401. Для запуска после локальных проверок нужен скрытый ввод через `enter_console_session.sh`. До успешного запуска `publish_checked.py` опубликованного аграрного workflow нет; пустые значения в текущем draft не считаются настроенными.

Локальные тесты: `PYTHONPATH=dify/agrarian python3 -m unittest dify/agrarian/test_formatter.py -q`. GraphEngine mock: `docker run --rm --network docker_ssrf_proxy_network --entrypoint python -v /root/MWTabel:/audit:ro -e PYTHONPATH=/app/api -e CODE_EXECUTION_ENDPOINT=http://sandbox:8194 langgenius/dify-api:1.14.2 /audit/dify/agrarian/runtime_audit.py`.
