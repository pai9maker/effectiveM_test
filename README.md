# EffectiveTube

Копия YouTube на FastAPI + PostgreSQL + SeaweedFS + Celery.

## Развертывание
Для развертывания на чистой Ubuntu:
1. Установите Docker и Docker Compose.
2. Сделайте скрипт исполняемым: `chmod +x deploy.sh`
3. Запустите: `./deploy.sh`

## Архитектура
- **Backend:** FastAPI, SQLAlchemy 2.0 (async), Pydantic v2.
- **Хранилище:** SeaweedFS (S3-совместимое) для видеофайлов.
- **Фоновые задачи:** Celery + Redis для транскодирования видео.
- **База данных:** PostgreSQL.

## Агентная обвязка
Документация по работе ИИ находится в файле `AGENTS.md`. История диалогов приложена в архиве.
