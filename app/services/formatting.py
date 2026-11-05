"""Human-friendly formatting for the server-rendered UI (Russian locale)."""

from __future__ import annotations

from datetime import UTC, datetime


def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def compact_number(n: int) -> str:
    n = int(n or 0)
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        value = n / 1000
        return f"{value:.1f}".rstrip("0").rstrip(".").replace(".", ",") + " тыс."
    value = n / 1_000_000
    return f"{value:.1f}".rstrip("0").rstrip(".").replace(".", ",") + " млн"


def views(n: int) -> str:
    return f"{compact_number(n)} {plural(n, 'просмотр', 'просмотра', 'просмотров')}"


def subscribers(n: int) -> str:
    return f"{compact_number(n)} {plural(n, 'подписчик', 'подписчика', 'подписчиков')}"


def comments(n: int) -> str:
    return f"{compact_number(n)} {plural(n, 'комментарий', 'комментария', 'комментариев')}"


def videos(n: int) -> str:
    return f"{compact_number(n)} {plural(n, 'видео', 'видео', 'видео')}"


def duration(total_seconds: float | int | None) -> str:
    total = int(total_seconds or 0)
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def time_ago(value: datetime | None) -> str:
    if value is None:
        return ""
    now = datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    seconds = max(int((now - value).total_seconds()), 0)

    if seconds < 60:
        return "только что"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} {plural(minutes, 'минуту', 'минуты', 'минут')} назад"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} {plural(hours, 'час', 'часа', 'часов')} назад"
    days = hours // 24
    if days < 30:
        return f"{days} {plural(days, 'день', 'дня', 'дней')} назад"
    months = days // 30
    if months < 12:
        return f"{months} {plural(months, 'месяц', 'месяца', 'месяцев')} назад"
    years = days // 365
    return f"{years} {plural(years, 'год', 'года', 'лет')} назад"


def date_ru(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%d.%m.%Y")


def initials(name: str) -> str:
    parts = [p for p in name.strip().split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:1].upper()
    return (parts[0][:1] + parts[1][:1]).upper()
