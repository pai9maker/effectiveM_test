#!/bin/bash

# deploy.sh - Скрипт развертывания EffectiveTube
set -e

echo "--- Инициализация развертывания EffectiveTube ---"

# 1. Проверка зависимостей
if ! command -v docker &> /dev/null; then
    echo "Ошибка: Docker не установлен. Пожалуйста, установите Docker и Docker Compose."
    exit 1
fi

# 2. Подготовка окружения
if [ ! -f .env ]; then
    echo "Создаю .env из примера..."
    cat <<EOF > .env
DATABASE_URL=postgresql+asyncpg://user:password@db:5432/effectivetube
REDIS_URL=redis://redis:6379/0
STORAGE_URL=http://seaweedfs:8333
SECRET_KEY=supersecretkey123
EOF
fi

# 3. Запуск инфраструктуры
echo "Поднимаем контейнеры (Postgres, Redis, SeaweedFS, App, Worker)..."
docker-compose up -d --build

# 4. Применение миграций БД
echo "Применяем миграции Alembic..."
# Ждем готовность БД
sleep 5
docker-compose exec -T app alembic upgrade head

# 5. Наполнение демо-данными
echo "Запуск скрипта наполнения БД..."
docker-compose exec -T app python3 scripts/seed_demo.py

echo "--- Развертывание завершено! ---"
echo "Приложение доступно по адресу: http://localhost:8000"
echo "Swagger API: http://localhost:8000/docs"
