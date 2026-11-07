# Развёртывание и эксплуатация

## Требования

* Ubuntu 22.04/24.04 (или macOS с Docker Desktop) и пользователь с `sudo`;
* 2 vCPU, 4 ГБ RAM, 20 ГБ диска (FFmpeg + образы + медиа);
* Docker Engine 24+ и Docker Compose v2;
* исходящий доступ к Docker Hub при первой сборке.

`deploy.sh` сам установит Docker через `get.docker.com`, если его нет и доступен
`apt-get`. На чистой Ubuntu достаточно:

```bash
git clone <repo> effectiveM_test && cd effectiveM_test
./deploy.sh
```

## Что делает deploy.sh

1. Проверяет Docker daemon и Compose v2.
2. Создаёт `.env` со случайными `SECRET_KEY`, `POSTGRES_PASSWORD`,
   `S3_ACCESS_KEY`, `S3_SECRET_KEY` (файл `chmod 600`). Существующий `.env` не
   перезаписывается.
3. Рендерит `infra/seaweedfs/s3.json` из шаблона — те же S3-ключи, что в `.env`.
4. `docker compose up -d --build`: PostgreSQL, Redis, SeaweedFS, job миграций,
   приложение и воркер.
5. Ждёт `200` от `http://localhost:8081/readyz` (БД + Redis + S3).
6. Запускает `python scripts/seed_demo.py` внутри контейнера (идемпотентно).
7. Печатает URL, ссылку на Swagger и демо-аккаунты.

Порт задаётся `HTTP_PORT` (по умолчанию `8081`):

```bash
HTTP_PORT=80 ./deploy.sh
```

## Переменные окружения

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `HTTP_PORT` | `8081` | внешний порт приложения |
| `ENV` | `production` | `production` включает проверку `SECRET_KEY` |
| `SECRET_KEY` | генерируется | подпись JWT, ≥ 32 символов |
| `POSTGRES_PASSWORD` | генерируется | пароль пользователя `app` |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | генерируются | доступ к SeaweedFS S3 |
| `S3_BUCKET` | `media` | бакет (создаётся автоматически) |
| `COOKIE_SECURE` | `false` | `true` при работе по HTTPS |
| `ACCESS_TOKEN_TTL_MINUTES` | `30` | TTL access-токена |
| `REFRESH_TOKEN_TTL_DAYS` | `14` | TTL refresh-токена |
| `MAX_UPLOAD_BYTES` | `2147483648` | лимит загружаемого файла |
| `MAX_VIDEO_DURATION_SEC` | `14400` | лимит длительности |
| `TRANSCODE_TARGET_HEIGHT` | `720` | высота транскодирования |
| `DEMO_PASSWORD` | `DemoPass123!` | пароль демо-аккаунтов |

## Проверка после развёртывания

```bash
curl -fsS http://localhost:8081/readyz | jq
# {"status":"ok","checks":{"database":"ok","redis":"ok","storage":"ok"}}

open http://localhost:8081/docs
```

Сценарий приёмки: войти как `viewer` → открыть видео → поставить лайк →
оставить комментарий → загрузить свой MP4 → дождаться `ready` → убедиться, что
воспроизведение работает (Range 206).

## Операции

```bash
docker compose ps                     # состояние сервисов
docker compose logs -f app            # логи приложения
docker compose logs -f worker         # обработка видео
docker compose exec app alembic upgrade head
docker compose exec app python scripts/seed_demo.py --reset
docker compose restart app worker
docker compose down                   # остановить, данные сохраняются
docker compose down -v                # удалить данные (БД, Redis, медиа)
```

### Резервное копирование

```bash
# база
docker compose exec -T db pg_dump -U app app | gzip > backup-$(date +%F).sql.gz
# медиа (том SeaweedFS)
docker run --rm -v effectivetube_storagedata:/data -v "$PWD":/backup alpine \
  tar czf /backup/media-$(date +%F).tar.gz -C /data .
```

### Обновление

```bash
git pull
docker compose up -d --build   # migrate выполнится до app
```

## Диагностика

| Симптом | Что проверить |
|---|---|
| `SECRET_KEY is required` | нет `.env` — запустите `./deploy.sh` |
| `port is already allocated` | занят `HTTP_PORT`; задайте другой |
| `/readyz` = 503 | `docker compose logs db redis storage`; app ждёт все три |
| Видео вечно `processing` | `docker compose logs worker`; очередь Redis |
| `failed` после загрузки | `failure_reason` в студии; обычно кодек/длительность |
| Пустая лента | демо-данные не загрузились: `docker compose exec app python scripts/seed_demo.py --reset` |
| Docker daemon недоступен | `sudo systemctl start docker`, затем повторить |

## Ограничения однокомпонентного демо

Один экземпляр приложения и воркера, без внешнего reverse proxy и TLS.
Для продакшена: HTTPS-терминация (nginx/Caddy), `COOKIE_SECURE=true`,
внешний S3, несколько воркеров и бэкапы по расписанию.
