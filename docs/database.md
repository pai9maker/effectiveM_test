# Проектирование базы данных

СУБД — PostgreSQL 16. Все идентификаторы — `UUID`, время — `timestamptz`.
Схема создаётся миграцией `alembic/versions/20261105_1a9de765cc34_initial_schema.py`
(включая `CREATE EXTENSION pg_trgm`).

## Связи

```
users 1 ──── * videos            (owner_id, CASCADE)
users 1 ──── * comments          (author_id, CASCADE)
users 1 ──── * playlists         (owner_id, CASCADE)
users * ──── * users             (subscriptions: subscriber_id / channel_id)
users * ──── * videos            (video_likes: user_id / video_id)
users * ──── * videos            (watch_history: user_id / video_id)
videos 1 ─── * video_access_grants * ─── 1 users   (allow-list приватных видео)
videos 1 ─── * comments          (parent_id — один уровень ответов)
videos 1 ─── * reports           (reporter_id, reason, status)
playlists 1 ─ * playlist_items * ─ 1 videos        (position)
users 1 ──── * audit_log         (actor_id, SET NULL)
```

## Таблицы

### `users`
Аккаунт и канал одновременно (как в YouTube: пользователь = канал).

| Поле | Тип | Назначение |
|---|---|---|
| `email`, `username` | `varchar`, unique | логин; username участвует в URL `/@username` |
| `password_hash` | `varchar(255)` | Argon2id |
| `display_name`, `bio`, `avatar_key`, `banner_key` | | профиль; ключи объектов в S3 |
| `role` | enum `user_role` | `user` / `moderator` / `admin` |
| `is_active` | bool | блокировка без удаления данных |
| `subscribers_count` | int | денормализованный счётчик |

Ограничения: `char_length(username) >= 3`, `subscribers_count >= 0`.

### `videos`
Агрегат видео: метаданные, состояние обработки, видимость, модерация, счётчики.

| Поле | Назначение |
|---|---|
| `status` | `uploading` / `processing` / `ready` / `failed` |
| `visibility` | `public` / `unlisted` / `private` |
| `moderation_status` | `visible` / `hidden` / `removed` |
| `raw_key`, `playback_key`, `thumbnail_key` | ключи в S3; `raw_key` удаляется после обработки |
| `duration_sec`, `width`, `height`, `size_bytes` | результат ffprobe |
| `views_count`, `likes_count`, `dislikes_count`, `comments_count` | денормализованные счётчики |
| `published_at`, `processed_at`, `failure_reason` | жизненный цикл |
| `moderated_by_id`, `moderated_at`, `moderation_reason` | кто и почему скрыл |

Индексы:
* `ix_videos_feed (status, moderation_status, visibility, published_at)` — лента;
* `ix_videos_owner_created (owner_id, created_at)` — студия и канал;
* `ix_videos_title_trgm` — GIN + `gin_trgm_ops` для `ILIKE` и `similarity()`
  (поиск по названию).

### `video_access_grants`
Явный allow-list: `(video_id, user_id)` — PK, `granted_by_id`, `created_at`.
Нужен только для `visibility = private`; владелец и администратор не хранятся.

### `video_likes`
`(user_id, video_id)` — PK, `value ∈ {-1, 1}` (`CHECK`). Одна реакция на видео.

### `comments`
Дерево глубины 1: `parent_id` ссылается на корневой комментарий; вложенные
ответы запрещены на уровне API. `is_deleted` — soft delete, тело очищается.
`CHECK char_length(body) BETWEEN 1 AND 2000`. При удалении `is_deleted = true`,
тело заменяется служебной заглушкой и не отдаётся API.

### `subscriptions`
`(subscriber_id, channel_id)` — PK, `CHECK subscriber_id <> channel_id`.
Счётчик подписчиков хранится в `users.subscribers_count` и обновляется в той же
транзакции.

### `playlists` / `playlist_items`
Плейлист принадлежит пользователю, имеет `visibility`. Элементы — связь
многие-ко-многим с `position` и `UNIQUE (playlist_id, video_id)`.

### `watch_history`
`(user_id, video_id)` — PK, `position_sec`, `watched_at`. UPSERT при просмотре.

### `view_events`
Ledger просмотров: `UNIQUE (video_id, viewer_key, bucket)`, где `viewer_key` —
`u:<uuid>` для авторизованных или хэш IP+UA для анонимов, `bucket` — час.
Дедупликация в Redis (NX, 6 часов), запись в БД — источник истины.

### `reports`
Жалоба на видео: `reason` (enum), `details`, `status`
(`open/reviewed/actioned/dismissed`), `resolved_by_id`, `resolved_at`.
Один открытый отчёт на пару «пользователь + видео» проверяется в API.

### `audit_log`
Append-only журнал привилегированных действий: `actor_id`, `action`,
`entity_type`, `entity_id`, `meta` (JSONB), `ip`, `created_at`. Пишется при
модерации, смене ролей и блокировках.

## Решения и компромиссы

* **UUID вместо SERIAL** — идентификаторы видео не перебираемы, безопасны в
  URL; цена — чуть больший индекс.
* **Денормализованные счётчики** — лента читается без агрегатов; корректность
  обеспечивается транзакциями и `GREATEST(..., 0)`.
* **Мягкое удаление комментариев** — сохраняет структуру ответов.
* **Видимость и модерация разделены** — владелец управляет приватностью,
  модератор — публикацией; правила комбинируются в `app/services/access.py`.
* **Ключи объектов, а не URL** — хранилище можно заменить, не мигрируя БД.
