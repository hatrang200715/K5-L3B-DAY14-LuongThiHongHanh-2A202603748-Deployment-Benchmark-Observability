"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

redis.from_url không mở kết nối thật — app khởi động được cả khi Redis
chưa sẵn sàng; health thật được kiểm bằng redis_healthy().
"""
import redis

from app.config import settings

# None khi REDIS_URL chưa được cấu hình (chạy local không Redis).
r = (
    redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
    )
    if settings.redis_url
    else None
)


def redis_healthy() -> bool:
    try:
        return bool(r is not None and r.ping())
    except Exception:
        return False
