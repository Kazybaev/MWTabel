# Tabel

`Tabel` - это учебная платформа для администрирования групп, ведения месячного табеля и просмотра оценок студентами.

Проект построен как `React + Django REST Framework`:
- `React` отвечает за интерфейс
- `Django + DRF` отвечают за API, роли, табель, уроки и отчёты
- `PostgreSQL` используется как основная база данных

## Возможности

- админ управляет менторами, студентами и группами
- ментор выставляет оценки по дням в месячном табеле
- студент видит только свои оценки и краткую сводку
- поддерживается посещаемость, средний балл и месячная матрица оценок
- в проект добавлена серверная логика месячных отчётов по каждому студенту с отправкой в Dify

## Стек

- Python
- Django
- Django REST Framework
- JWT (`SimpleJWT`)
- PostgreSQL
- React
- Vite

## Структура проекта

```text
.
├── frontend/                  # React frontend
├── tabel_project/
│   ├── tabel_project/         # Django settings, urls, wsgi
│   └── tabel_app/             # модели, API, отчёты, management commands
├── .env.example               # пример переменных окружения
├── requirements.txt
└── README.md
```

## Быстрый запуск

### 1. Клонирование

```bash
git clone https://github.com/<your-username>/tabel.git
cd tabel
```

### 2. Подготовка окружения

Создай `.env` на основе [`.env.example`](./.env.example).

Пример:

```env
SECRET_KEY=django-insecure-change-me
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost,testserver

DB_POSTGRES=motionweb
DB_USER=postgres
DB_PASSWORD=change-me
DB_HOST=localhost
DB_PORT=5432

DIFY_BASE_URL=https://your-dify-domain/v1
DIFY_API_KEY=your-dify-api-key
DIFY_RESPONSE_MODE=blocking
DIFY_TIMEOUT_SECONDS=30
```

### 3. Установка зависимостей backend

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Установка зависимостей frontend

```bash
cd frontend
npm install
cd ..
```

### 5. Миграции

```bash
python tabel_project\manage.py migrate
```

### 6. Демо-данные

```bash
python tabel_project\manage.py seed_demo
```

### 7. Сборка frontend

```bash
cd frontend
npm run build
cd ..
```

### 8. Запуск проекта

```bash
python tabel_project\manage.py runserver
```

Открыть:

```text
http://127.0.0.1:8000/
```

## Демо-аккаунты

- `admin_demo / admin12345`
- `mentor_demo / mentor12345`
- `student_demo_1 / student12345`

## Месячные отчёты в Dify

В проекте есть сервис отчётов по студентам:
- собирает оценки, посещаемость, средний балл и список уроков за месяц
- определяет последний урок месяца для группы
- отправляет отчёт в Dify по одному студенту
- защищён от повторной отправки за тот же месяц

Команда запуска:

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

## Публикация на GitHub

Перед публикацией проверь:

1. `.env` не должен попадать в репозиторий
2. реальные ключи и пароли должны храниться только локально или в secrets хостинга
3. `frontend/dist` и `node_modules` не нужно коммитить
4. перед первым push желательно сделать первый осмысленный commit

Минимальный набор команд:

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<your-username>/tabel.git
git push -u origin main
```

## Что ещё можно улучшить

- добавить Docker и `docker-compose`
- вынести production settings отдельно
- добавить CI для тестов и сборки
- подключить деплой на Render, Railway или VPS

## Лицензия

Проект распространяется по лицензии `MIT`. Подробности смотри в [LICENSE](./LICENSE).
