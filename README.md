# Tabel

<p align="center">
  <img src="./assets/motion-community-logo.jfif" alt="Motion Community" width="180" />
</p>

<p align="center">
  Учебная платформа для админа, ментора и студента: группы, месячный табель, оценки, посещаемость и отчёты.
</p>

## О проекте

`Tabel` — это веб-система для учебных центров и IT-школ, где:

- администратор управляет группами, менторами и студентами;
- ментор работает со своими группами и ведёт табель;
- студент видит только свои оценки и свою сводку;
- в конце месяца можно формировать и отправлять отчёты через `Dify`.

Стек проекта:

- `React + Vite` — интерфейс;
- `Django + Django REST Framework` — backend и API;
- `PostgreSQL` — production-база данных;
- `JWT` — авторизация;
- `Docker + Nginx + Gunicorn` — production-развёртывание.

## Что умеет система

- роли `ADMIN`, `MENTOR`, `STUDENT`;
- управление группами;
- управление студентами;
- управление менторами;
- месячный табель с оценками по дням;
- учёт посещаемости;
- расчёт среднего балла;
- личный кабинет студента;
- автоотчёты по студентам через `Dify`;
- mobile-friendly интерфейс.

## Роли и возможности

### Администратор

Администратор может:

- создавать и редактировать группы;
- добавлять менторов;
- добавлять студентов;
- назначать студентов в группы;
- видеть общую сводку по системе;
- просматривать уроки, группы и состав потоков.

### Ментор

Ментор может:

- видеть только свои группы;
- открывать табель группы по месяцам;
- выставлять оценки по дням;
- отмечать пропуски;
- видеть посещаемость и средний балл студентов;
- работать с табелем на компьютере и телефоне.

### Студент

Студент может:

- входить только в свой кабинет;
- видеть только свои оценки;
- видеть только свой месячный табель;
- видеть посещаемость;
- видеть средний балл;
- пользоваться системой без доступа к другим студентам.

## Как пользоваться системой

### 1. Вход

Пользователь открывает проект и входит по своему логину и паролю.

После входа система автоматически показывает интерфейс по роли:

- админу — панель управления;
- ментору — группы и табель;
- студенту — личный кабинет и оценки.

### 2. Работа администратора

Обычный сценарий:

1. Создать группу.
2. Назначить ментора.
3. Добавить студентов.
4. Проверить, что группа и состав сохранены.
5. Передать работу ментору.

### 3. Работа ментора

Обычный сценарий:

1. Открыть свою группу.
2. Выбрать месяц.
3. Выставить оценки по дням.
4. Отметить пропуски.
5. Проверить средний балл и посещаемость.

### 4. Работа студента

Обычный сценарий:

1. Войти в личный кабинет.
2. Открыть страницу `Мои оценки`.
3. Посмотреть табель за месяц.
4. Проверить средний балл и посещаемость.

## Месячные отчёты

В проекте есть логика отправки месячных отчётов по студентам.

Что делает система:

- собирает оценки за месяц;
- считает посещаемость;
- считает средний балл;
- формирует данные по студенту;
- отправляет payload в `Dify Workflow API`.

Ручной запуск:

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


## Структура проекта

```text
.
├── assets/                 # логотип и дополнительные изображения
├── docker/                 # nginx и entrypoint
├── frontend/               # React frontend
├── scripts/                # вспомогательные локальные скрипты
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

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python tabel_project\manage.py migrate
python tabel_project\manage.py seed_demo
python tabel_project\manage.py runserver
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Открыть:

- frontend dev: `http://127.0.0.1:5173/`
- backend: `http://127.0.0.1:8000/`

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
- для домена и HTTPS потом нужно обновить `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` и SSL-настройки.

## Лицензия

Проект распространяется по лицензии `MIT`.

## Команда

Этот проект создан вместе с командой **Motion Community**.
