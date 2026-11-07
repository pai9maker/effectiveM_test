# EffectiveTube

Учебный клон YouTube: серверный рендеринг на FastAPI, PostgreSQL, приватное
S3-хранилище (SeaweedFS) и фоновая обработка видео через Celery + FFmpeg.
Разворачивается одной командой на чистой Ubuntu.

```
Браузер ──► app (FastAPI: SSR-страницы + JSON API + /docs)
              ├── PostgreSQL 16   — пользователи, видео, лайки, жалобы, аудит
              ├── Redis 7         — refresh-сессии, лимиты, очередь Celery
              └── SeaweedFS S3    — видео, превью, аватары
worker (Celery + FFmpeg) ──► ffprobe → 720p → JPEG-превью → S3
```

## Быстрый старт

Нужны Docker и Docker Compose v2 (на чистой Ubuntu `deploy.sh` установит Docker
сам, если запущен с `sudo`/от root).

```bash
git clone https://github.com/pai9maker/effectiveM_test.git
cd effectiveM_test
./deploy.sh
```

Скрипт:

1. сгенерирует `.env` со случайными `SECRET_KEY`, паролем БД и ключами S3;
2. отрендерит конфиг SeaweedFS из шаблона;
3. соберёт образ и поднимет PostgreSQL, Redis, SeaweedFS, миграции, app и worker;
4. дождётся `200` от `/readyz`;
5. загрузит демо-данные (идемпотентно).

Приложение: **http://localhost:8081**, Swagger: **http://localhost:8081/docs**.

Порт меняется переменной `HTTP_PORT`:

```bash
HTTP_PORT=80 ./deploy.sh
```

## Демо-аккаунты

Пароль всех аккаунтов — `DemoPass123!` (задаётся `DEMO_PASSWORD`).

| Логин | Роль | Что показывает |
|---|---|---|
| `admin` | администратор | `/admin`: роли, блокировки, журнал действий |
| `moderator` | модератор | `/moderation`: жалобы, скрытие/восстановление видео |
| `viewer` | пользователь | лента, лайки, комментарии; есть доступ к приватному видео |
| `techlab`, `cooking`, `travel`, `music`, `gaming` | авторы | каналы с видео и плейлистами |

## Возможности

**Экраны (SSR, тёмная/светлая тема, русский язык)**

* **Главная** — лента готовых публичных видео с превью, длительностью и счётчиками.
* **Просмотр** — HTML5-плеер с перемоткой (HTTP Range), лайк/дизлайк,
  комментарии и ответы, подписка, рекомендации.
* **Канал** `/@username` — видео, плейлисты, подписчики, кнопка подписки.
* **Поиск** `/results?search_query=` — по названию и описанию (`pg_trgm`).
* **Загрузка** `/upload` — прогресс отправки, метаданные, видимость.
* **Студия** `/studio` — статусы обработки, редактирование, удаление,
  выдача доступа к приватному видео.
* **Авторизация** — вход и регистрация.
* **Модерация** `/moderation` — очередь жалоб, скрытие и восстановление видео.
* **Админка** `/admin` — роли, блокировка пользователей, журнал аудита.

**Правила доступа**

* `public` — всем; `unlisted` — по ссылке, но не в ленте; `private` — только
  владельцу, явно приглашённым пользователям и администратору.
* Скрытое/удалённое модератором видео видят владелец, модератор и админ.
* Посторонний получает **404**, а не 403 — существование приватного id не
  подтверждается.
* Управлять видео может владелец и админ; модератор — только скрывать.

**Безопасность**

* Argon2id для паролей, JWT в `httpOnly`-куках, refresh-токены с allow-list в Redis.
* Double-submit CSRF для всех небезопасных `/api/*`, CSP и security-заголовки.
* Медиа не публикуется в S3: стриминг идёт через backend с проверкой прав.
* Rate limiting на вход, регистрацию, комментарии, жалобы и загрузку.
* Все изменения схемы БД — только миграциями Alembic.

## Тесты

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest            # unit-тесты
```

Интеграционный smoke-тест против запущенного стека:

```bash
ET_SMOKE_URL=http://localhost:8081 pytest -m integration
```

Подробнее — `docs/testing.md`.

## Разработка без Docker

```bash
make install     # venv + зависимости
make migrate     # alembic upgrade head (нужен DATABASE_URL)
make seed        # демо-данные
make run         # uvicorn с авто-перезагрузкой
make test
make lint
```

## Структура репозитория

```
app/
  api/v1/        JSON API: auth, videos, channels, playlists, moderation, admin, search
  web/           SSR-маршруты и Jinja2-окружение
  services/      доступ, стриминг, storage, rate limit, сериализация
  models/        SQLAlchemy 2.0
  schemas/       Pydantic v2
  workers/       Celery app и медиа-пайплайн
  templates/     Jinja2 (YouTube-подобный UI)
  static/        CSS/JS
alembic/         миграции
docs/            архитектура, БД, безопасность, развёртывание, тесты, AI-workflow
infra/seaweedfs/ шаблон S3-конфига
scripts/         seed_demo.py
tests/           unit + integration smoke
ai-dialogs/      экспортированные сессии ИИ (как есть)
```

## Документация

* [Архитектура](docs/architecture.md)
* [База данных](docs/database.md)
* [Безопасность](docs/security.md)
* [Развёртывание](docs/deployment.md)
* [Тесты](docs/testing.md)
* [Как использовался ИИ](docs/ai-workflow.md)
* [Правила работы агентов](AGENTS.md)
* [Правила разработки](CONTRIBUTING.md)

## Ограничения демо

Один экземпляр приложения и воркера, без TLS и внешнего reverse proxy. Для
продакшена нужны HTTPS (`COOKIE_SECURE=true`), внешний S3, несколько воркеров и
регулярные бэкапы. Подтверждение email, 2FA и восстановление пароля не входят в
рамки задания.
