"""Config — 12-Factor: mọi cấu hình đọc từ biến môi trường."""
import os
from dataclasses import dataclass


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


@dataclass
class Settings:
    port: int = 8000
    environment: str = "development"
    agent_api_key: str = ""
    redis_url: str = ""
    rate_limit_per_minute: int = 10
    daily_budget_usd: float = 1.0
    monthly_budget_usd: float = 10.0


settings = Settings(
    port=_int("PORT", 8000),
    environment=os.getenv("ENVIRONMENT", "development"),
    # Không có giá trị mặc định tiện tay — key phải được cấp qua biến môi trường.
    agent_api_key=os.getenv("AGENT_API_KEY", ""),
    redis_url=os.getenv("REDIS_URL", ""),
    rate_limit_per_minute=_int("RATE_LIMIT_PER_MINUTE", 10),
    daily_budget_usd=_float("DAILY_BUDGET_USD", 1.0),
    monthly_budget_usd=_float("MONTHLY_BUDGET_USD", 10.0),
)
