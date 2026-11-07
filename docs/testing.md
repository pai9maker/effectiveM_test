# Тесты

## Быстрый запуск

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest            # unit-тесты
```

Или через Make: `make test`.

## Что покрыто unit-тестами

| Файл | Проверяет |
|---|---|
| `tests/test_access.py` | матрица видимости: public/unlisted/private, hidden/removed, owner/granted/moderator/admin, права на управление, «не готово к просмотру» |
| `tests/test_security.py` | Argon2id round-trip, rehash, типы JWT, подпись/подделка/истечение, double-submit CSRF |
| `tests/test_http_range.py` | закрытые/открытые/suffix-диапазоны, clamping, 416-случаи, мусорные заголовки |
| `tests/test_validation_and_formatting.py` | регистрация (username/password/резерв), нормализация заголовков видео, комментарии, русские склонения, компактные числа, длительность, «время назад» |

43 unit-теста, внешняя инфраструктура не требуется: проверяются чистые функции и
правила, на которых держатся безопасность и стриминг.

## Интеграционный smoke-тест

Требует запущенного приложения (после `./deploy.sh`):

```bash
ET_SMOKE_URL=http://localhost:8081 \
ET_PRIVATE_VIDEO_ID=<uuid приватного видео> \
pytest -m integration
```

Проверяется: `/healthz`, `/readyz` (БД, Redis, S3), `/docs`, главная и поиск,
вход демо-пользователя, лайк, комментарий с CSRF-заголовком, запрет модерации
для обычного пользователя, `206 Partial Content` на Range-запрос.

Получить id приватного видео:

```bash
docker compose exec -T db psql -U app -d app -tAc \
  "select id from videos where visibility='private' limit 1"
```

## Ручной приёмочный сценарий

1. `./deploy.sh`, открыть `http://localhost:8081`.
2. Войти как `viewer / DemoPass123!`.
3. Открыть любое видео, поставить лайк, оставить комментарий и ответ.
4. Загрузить MP4 через `/upload`, дождаться перехода в `ready`.
5. Проверить воспроизведение и перемотку (сеть → 206).
6. Войти как `techlab`, открыть приватное видео → «Доступ», выдать `viewer`.
7. Анонимно открыть приватное видео по прямой ссылке → 404.
8. Войти как `moderator`, обработать жалобу в `/moderation` (скрыть видео).
9. Войти как `admin`, сменить роль пользователя и проверить журнал в `/admin`.

## Линтер

```bash
make lint    # ruff check app tests scripts
```
