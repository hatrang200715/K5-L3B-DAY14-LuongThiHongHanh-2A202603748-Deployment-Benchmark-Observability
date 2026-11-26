"""
Production AI Agent — Part 6 Final Project.

Đủ 12 tiêu chí: /health, /ready, API key auth, rate limit (Redis),
cost guard (Redis), JSON logging, graceful shutdown.

Chạy: uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 2
"""
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask

START_TIME = time.time()


class JsonFormatter(logging.Formatter):
    """Mỗi dòng log của app là 1 JSON object hợp lệ."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(record.created)),
                "lvl": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            },
            ensure_ascii=False,
        )


def _setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]


logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_logging()
    logger.info(
        json.dumps({"event": "startup", "environment": settings.environment, "port": settings.port})
    )
    yield
    logger.info("shutdown — ngừng nhận request mới, chờ request đang chạy hoàn thành")


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.time()
    response = await call_next(request)
    logger.info(
        json.dumps(
            {
                "event": "request",
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "ms": round((time.time() - started) * 1000, 1),
            }
        )
    )
    return response


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = None


@app.get("/")
def root():
    return {"app": "Production AI Agent", "environment": settings.environment}


@app.get("/health")
def health():
    # Liveness: LUÔN 200 khi process còn chạy, kể cả khi Redis chết.
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "environment": settings.environment,
    }


@app.get("/ready")
def ready():
    # Readiness: Redis không kết nối được → 503, load balancer ngừng route traffic.
    if not redis_healthy():
        return JSONResponse(status_code=503, content={"ready": False, "detail": "Redis unavailable"})
    return {"ready": True}


@app.post("/ask")
def ask(body: AskRequest, key: str = Depends(verify_api_key)):
    check_rate_limit(key)        # 429 khi vượt giới hạn
    check_budget(key)            # 402 khi hết budget
    answer = llm_ask(body.question)

    input_tokens = len(body.question.split()) * 2
    output_tokens = len(answer.split()) * 2
    request_cost = record_cost(key, input_tokens, output_tokens)

    return {
        "question": body.question,
        "answer": answer,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                  "cost_usd": round(request_cost, 6)},
    }
