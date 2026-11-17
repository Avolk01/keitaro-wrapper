# Keitaro Campaign Studio

Тестовое задание: создание кампании с двумя потоками и редактор офферов существующей кампании. Backend — FastAPI + SQLAlchemy, frontend — React + Vite.

## Что умеет

- Загружает домены, группы кампаний, источники, офферы и кампании из Keitaro.
- Создаёт кампанию с выбранными доменом, группой и источником. Первый поток (`regular`, позиция 1) принимает выбранную страну и делает HTTP-редирект на Google. Второй (`default`, позиция 2) отправляет остальной трафик на выбранный оффер.
- Добавляет, отключает и возвращает офферы в существующем потоке. Отключённый оффер сохраняется в потоке для восстановления. После изменения активные офферы получают равные целые доли, сумма всегда 100%.
- Записывает локальную историю изменений в SQLite через SQLAlchemy. Сами кампании и офферы остаются в Keitaro.

## Запуск

Нужны Python 3.11+ и Node.js 18+.

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

В `backend/.env` укажите `KEITARO_URL` и `KEITARO_API_KEY`. Ключ находится в профиле Keitaro → «API ключи». Не добавляйте `.env` в Git.

```powershell
alembic upgrade head
uvicorn app.main:app --reload
```

В другом терминале:

```powershell
cd frontend
npm install
npm run dev
```

Откройте `http://127.0.0.1:5173`. Backend API и Swagger доступны на `http://127.0.0.1:8000/docs`. Для нового проекта используется SQLite; `DATABASE_URL` можно поменять на PostgreSQL URL, установив соответствующий драйвер.

## Миграции и проверка

```powershell
cd backend
alembic upgrade head
python -m unittest discover -s tests -v
```

При изменении модели: `alembic revision --autogenerate -m "description"`, затем `alembic upgrade head`. Для отката текущей миграции: `alembic downgrade -1`.

Для сборки интерфейса: `cd frontend; npm run build`.

## Особенности API

Keitaro API вызывается только с backend через заголовок `Api-Key`; ключ не попадает в браузер. Создание выполняется тремя запросами, поскольку API не поддерживает атомарную транзакцию между кампанией и потоками. При ошибке создания потока API возвращает ID частично созданной кампании для ручного исправления. Редактор отправляет в `PUT /streams/{id}` весь список офферов, так как Keitaro заменяет его целиком. На каждое изменение backend заново читает текущий поток.

Документация: [полное ТЗ](https://app.notion.com/p/mnovikov/Adrobot-2b01eb78a7bb80a1b188c3a4a1cad55e), [Keitaro Admin API](https://admin-api.docs.keitaro.io/), [авторизация API](https://docs.keitaro.io/en/development/admin-api.html).

## Структура

`backend/app/service.py` — сценарии создания и редактирования; `backend/app/keitaro.py` — HTTP-клиент; `backend/app/db.py` и `backend/migrations` — локальная история; `frontend/src` — React UI.
