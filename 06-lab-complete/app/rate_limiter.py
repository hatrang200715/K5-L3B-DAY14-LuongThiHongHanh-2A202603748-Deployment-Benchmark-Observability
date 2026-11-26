"""
Rate limiting (tiêu chí 7): sliding window qua Redis ZSET.

Vượt RATE_LIMIT_PER_MINUTE request / 60 giây cho mỗi API key → 429 kèm
Retry-After. State nằm trong Redis nên dùng chung cho mọi worker/instance
và còn nguyên sau khi restart agent.
"""
import time

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60
_WINDOW_KEY = "rl:{key}"


def check_rate_limit(key: str) -> None:
    if r is None or not key:
        return  # Không có Redis → fail-open; readiness sẽ báo riêng qua /ready.
    now = time.time()
    zkey = _WINDOW_KEY.format(key=key)
    try:
        r.zremrangebyscore(zkey, "-inf", now - WINDOW_SECONDS)
        if r.zcard(zkey) >= settings.rate_limit_per_minute:
            oldest = r.zrange(zkey, 0, 0, withscores=True)
            # Lấy timestamp cũ nhất trong window để tính thời điểm mở lại.
            oldest_score = oldest[0][1] if oldest else now
            retry_after = max(1, int(oldest_score + WINDOW_SECONDS - now) + 1)
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Rate limit exceeded",
                    "limit": settings.rate_limit_per_minute,
                    "window_seconds": WINDOW_SECONDS,
                    "retry_after_seconds": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(settings.rate_limit_per_minute),
                    "X-RateLimit-Remaining": "0",
                },
            )
        pipe = r.pipeline()
        pipe.zadd(zkey, {f"{now:.6f}": now})
        pipe.expire(zkey, WINDOW_SECONDS + 5)
        pipe.execute()
    except HTTPException:
        raise
    except Exception:
        return  # Redis lỗi tạm thời → không chặn request vì rate limit.
