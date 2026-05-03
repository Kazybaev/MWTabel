# Tabel

<p align="center">
  <img src="./assets/motion-community-logo.jfif" alt="Motion Community" width="180" />
</p>
<p align="center">
  Команда Motion Community
</p>

<p align="center">
  Учебная система для табеля, оценок, посещаемости и ежемесячных отчётов студентов.
</p>

## О проекте

`Tabel` — это веб-система для учебных центров и IT-школ, где:

- администратор управляет группами, менторами и студентами;
- ментор ведёт табель группы и выставляет оценки по дням;
- студент видит только свои оценки, средний балл и посещаемость;
- отчёты за месяц можно отправлять через `Dify`.

Стек проекта:

- `React + Vite` — frontend;
- `Django + Django REST Framework` — backend и API;
- `PostgreSQL` — production-база данных;
- `JWT` — авторизация;
- `Docker + Nginx + Gunicorn` — production-развёртывание.

## Что умеет система

- роли `ADMIN`, `MENTOR`, `STUDENT`;
- управление группами;
- управление студентами;
- управление менторами;
- месячный табель с оценками по датам;
- учёт посещаемости;
- расчёт среднего балла;
- личный кабинет студента;
- ежемесячные отчёты по студентам через `Dify`;
- mobile-friendly интерфейс.

## Роли и возможности

### Администратор

Администратор может:

- создавать и редактировать группы;
- назначать менторов;
- добавлять студентов;
- распределять студентов по группам;
- смотреть сводку по группам, урокам и участникам;
- открывать табель группы и проверять данные.

### Ментор

Ментор может:

- видеть только свои группы;
- открывать табель группы по месяцам;
- выставлять оценки по датам;
- отмечать пропуски;
- видеть средний балл и посещаемость студентов;
- отправлять ежемесячный отчёт студенту или родителю.

### Студент

Студент может:

- входить только в свой кабинет;
- смотреть только свои оценки;
- видеть свой месячный табель;
- видеть посещаемость;
- видеть средний балл.

## Как пользоваться системой

### 1. Вход

Пользователь открывает проект и входит по своему логину и паролю.

После входа система автоматически показывает интерфейс по роли:

- администратору — панель управления;
- ментору — группы и табель;
- студенту — личный кабинет и оценки.

### 2. Сценарий для администратора

1. Создать группу.
2. Назначить ментора.
3. Добавить студентов.
4. Проверить состав группы.
5. При необходимости открыть табель и проверить месяц.

### 3. Сценарий для ментора

1. Открыть нужную группу.
2. Выбрать месяц.
3. Выставить оценки по дням.
4. Отметить пропуски.
5. Проверить средний балл и посещаемость.

### 4. Сценарий для студента

1. Войти в личный кабинет.
2. Открыть страницу `Мои оценки`.
3. Посмотреть табель за месяц.
4. Проверить средний балл и посещаемость.

## Ежемесячные отчёты и Dify

В проекте есть логика отправки ежемесячных отчётов по студентам через `Dify Workflow API`.

Система:

- собирает оценки за месяц;
- считает посещаемость;
- считает средний балл;
- считает количество оценок `5`, `4`, `3`, `2` и пропусков `Н`;
- формирует JSON payload;
- отправляет этот payload в `Dify`.

В Dify отправляются, например, такие поля:

- `student_name`
- `recipient_name`
- `recipient_phone`
- `group_name`
- `mentor_name`
- `month`
- `average_grade`
- `attendance_count`
- `absence_count`
- `total_five`
- `total_four`
- `total_three`
- `total_two`
- `attendance_rate`
- `report`

### Ручной запуск отчётов

```bash
python tabel_project\manage.py send_monthly_reports
```

Полезные варианты:

```bash
python tabel_project\manage.py send_monthly_reports --dry-run
python tabel_project\manage.py send_monthly_reports --date 2026-04-30
python tabel_project\manage.py send_monthly_reports --group-id 1
python tabel_project\manage.py send_monthly_reports --student-id 5
```

## Последние изменения

- улучшена mobile-адаптация для `admin`, `mentor` и `student`;
- добавлен удобный горизонтальный скролл табеля на телефонах;
- скрыты лишние логины в боковых карточках интерфейса;
- доработан payload отчётов для `Dify`;
- в JSON отчёта добавлены поля:
  - `total_five`
  - `total_four`
  - `total_three`
  - `total_two`
- обновлены SEO-файлы:
  - `index.html`
  - `robots.txt`
  - `sitemap.xml`
  - `site.webmanifest`

## Структура проекта

```text
.
├── assets/                 # логотип и дополнительные изображения
├── docker/                 # nginx и entrypoint
├── frontend/               # React frontend
├── scripts/                # локальные скрипты запуска
├── tabel_project/
│   ├── tabel_project/      # settings, urls, wsgi
│   └── tabel_app/          # модели, API, отчёты, management commands
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── README.md
```

## Локальный запуск

### Backend

Рекомендуемый локальный запуск без Docker:

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-local.ps1 -SeedDemo
```

### Frontend

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-frontend-local.ps1
```

Открыть:

- frontend dev: `http://127.0.0.1:5173/`
- backend: `http://127.0.0.1:8000/`

## Demo-аккаунты

- `admin_demo / admin12345`
- `mentor_demo / mentor12345`
- `student_demo_1 / student12345`
- `student_demo_2 / student12345`

## Production запуск через Docker

В проекте уже есть:

- `Dockerfile`
- `docker-compose.yml`
- `docker/nginx/default.conf`
- `docker/entrypoint.sh`

### Что заполнить в `.env`

Обязательно проверь:

- `SECRET_KEY`
- `DEBUG=False`
- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- `DB_USER`
- `DB_POSTGRES`
- `DB_PASSWORD`
- `DB_HOST=db`
- `DB_PORT=5432`
- `DIFY_API_KEY`

### Запуск на сервере

```bash
docker compose up --build -d
```

Проверка логов:

```bash
docker compose logs -f web
docker compose logs -f nginx
```

Создать администратора:

```bash
docker compose exec web python manage.py createsuperuser
```

Запустить demo-данные:

```bash
docker compose exec web python manage.py seed_demo
```

Открыть проект:

```text
http://<server-ip>/
```

## Важные замечания

- `.env` не должен попадать в GitHub;
- реальные ключи и пароли должны храниться только локально или на сервере;
- перед production лучше использовать новый `SECRET_KEY` и актуальные ключи;
- для домена и HTTPS потом нужно обновить `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` и SSL-настройки;
- если сайт должен появляться в Google, лучше использовать публичную открытую главную страницу.

## Лицензия

Проект распространяется по лицензии `MIT`.

## Команда

Этот проект создан вместе с командой **Motion Community**.
