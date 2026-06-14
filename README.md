# Tabel

Учебная система для ведения групп, студентов, менторов, табеля, оценок, посещаемости и ежемесячных отчетов родителям.

Проект состоит из:

- backend: Django + Django REST Framework;
- frontend: React + Vite;
- база данных в production: PostgreSQL;
- авторизация: JWT;
- отправка отчетов: Dify Workflow API;
- production-запуск: Docker, Gunicorn, Nginx.

## Возможности

- Роли пользователей: администратор, ментор, студент.
- Управление группами, менторами и студентами.
- Месячный табель по группе.
- Оценки `5`, `4`, `3`, `2` и отметка пропуска `Н`.
- Расчет среднего балла и посещаемости.
- Личный кабинет студента только со своими данными.
- Ежемесячные отчеты родителям через Dify.

## Главное правило отчетов

Отчет по студенту отправляется на номер родителя из поля `parent_phone`.

Отчет можно отправить только при выполнении всех условий:

- наступил последний учебный день группы в выбранном месяце;
- для студента на последнем уроке месяца уже стоит оценка или пропуск;
- за этот месяц по этому студенту еще нет успешной отправки.

Отчет не должен отправляться в начале следующего месяца. Повторная успешная отправка одного и того же отчета запрещена.

История отправок хранится в модели `MonthlyStudentReportDispatch`. Уникальность пары `(student, month)` защищает от дублей.

## Важные файлы

- `tabel_project/tabel_app/models.py` - модели пользователей, групп, уроков, оценок и отправок отчетов.
- `tabel_project/tabel_app/report.py` - сбор месячного отчета, проверка даты отправки, защита от дублей, отправка в Dify.
- `tabel_project/tabel_app/views.py` - API, права доступа, сохранение табеля.
- `tabel_project/tabel_app/scheduler.py` - автоматическая проверка отчетов.
- `tabel_project/tabel_app/management/commands/send_monthly_reports.py` - ручной запуск отправки отчетов.
- `frontend/src` - React-приложение.

## Локальный запуск backend

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-local.ps1 -SeedDemo
```

Backend будет доступен по адресу:

```text
http://127.0.0.1:8000/
```

API-информация:

```text
http://127.0.0.1:8000/api-info/
```

## Локальный запуск frontend

Нужен установленный Node.js и npm.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-frontend-local.ps1
```

Frontend будет доступен по адресу:

```text
http://127.0.0.1:5173/
```

## Проверки

Backend:

```powershell
$env:DB_ENGINE='sqlite'
python tabel_project\manage.py test tabel_app
```

Frontend:

```powershell
cd frontend
npm run lint
npm run build
```

## Ручная отправка отчетов

Обычная проверка отчетов за текущий месяц:

```powershell
python tabel_project\manage.py send_monthly_reports
```

Полезные варианты:

```powershell
python tabel_project\manage.py send_monthly_reports --dry-run
python tabel_project\manage.py send_monthly_reports --date 2026-04-30
python tabel_project\manage.py send_monthly_reports --month 2026-04
python tabel_project\manage.py send_monthly_reports --student-id 5
python tabel_project\manage.py send_monthly_reports --group-id 1
```

Важно: ручной запуск тоже не должен отправлять отчет раньше или позже последнего учебного дня месяца.

## Переменные окружения

Минимально важные переменные для production:

- `SECRET_KEY`
- `DEBUG=False`
- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- `DB_ENGINE=postgresql`
- `DB_USER`
- `DB_POSTGRES`
- `DB_PASSWORD`
- `DB_HOST`
- `DB_PORT`
- `TIME_ZONE=Asia/Bishkek`
- `AUTO_MONTHLY_REPORTS=True`
- `DIFY_API_KEY`
- `DIFY_API_URL`
- `DIFY_RESPONSE_MODE=blocking`
- `DIFY_TIMEOUT_SECONDS=30`

Секреты нельзя хранить в репозитории.

## Production

Docker-файлы уже есть в проекте:

- `Dockerfile`
- `docker-compose.yml`
- `docker/nginx/default.conf`
- `docker/entrypoint.sh`

Запуск:

```bash
docker compose up --build -d
```

Логи:

```bash
docker compose logs -f web
docker compose logs -f nginx
```

Создание администратора:

```bash
docker compose exec web python manage.py createsuperuser
```

## Demo-аккаунты

После запуска seed-команды:

- `admin_demo / admin12345`
- `mentor_demo / mentor12345`
- `student_demo_1 / student12345`
- `student_demo_2 / student12345`

## Лицензия

MIT.
