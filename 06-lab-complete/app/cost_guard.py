"""
Cost guard (tiêu chí 8): cộng dồn chi phí LLM vào Redis, chặn khi vượt budget.

Daily key:  cost:{key}:{YYYY-MM-DD}  — TTL 2 ngày
Monthly key: cost:{key}:month:{YYYY-MM} — TTL 40 ngày
Vượt DAILY_BUDGET_USD hoặc MONTHLY_BUDGET_USD → HTTP 402.
"""
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006


def _daily_key(key: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"cost:{key}:{today}"


def _monthly_key(key: str) -> str:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return f"cost:{key}:month:{month}"


def _spent(key: str) -> tuple:
    if r is None or not key:
        return None, None
    daily = float(r.get(_daily_key(key)) or 0.0)
    monthly = float(r.get(_monthly_key(key)) or 0.0)
    return daily, monthly


def check_budget(key: str) -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → HTTPException(402)."""
    if r is None or not key:
        return  # Không có Redis → không đếm được; /ready đã báo readiness.
    try:
        daily, monthly = _spent(key)
        if (
            settings.daily_budget_usd > 0
            and daily is not None
            and daily >= settings.daily_budget_usd
        ):
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "Budget exceeded",
                    "period": "daily",
                    "used_usd": round(daily, 6),
                    "budget_usd": settings.daily_budget_usd,
                },
            )
        if (
            settings.monthly_budget_usd > 0
            and monthly is not None
            and monthly >= settings.monthly_budget_usd
        ):
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "Budget exceeded",
                    "period": "monthly",
                    "used_usd": round(monthly, 6),
                    "budget_usd": settings.monthly_budget_usd,
                },
            )
    except HTTPException:
        raise
    except Exception:
        return  # Redis lỗi tạm thời → không chặn request vì budget.


def record_cost(key: str, input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí vào tổng daily/monthly, trả về chi phí request."""
    cost = (
        input_tokens / 1000 * PRICE_INPUT_PER_1K
        + output_tokens / 1000 * PRICE_OUTPUT_PER_1K
    )
    if r is None or not key:
        return cost
    try:
        pipe = r.pipeline()
        pipe.incrbyfloat(_daily_key(key), cost)
        pipe.expire(_daily_key(key), 2 * 24 * 3600)
        pipe.incrbyfloat(_monthly_key(key), cost)
        pipe.expire(_monthly_key(key), 40 * 24 * 3600)
        pipe.execute()
    except Exception:
        pass  # Không mất response của user vì lỗi ghi chi phí.
    return cost
