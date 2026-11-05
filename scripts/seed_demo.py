"""Populate the database with demo users, videos, comments and moderation data.

The script is idempotent: it does nothing when users already exist unless
``--reset`` is passed. Video files are generated with ffmpeg, uploaded to the
S3-compatible storage and inserted as fully processed ``ready`` videos.

Usage:
    python scripts/seed_demo.py            # seed once
    python scripts/seed_demo.py --reset    # wipe demo data and re-seed
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, func, select, text  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import (  # noqa: E402
    Comment,
    ModerationStatus,
    Playlist,
    PlaylistItem,
    PlaylistVisibility,
    Report,
    ReportReason,
    Subscription,
    User,
    UserRole,
    Video,
    VideoAccessGrant,
    VideoLike,
    VideoStatus,
    Visibility,
)
from app.services.storage import build_object_key, get_storage  # noqa: E402

RNG = random.Random(20261105)

USERS = [
    # username, display_name, role, bio
    ("admin", "Администратор", UserRole.admin, "Платформа EffectiveTube"),
    ("moderator", "Мария Модератор", UserRole.moderator, "Слежу за порядком в комментариях"),
    ("viewer", "Иван Зритель", UserRole.user, "Смотрю всё подряд"),
    ("techlab", "Tech Lab", UserRole.user, "Разборы технологий, код и железо. Новое по вторникам."),
    ("cooking", "Простая Кухня", UserRole.user, "Готовим быстро и вкусно на обычной кухне."),
    ("travel", "Дорога Домой", UserRole.user, "Путешествия без пафоса: маршруты, цены, лайфхаки."),
    ("music", "Lo-Fi Room", UserRole.user, "Музыка для работы и учёбы. 24/7 настроение."),
    ("gaming", "Pixel Hunt", UserRole.user, "Прохождения, обзоры и немного боли."),
]

VIDEOS = [
    # owner, title, description, seconds, views, days_ago, visibility, moderation
    (
        "techlab",
        "FastAPI за 20 минут: от идеи до продакшена",
        "Разбираем структуру проекта, зависимости, миграции Alembic и деплой в Docker.\n\nТаймкоды:\n00:00 Введение\n03:20 Структура проекта\n09:40 Миграции\n15:10 Деплой",
        95,
        184_320,
        2,
        Visibility.public,
        ModerationStatus.visible,
    ),
    (
        "techlab",
        "PostgreSQL: индексы, которые реально ускоряют",
        "B-tree, GIN и trigram-индексы на практике. Показываю EXPLAIN ANALYZE до и после.",
        78,
        96_450,
        6,
        Visibility.public,
        ModerationStatus.visible,
    ),
    (
        "techlab",
        "Собираем домашний сервер на мини-ПК",
        "Тихий сервер для медиатеки, контейнеров и бэкапов. Смета, сборка, настройка.",
        120,
        54_120,
        14,
        Visibility.public,
        ModerationStatus.visible,
    ),
    (
        "techlab",
        "Приватное видео: доступ только по приглашению",
        "Демонстрация приватного видео. Видно только владельцу и зрителям из списка доступа.",
        32,
        12,
        1,
        Visibility.private,
        ModerationStatus.visible,
    ),
    (
        "cooking",
        "Паста карбонара без сливок — как в Риме",
        "Четыре ингредиента, никаких сливок. Секрет — температура и крахмальная вода.",
        64,
        412_800,
        4,
        Visibility.public,
        ModerationStatus.visible,
    ),
    (
        "cooking",
        "Хлеб на закваске: первый раз не комом",
        "Пошаговый рецепт для новичков. Стартер, замес, расстойка и печь.",
        140,
        221_340,
        9,
        Visibility.public,
        ModerationStatus.visible,
    ),
    (
        "cooking",
        "Ужин за 15 минут: три сковородки",
        "Три быстрых блюда на будний вечер. Список продуктов в описании.",
        55,
        78_900,
        21,
        Visibility.public,
        ModerationStatus.visible,
    ),
    (
        "travel",
        "Алтай без машины: маршрут на 5 дней",
        "Автобусы, тропы и ночёвки. Бюджет поездки — 32 тысячи рублей.",
        110,
        134_500,
        3,
        Visibility.public,
        ModerationStatus.visible,
    ),
    (
        "travel",
        "Стамбул за выходные: что успеть",
        "Паромы, базары и кофе. Маршрут на 48 часов без музеев.",
        88,
        302_100,
        11,
        Visibility.public,
        ModerationStatus.visible,
    ),
    (
        "travel",
        "Скрытая бухта, куда не доезжают туристы",
        "Координаты в описании. Будьте аккуратны с мусором и природой.",
        47,
        45_600,
        30,
        Visibility.unlisted,
        ModerationStatus.visible,
    ),
    (
        "music",
        "Lo-Fi для работы — 1 час спокойного бита",
        "Мягкий бит для концентрации. Наушники рекомендуются.",
        180,
        1_204_000,
        5,
        Visibility.public,
        ModerationStatus.visible,
    ),
    (
        "music",
        "Дождь и винил: вечерний микс",
        "Запись с винила, шум дождя, без резких переходов.",
        150,
        88_200,
        16,
        Visibility.public,
        ModerationStatus.visible,
    ),
    (
        "music",
        "Пустой зал: репетиция в 3 часа ночи",
        "Черновик новой композиции. Свет, тени и немного импровизации.",
        72,
        19_800,
        27,
        Visibility.public,
        ModerationStatus.visible,
    ),
    (
        "gaming",
        "Проходим инди-хоррор без единого крика (почти)",
        "Полное прохождение с комментариями. Осторожно: резкие звуки.",
        160,
        356_700,
        1,
        Visibility.public,
        ModerationStatus.visible,
    ),
    (
        "gaming",
        "Почему эта головоломка сломала мне мозг",
        "Разбор механик и уровней. Спойлеры к финалу.",
        83,
        142_900,
        8,
        Visibility.public,
        ModerationStatus.visible,
    ),
    (
        "gaming",
        "Спидран за 12 минут: разбор маршрута",
        "Покадровый разбор трюков и таймингов.",
        69,
        67_300,
        19,
        Visibility.public,
        ModerationStatus.visible,
    ),
    (
        "viewer",
        "Мой первый влог: неделя без телефона",
        "Что изменилось в голове и в расписании.",
        58,
        2_340,
        7,
        Visibility.public,
        ModerationStatus.visible,
    ),
    (
        "viewer",
        "Тест: видео, скрытое модерацией",
        "Это видео скрыто модератором и не показывается в ленте.",
        25,
        900,
        2,
        Visibility.public,
        ModerationStatus.hidden,
    ),
]

COMMENTS = [
    "Отличное объяснение, наконец-то понял тему!",
    "Смотрю уже третий раз, всё равно нахожу новое.",
    "Подскажите, какая версия софта использовалась?",
    "Спасибо за таймкоды, это очень удобно.",
    "Звук бы чуть громче, а так всё супер.",
    "Ждём продолжение!",
    "А можно ссылку на исходники?",
    "Слишком быстро на 03:20, но в целом ок.",
    "Лучший разбор на эту тему на русском.",
    "Не согласен с выводом в конце, но аргументы интересные.",
    "Поставил лайк не глядя, потом посмотрю.",
    "Алгоритмы привели сюда и не прогадали.",
    "Кто ещё смотрит это перед дедлайном?",
    "Сделайте пожалуйста версию покороче.",
    "Материал огонь, монтаж приятный.",
    "Ушёл пробовать — вернусь с результатом.",
]

REPLIES = [
    "Тоже искал этот момент, спасибо автору.",
    "У меня на 2.1 всё работает так же.",
    "Присоединяюсь к вопросу.",
    "Проверь версию контейнера, похоже на неё.",
    "Да, без этого никак.",
]

REPORT_DETAILS = [
    "В названии обещают одно, в видео — реклама стороннего сервиса.",
    "Кадры с резким звуком без предупреждения.",
    "Похоже на перезалив чужого ролика.",
    "Спам в описании и ссылки на сомнительные сайты.",
]


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, timeout=600)


def probe(path: str) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
        check=True,
        capture_output=True,
        timeout=120,
    )
    return json.loads(result.stdout or b"{}")


def make_video(path: str, seconds: int, index: int) -> None:
    """Generate a synthetic clip that looks nothing like real footage (demo data)."""
    hue = (index * 47) % 360
    run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=25:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency={220 + (index * 37) % 660}:duration={seconds}",
            "-vf", f"hue=h={hue}:s=1.1,eq=brightness=-0.02",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
            "-movflags", "+faststart", "-shortest", path,
        ]
    )


def make_thumbnail(video_path: str, image_path: str, at: float) -> None:
    run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", f"{at:.1f}", "-i", video_path,
            "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "3", image_path,
        ]
    )


def seed(reset: bool) -> None:
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(engine, expire_on_commit=False)
    storage = get_storage()
    try:
        storage.ensure_bucket()
    except Exception as exc:  # pragma: no cover - infra
        print(f"! storage unavailable: {exc}", file=sys.stderr)
        raise SystemExit(2)

    with SessionLocal() as db:
        existing = db.scalar(select(func.count()).select_from(User)) or 0
        if existing and not reset:
            print(f"Demo data already present ({existing} users). Use --reset to recreate.")
            return
        if reset:
            print("Wiping demo data…")
            db.execute(
                text(
                    "TRUNCATE users, videos, comments, video_likes, subscriptions, "
                    "watch_history, view_events, playlists, playlist_items, reports, "
                    "video_access_grants, audit_log RESTART IDENTITY CASCADE"
                )
            )
            db.commit()

        print("Creating users…")
        users: dict[str, User] = {}
        for username, display_name, role, bio in USERS:
            user = User(
                email=f"{username}@example.com",
                username=username,
                display_name=display_name,
                password_hash=hash_password(settings.demo_password),
                role=role,
                bio=bio,
                created_at=datetime.now(UTC) - timedelta(days=RNG.randint(60, 700)),
            )
            db.add(user)
            users[username] = user
        db.commit()

        # subscriptions
        print("Subscribing demo users…")
        for subscriber in users.values():
            for channel_name in RNG.sample([u for u in users if u != subscriber.username], k=RNG.randint(1, 4)):
                channel = users[channel_name]
                db.add(Subscription(subscriber_id=subscriber.id, channel_id=channel.id))
                channel.subscribers_count = (channel.subscribers_count or 0) + 1
        db.commit()

        workdir = tempfile.mkdtemp(prefix="et-seed-")
        created_videos: list[Video] = []
        try:
            print("Generating and uploading videos…")
            for index, (owner, title, description, seconds, views, days_ago, visibility, moderation) in enumerate(VIDEOS):
                video_path = os.path.join(workdir, f"video-{index}.mp4")
                thumb_path = os.path.join(workdir, f"thumb-{index}.jpg")
                make_video(video_path, seconds, index)
                make_thumbnail(video_path, thumb_path, min(2.0, seconds / 2))

                owner_user = users[owner]
                playback_key = build_object_key("videos", "playback.mp4", owner_id=str(owner_user.id))
                thumb_key = build_object_key("thumbnails", "thumb.jpg", owner_id=str(owner_user.id))
                with open(video_path, "rb") as fh:
                    storage.upload_fileobj(playback_key, fh, content_type="video/mp4")
                with open(thumb_path, "rb") as fh:
                    storage.upload_fileobj(thumb_key, fh, content_type="image/jpeg")
                info = probe(video_path)
                video_stream = next(s for s in info["streams"] if s["codec_type"] == "video")
                published = datetime.now(UTC) - timedelta(days=days_ago, hours=RNG.randint(0, 20))

                video = Video(
                    owner_id=owner_user.id,
                    title=title,
                    description=description,
                    status=VideoStatus.ready,
                    visibility=visibility,
                    moderation_status=moderation,
                    playback_key=playback_key,
                    thumbnail_key=thumb_key,
                    duration_sec=float(info["format"]["duration"]),
                    width=int(video_stream["width"]),
                    height=int(video_stream["height"]),
                    size_bytes=os.path.getsize(video_path),
                    views_count=views,
                    comments_count=0,
                    likes_count=0,
                    dislikes_count=0,
                    published_at=published,
                    processed_at=published,
                )
                if moderation is not ModerationStatus.visible:
                    video.moderated_at = datetime.now(UTC) - timedelta(days=1)
                    video.moderated_by_id = users["moderator"].id
                    video.moderation_reason = "demo moderation queue"
                db.add(video)
                db.flush()
                created_videos.append(video)
                print(f"  ✓ {title[:60]}")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        db.commit()

        print("Adding likes, comments and views…")
        for video in created_videos:
            if video.moderation_status is not ModerationStatus.visible:
                continue
            voters = RNG.sample(list(users.values()), k=RNG.randint(2, len(users)))
            for voter in voters:
                value = 1 if RNG.random() < 0.85 else -1
                db.add(VideoLike(user_id=voter.id, video_id=video.id, value=value))
                if value == 1:
                    video.likes_count += 1
                else:
                    video.dislikes_count += 1

            top_level: list[Comment] = []
            for _ in range(RNG.randint(2, 6)):
                author = RNG.choice(list(users.values()))
                comment = Comment(
                    video_id=video.id,
                    author_id=author.id,
                    body=RNG.choice(COMMENTS),
                    created_at=datetime.now(UTC) - timedelta(hours=RNG.randint(1, 240)),
                )
                db.add(comment)
                db.flush()
                top_level.append(comment)
                video.comments_count += 1
                for _ in range(RNG.randint(0, 2)):
                    if RNG.random() < 0.4:
                        continue
                    reply = Comment(
                        video_id=video.id,
                        author_id=RNG.choice(list(users.values())).id,
                        parent_id=comment.id,
                        body=RNG.choice(REPLIES),
                        created_at=comment.created_at + timedelta(minutes=RNG.randint(1, 300)),
                    )
                    db.add(reply)
                    video.comments_count += 1
        db.commit()

        print("Creating playlists…")
        playlist_specs = [
            ("techlab", "Инженерные разборы", PlaylistVisibility.public, ["FastAPI", "PostgreSQL", "сервер"]),
            ("cooking", "Быстрые рецепты", PlaylistVisibility.public, ["Паста", "Ужин"]),
            ("travel", "Маршруты выходного дня", PlaylistVisibility.public, ["Алтай", "Стамбул"]),
            ("music", "Фон для работы", PlaylistVisibility.public, ["Lo-Fi", "Дождь"]),
            ("viewer", "Посмотреть позже", PlaylistVisibility.private, ["FastAPI", "Паста"]),
        ]
        for owner, title, visibility, keywords in playlist_specs:
            playlist = Playlist(
                owner_id=users[owner].id,
                title=title,
                description="Демонстрационный плейлист",
                visibility=visibility,
            )
            db.add(playlist)
            db.flush()
            position = 0
            for video in created_videos:
                if any(word.lower() in video.title.lower() for word in keywords):
                    position += 1
                    db.add(PlaylistItem(playlist_id=playlist.id, video_id=video.id, position=position))
        db.commit()

        print("Granting access to the private video…")
        private_video = next(v for v in created_videos if v.visibility is Visibility.private)
        db.add(
            VideoAccessGrant(
                video_id=private_video.id,
                user_id=users["viewer"].id,
                granted_by_id=users["techlab"].id,
            )
        )
        # history for the demo viewer
        for video in created_videos[:6]:
            db.execute(
                text(
                    "INSERT INTO watch_history (user_id, video_id, watched_at) "
                    "VALUES (:u, :v, now() - interval '1 hour')"
                ),
                {"u": str(users["viewer"].id), "v": str(video.id)},
            )
        db.commit()

        print("Creating moderation reports…")
        report_targets = [v for v in created_videos if v.owner_id == users["gaming"].id][:2]
        for index, video in enumerate(report_targets):
            db.add(
                Report(
                    reporter_id=users["viewer"].id if index == 0 else users["moderator"].id,
                    video_id=video.id,
                    reason=ReportReason.spam if index == 0 else ReportReason.harassment,
                    details=REPORT_DETAILS[index],
                    created_at=datetime.now(UTC) - timedelta(hours=index + 2),
                )
            )
        db.commit()

        print("\nDemo data ready:")
        print(f"  users: {len(users)}, videos: {len(created_videos)}, playlists: {len(playlist_specs)}")
        print(f"  password for every demo account: {settings.demo_password}")
        print("  accounts: admin, moderator, viewer, techlab, cooking, travel, music, gaming")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed EffectiveTube with demo data")
    parser.add_argument("--reset", action="store_true", help="wipe existing data first")
    args = parser.parse_args()
    seed(reset=args.reset)
