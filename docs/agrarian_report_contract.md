# Аграрный колледж: контракт отчёта (этап анализа)

Срез: 14.11.2026. Только чтение production БД; сборка `build_student_month_report` внутри транзакции `READ ONLY`. Файлы `report.py`, `models.py`, `report_queue.py` совпали с развёрнутым контейнером по SHA-256. Задания, отправки, Dify и Meta не менялись.

## Фактический путь

1. `frontend/src/pages/ReportConversationsPage.jsx:258` вызывает `buildManualReportRequest` (`frontend/src/lib/manualReportRequest.js`). POST `/api/reports/send-all/`: `organization="college"`, `college_branch="agrarian"`, `month="YYYY-MM"`, `confirm_retry_failed` и, по режиму, `group_ids` либо `student_ids`. `frontend/src/lib/api.js:105` добавляет `X-Organization-Type: college` и `X-College-Branch: agrarian`.
2. `organization_for_request` и `college_branch_for_request` (`organization.py`) проверяют заголовки и доступ. Без заголовка ветка по умолчанию Kuwait; тело должно совпасть с заголовками. `ForceSendAllReportsAPIView.post` (`views.py:1177`) проверяет ADMIN, сериализатор, организацию и ветку. `ensure_route_configured("agrarian")` требует `DIFY_AGRARIAN_API_KEY` **до** создания batch. Отсутствие ключа оставляет отправку заблокированной.
3. `enqueue_monthly_report_batch` (`report_queue.py:44`) фильтрует `StudentProfile.organization_type`, `college_branch`, первичную `group_id` и `student_ids`; проверяет архив и фактическую активность, route, историю dispatch и параллельные задания. Сохраняет batch `requested_filters.workflow_route`, `college_branch`, `group_ids`, `student_ids`; item содержит студента, месяц и хеш дедупликации. Снимка отчёта при постановке нет: данные собираются позднее worker.
4. `process_report_batch_item` (`report_queue.py:300`) берёт сохранённый route, вызывает `send_student_month_report(..., bypass_schedule=True, expected_workflow_route=...)`. `report.py:565` вновь проверяет route/историю, строит `build_student_month_report`, затем сохраняет payload в dispatch и attempt до `run_dify_workflow`. `build_dify_inputs` передаёт Dify поля ниже; `user` формируется из студента/месяца (`build_dispatch_user_key`). Это потенциальное изменение данных между постановкой и обработкой.

## Оценки и период

Одна оценка — одна строка `LessonRecord`: `student`, `lesson`, `grade`, `comment`, `author`, `sequence`, `created_at`, `updated_at`. `Lesson` содержит `group`, `lesson_date`, `topic`; отдельной даты у оценки нет. Уникальна тройка `(student, lesson, sequence)`, количество оценок на занятие не ограничено тремя. API аграрных оценок (`AgrarianGradeRecordSerializer`, `AgrarianGradeRecordViewSet`) принимает `score` → `grade`, `student`, предметную `group`, `date`, `comment`; создание назначает следующий `sequence`. Значения: `5`, `4`, `3`, `2`, `Н`. `Н` — явный пропуск; пустого допустимого значения формы нет. Отсутствующая запись означает отсутствие отметки, а не ноль и не пропуск.

Импорт `import_college_seed.py:76,464` связывает ячейку с датой заголовка, создаёт `LessonRecord` только при достоверной дате, студенте, группе и допустимом значении. Пустые/дефисные ячейки остаются без оценки; неоднозначные, недатированные и конфликтующие ячейки хранятся в `ImportedGradeCell` с причиной и не входят в отчёт. Для старой схемы импорта непустое значение вне `2`–`5` нормализуется в `Н`; это ограничение интерпретации исторического источника.

`get_student_report_groups(student, month)` берёт предметы из `college_groups` и первичную `group`, проверяя организацию/ветку. Архивная группа включается, если архивирована не раньше первого дня месяца и имеет урок в месяце. Архивный студент/основная группа требуют месячной записи (`student_has_month_report_activity`); архив до начала месяца исключается. `get_month_lessons_for_student` и `get_month_records_for_student` фильтруют по `Lesson.lesson_date` от первого до последнего дня включительно. Поэтому датированные `LessonRecord` позволяют достоверно сформировать месячный отчёт по занятиям. Недатированные итоговые оценки из иных источников приписывать октябрю нельзя.

## Фактический payload

| Поле | Источник, тип и смысл | При отсутствии |
|---|---|---|
| `organization`, `college_branch`, `workflow_route` | строки из `StudentProfile` и `workflow_route_for_student`; всегда `college/agrarian/agrarian` | несоответствие ветки останавливает сборку |
| `student.id`, `user_id`, `full_name`, `username` | ID/строки `StudentProfile` и `User`; ФИО студента | строки могут быть пустыми, отдельной проверки нет |
| `student.parent_name`, `parent_phone` | строки `StudentProfile`; получатель и номер родителя, не студента | имя может быть `""`; номер должен быть заполнен моделью, при ошибке отдельной блокировки в сборщике нет |
| `group`, `main_group`, `groups`, `subjects` | первичная предметная группа, основная колледжная группа, список предметов; `subjects[].grade_counts` по `5/4/3/2` | `main_group.name=""` при отсутствии; `groups/subjects=[]` при отсутствии подходящих групп |
| `mentor` | первичный наставник: ID, ФИО, username, email | email может быть `""` |
| `period` | `month`, границы, `last_lesson_date`, `generated_at`; строки ISO | `last_lesson_date=null` без уроков |
| `lessons[]` | строка на **каждую оценку** с `record_id`, `lesson_id`, `group_id/name`, датой урока, темой, оценкой, комментарием, автором, status | для урока без записей синтезируется строка `grade=""`, `status="unmarked"` |
| `summary` | числа уроков, отмеченных/неотмеченных уроков, посещений, пропусков, числовых оценок, среднего и сумм `2`–`5`; `grades[]` | при отсутствии оценок среднее `0`, что неотличимо от вычисленного значения без контекста `numeric_grades_count` |
| `subjects[].absence_dates`, `absence_dates` | уникальные даты строк с `status="absent"` | пустые массивы |
| `message_text` | текущий общий текст колледжа из `format_college_parent_message` | всегда формируется для колледжа; не аграрный formatter |

`build_dify_inputs` передаёт `report` целиком и плоские `student_name`, `recipient_name`, `recipient_phone`, `group_name`, `mentor_name`, `month`, `average_grade`, `attendance_count`, `absence_count`, `total_five/four/three/two`, `attendance_rate`, `message_text`. `report` содержит route, но плоского `workflow_route` нет. Batch/item/attempt ID в Dify inputs не включены; корреляция выполняется сохранёнными batch/item/dispatch/attempt и Dify `user`, а не явным входом.

Посещаемость считается **на урок**, не на оценку: хотя бы одна числовая оценка означает посещение; `Н` без числовой оценки — один пропуск; отсутствие всех строк — один неотмеченный урок. `summary.absence_count` не удваивает несколько `Н` одного урока. Но `summary.total_*` считают строки оценок, а `subjects[].absence_dates` и общий `absence_dates` сворачивают даты; несколько уроков в день могут выглядеть как одна дата. Строки `lessons[]` при смеси `Н` и числа сохраняют `status="absent"` для `Н`, хотя урок в итоговом счётчике посещён; это требует явной политики formatter.

Read-only срез октября 2026: 104 аграрных студента, 4 860 `LessonRecord` с датой урока в октябре. Распределение числа **предметов в месячной выборке**: 1 предмет — 1 студент; 4 предмета — 103 студента. Это свойства текущих данных, не лимит для аграрного маршрута. Обезличенные реальные сборки находятся в [agrarian_report_examples.json](agrarian_report_examples.json): `full` означает наиболее заполненный найденный отчёт **без пропусков**, но у него 19 неотмеченных уроков; полностью отмеченного кандидата не найдено. `missing_grades` имеет 70 неотмеченных уроков; `absences` — 55 явных пропусков. Примеры заменяют ФИО, ID, автора/комментарии, текст сообщения и маскируют телефон.

## Dify, доступное только на чтение

В локальной Dify БД найдено приложение `agro.ai`, ID `5805ac6e-d16a-4dae-92b3-5430c8188edf`, опубликованный workflow ID `68feeddd-d9b8-45f9-859c-87185d985818`, draft ID `e3f4ae5a-d12c-410f-bc07-952809bb60e9`. Его входы: `user_message`, `user_image`, `weather_data`, `chat_history`, `lang` (обязателен), `weather_forecast`, `country` (обязателен), `location`, `regulations`, `soil_analysis`, `document_text`, `product_scheme`, `crop_stats`, `field_data`. Это приложение о растениях/погоде, его связь с отчётами не установлена. Отчётное Dify-приложение аграрного колледжа по имеющимся признакам не идентифицировано; для последующего этапа нужен подтверждённый app ID.

## Предлагаемые изменения (не реализованы)

1. Подтвердить точный ID отчётного Dify-приложения и его Start-входы; согласовать аграрный formatter и BODY Meta с явной картой параметров, не используя `agro.ai` по сходству названия.
2. Зафиксировать семантику смешанных `Н` и числовых оценок одного урока, нескольких уроков в один день и неполных отметок; formatter должен показывать `unmarked` отдельно от пропуска и не превращать отсутствие оценок в нулевой результат.
3. Для надёжной корреляции добавить в будущий контракт явные `batch_id`, `item_id`, `dispatch_id`, `attempt_id` и версию схемы; решить, нужен ли неизменяемый snapshot при постановке. Не включать персональные ID/номер в публичные примеры.
4. Проверить качество родительских имён/телефонов и недатированных импортных ячеек перед разрешением отправки. Не ограничивать аграрный маршрут четырьмя предметами. Сохранить текущие Academy/Kuwait route и заблокированный аграрный send gate до отдельного разрешения.
