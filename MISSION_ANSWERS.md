# Day 14 Lab — Mission Answers

> 👤 **Luong Thi Hong Hanh** · **2A202603748** · Ngày làm: 26/11/2026

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns tìm thấy trong `01-localhost-vs-production/develop/app.py`

Tìm thấy **8 anti-pattern** (yêu cầu tối thiểu 5):

1. **API key hardcode trong code** — `develop/app.py:17`
   ```python
   OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"
   ```
   PUSH lên GitHub là key lộ ngay lập tức; để xoá dấu vết phải xoá cả lịch sử git, không chỉ sửa code. Phải đọc từ biến môi trường.

2. **Log in ra secret** — `develop/app.py:34`
   ```python
   print(f"[DEBUG] Using key: {OPENAI_API_KEY}")  # log ra secret!
   ```
   Tôi đã chạy app và xác nhận secret thực sự lọt vào stdout:
   ```
   [DEBUG] Got question: Hello
   [DEBUG] Using key: sk-hardcoded-fake-key-never-do-this   ← key lộ trong log
   ```
   Log thường được thu về log aggregator (Datadog, Loki…) cho nhiều người thấy — secret trong log = leak dài hạn.

3. **Không có health check endpoint** — `develop/app.py` (không có route `/health` nào)
   Tôi xác nhận: `curl -o /dev/null -w '%{http_code}' http://localhost:8001/health` trả **404**.
   Nếu agent crash hoặc treo, platform (Railway/Render/k8s) không biết để restart — container "zombie".

4. **Port và host cố định, không đọc từ env** — `develop/app.py:51–52`
   ```python
   host="localhost",   # chỉ nhận kết nối từ chính máy đó
   port=8000,          # cứng — trên Railway/Render PORT được inject qua env var
   ```
   `host="localhost"` có nghĩa kể cả khi deploy, không bên ngoài nào kết nối được vào container. Must bind `0.0.0.0` và đọc port từ `PORT`.

5. **`reload=True` bật trong production** — `develop/app.py:53`
   Watch-file reloader tốn CPU vì liên tục quét filesystem, và có thể reload ngay giữa request — gây lỗi khi đang serve traffic.

6. **Hardcode credential thứ hai: `DATABASE_URL` chứa password dạng plaintext** — `develop/app.py:18`
   ```python
   DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"
   ```
   Giống anti-pattern 1 nhưng nguy hiểm hơn vì đây là credential của database.

7. **Không có graceful shutdown** — không xử lý SIGTERM; bị kết thúc giữa chừng thì request đang chạy bị cắt ngang, client nhận lỗi 5xx không rõ nguyên nhân.

8. **Cấu hình trộn lẫn trong code, không tách module config** — `DEBUG = True`, `MAX_TOKENS = 500` viết cứng ở `develop/app.py:21–22`; muốn đổi giá trị cho môi trường khác phải sửa code và deploy lại. Bản production tách hết ra `config.py` đọc từ env.

### Exercise 1.2: Kết quả chạy bản basic

Đã chạy `python app.py` trong `01-localhost-vs-production/develop/`. Cổng 8000 trên máy này có service khác chiếm trước nên tôi chạy thử ở cổng 8001 để kiểm tra — code gốc vẫn hardcode 8000, đó chính là anti-pattern số 4:

```bash
$ curl -X POST "http://localhost:8001/ask?question=Hello"
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}   # HTTP 200 ✓
```

Quan sát thêm:
- Gọi đúng chuẩn JSON body `{"question":"Hello"}` → **422** vì app chỉ nhận `question` dạng query param — API contract khác hẳn bản production.
- `GET /health` → **404** (không có health check).
- Stdout chứa dòng log lộ API key (xem anti-pattern 2).

Chạy được nhưng **không production-ready**: chỉ cần một crash hoặc secret lộ là không có cơ chế nào phát hiện, cảnh báo hoặc tự phục hồi.

### Exercise 1.3: So sánh basic (develop) với advanced (production)

Đã chạy bản production (`PORT=8002 python app.py`) và test thực tế:

```bash
$ curl http://localhost:8002/health   → 200 {"status":"ok","uptime_seconds":12.2,...}
$ curl http://localhost:8002/ready    → 200 {"ready":true}
$ curl -X POST http://localhost:8002/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
  → 200 {"question":"Hello","answer":"Agent đang hoạt động tốt!...","model":"gpt-4o-mini"}
```

Bảng so sánh (so sánh `develop/app.py` với `production/app.py` + `production/config.py`):

| Feature | Basic (develop) | Advanced (production) | Tại sao quan trọng? |
|---------|-----------------|----------------------|---------------------|
| Config | Hardcode trong code (`OPENAI_API_KEY = "sk-..."`) | `config.py` đọc từ env vars, có `validate()` fail-fast | Đổi cấu hình không cần sửa code/deploy lại; secret không bao giờ nằm trong git |
| Secret trong log | `print(f"Using key: {key}")` — key lọt ra stdout | Log chỉ `question_length`, `client_ip` — không log secrets | Log được thu tập trung cho nhiều người đọc; secret trong log là leak |
| Logging | `print()` không cấu trúc, không có level | Structured JSON với timestamp + level, tắt DEBUG theo env | Máy/proxy đọc được để alert, filter, trace — print() chỉ dành cho người xem terminal |
| Health check | Không có (`/health` → 404) | `/health` (liveness) + `/ready` (readiness) | Platform biết khi nào cần restart và khi nào được nhận traffic |
| Readiness | Không có | Cờ `is_ready`, trả 503 khi chưa sẵn sàng | Load balancer không route traffic vào container đang khởi động |
| Shutdown | Bị cắt đột ngột giữa request | Xử lý SIGTERM, cho request đang chạy hoàn thành (`lifespan`) | Deploy/restart không gây lỗi 5xx cho client |
| Host/Port | `localhost:8000` cứng | `0.0.0.0:PORT` từ env | Không có thì container không nhận được kết nối từ ngoài — platform cấp port qua env var |
| Reload | `reload=True` luôn bật | `reload=settings.debug` — chỉ khi DEBUG=true | Reloader tốn CPU và restart phá traffic production |
| Metrics | Không có | `/metrics` Prometheus scrape được | Đo được uptime/hiệu năng để alert — nền tảng cho Part 7 |
| CORS | Không cấu hình | `CORSMiddleware` với `ALLOWED_ORIGINS` từ env | Chặn browser gốc lạ gọi tài nguyên nhạy cảm |
| API contract | `POST /ask?question=Hello` (query param) | JSON body `{question}` + 422 có nội dung | Dễ debug, dễ version hoá, tương thích với curl/docs |

### Tự kiểm tra CP1 — một anti-pattern production đã sửa (kèm dòng code)

- `develop/app.py:17`: `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` để trong source.
- `production/config.py:27` đọc từ env: `openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))`
- và **fail-fast** khi ở production thiếu key (`config.py:43`, trong hàm `validate()`):
  ```python
  if not self.api_key and self.environment == "production":
      raise ValueError("AGENT_API_KEY must be set in production!")
  ```

Nguyên nhân gốc của các anti-pattern trên là code viết phục vụ demo trên laptop. Bản production sửa dần từng lỗi theo nguyên tắc **12-Factor App**: config nằm trong biến môi trường, log ra stdout ở định dạng có cấu trúc, process tắt có kiểm soát.

---

## Part 2: Docker

### Exercise 2.1: Câu hỏi Dockerfile cơ bản (`02-docker/develop/Dockerfile`)

1. **Base image:** `python:3.11` — bản full Python distribution (~1 GB), chứa cả pip, build tools, docs… tốt cho môi trường phát triển nhưng nặng nếu deploy.
2. **Working directory:** `WORKDIR /app` — mọi lệnh `COPY`, `RUN`, `CMD` phía sau đều chạy trong `/app` và container khởi động tại đây.
3. **Tại sao COPY requirements.txt trước:** Docker build từng layer và cache theo thứ tự. Chỉ cần `requirements.txt` không đổi thì khi sửa code, layer `RUN pip install ...` vẫn dùng cache — không phải cài lại deps (tiết kiệm hàng phút mỗi lần build). Nếu `COPY . .` đứng trước, mọi thay đổi code đều invalidate cache của cả layer cài deps.
4. **CMD vs ENTRYPOINT:** `CMD` chỉ định command mặc định và **bị ghi đè hoàn toàn** khi `docker run <image> <command>`; `ENTRYPOINT` là executable cố định, tham số truyền ở `docker run` **được nối vào sau**. Thực dụng: `ENTRYPOINT` cho bin chính + `CMD` cho flag mặc định `("python", "app.py")`.

### Exercise 2.2: Build và run bản develop (kết quả thực tế)

```bash
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
$ docker run -p 8000:8000 -d --name agent-dev my-agent:develop

$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":2.6,"container":true}        # HTTP 200 ✓

# app chỉ nhận query param (khác contract JSON body):
$ curl "http://localhost:8000/ask?question=What+is+Docker%3F" -X POST
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}   # HTTP 200 ✓

$ docker images my-agent:develop
my-agent   develop   1.67GB
```

Debug container: `docker logs agent-dev` in ra access log uvicorn; `docker exec -it agent-dev sh` vào được shell bên trong container.

### Exercise 2.3: Multi-stage build — so sánh kích thước image (đo bằng `docker images`)

```bash
$ docker build -f 02-docker/production/Dockerfile -t my-agent:production .
$ docker images --format 'table {{.Repository}}\t{{.Tag}}\t{{.Size}}' | grep my-agent
my-agent   production   265MB
my-agent   develop      1.67GB
```

- **Develop:** 1.67 GB ≈ 1 710 MB
- **Production:** 265 MB
- **Chênh lệch:** (1710 − 265) / 1710 × 100 ≈ **84,5% nhỏ hơn** ✓ (đạt yêu cầu < 500 MB)

**Stage 1 (builder) làm gì:** dùng `python:3.11-slim` + cài gcc/libpq-dev, `pip install --user` toàn bộ requirements vào `/root/.local` — nơi chứa cả toolchain biên dịch. Image này chỉ là giai đoạn trung gian, không được deploy.

**Stage 2 (runtime) làm gì:** bắt đầu từ `python:3.11-slim` sạch, chỉ `COPY --from=builder /root/.local` (packages đã cài — không có gcc, không pip cache), copy source, tạo **non-root user** `appuser`, thêm **HEALTHCHECK** gọi `/health`.

**Tại sao image nhỏ hơn:** toàn bộ build tools (gcc ~hàng trăm MB, apt cache, pip cache) nằm lại ở Stage 1; Stage 2 chỉ nhận kết quả cuối là thư viện runtime. Cộng thêm base `slim` thay vì full Python. (`--user` + copy `.local` cũng thấy rõ điều đó: deps không lẫn toolchain.)

### Exercise 2.4: Docker Compose stack — architecture và kết quả test

Sơ đồ stack (`02-docker/production/docker-compose.yml`):

```text
client (host, cổng 80/443)
   │
   ▼
┌─────────────── nginx:alpine ───────────────┐
│ reverse proxy + rate limit 10 r/s/IP       │
│ (limit_req burst=20, 429 khi vượt)         │
└──────┬─────────────────────────────────────┘
       │ proxy_pass → upstream agent_backend
       ▼
┌────────── agent:8000 (FastAPI) ────────────┐
│ không expose port ra host, chạy non-root   │
│ HEALTHCHECK /health mỗi 30s                │
└──────┬──────────────┬──────────────────────┘
       ▼              ▼
 redis:7-alpine   qdrant v1.9.0
 (cache, rate-    (vector DB cho RAG,
  limit; volume    volume qdrant_data)
  redis_data)
```

**4 service được start:** `agent`, `redis`, `qdrant`, `nginx`. **Chúng communicate thế nào:** cùng 1 bridge network tên `internal`; gọi nhau bằng tên service trong DNS của Docker (`agent:8000`, `redis://redis:6379/0`, `http://qdrant:6333`); agent có `depends_on` với `condition: service_healthy` nên chỉ lên sau khi redis và qdrant pass healthcheck; chỉ nginx có `ports` ra host, agent không expose port ra ngoài; dữ liệu redis và qdrant nằm ở volumes (`redis_data`, `qdrant_data`) nên tồn tại qua restart.

Kết quả test thực tế (đã chạy `docker compose -p k5-day14-docker up -d --build`):

```text
$ docker compose ... ps
SERVICE   STATUS
agent     Up 10 seconds (healthy)
nginx     Up 10 seconds
qdrant    Up 21 seconds (healthy)
redis     Up 21 seconds (healthy)

$ curl http://localhost/health
{"status":"ok","uptime_seconds":9.1,"version":"2.0.0",...}   → HTTP 200 ✓

$ curl http://localhost/ask -X POST -H "Content-Type: application/json" \
    -d '{"question": "Explain microservices"}'
{"answer":"Đây là câu trả lời từ AI agent (mock)...."}        → HTTP 200 ✓
```

Request đi qua Nginx (cổng 80) → round-robin tới upstream `agent_backend` → agent trả lời. Nginx áp rate limit `10 r/s` cho từng IP và trả 429 khi vượt burst 20; đường `/health` không bị rate limit.

> Ghi chú vận hành: compose khai báo `env_file: .env.local` nên tôi đã tạo `02-docker/production/.env.local` (nằm trong .gitignore) trước khi `up`, vì repo không có sẵn file này — compose sẽ lỗi nếu thiếu.


## Part 3: Cloud Deployment

### Deploy agent `06-lab-complete/` lên nền tảng chính: **Render** (Exercise 3.2)

- **URL public:** https://day14-production-agent-u0ci.onrender.com
- **Cách deploy:** Blueprint từ `06-lab-complete/render.yaml` (viết ở CP5, có `rootDir: 06-lab-complete`) — Render tạo 2 services: web `day14-production-agent` (runtime docker, health check `/health`) và Key Value `day14-redis` (Redis private, tự cấp `REDIS_URL` cho web service qua `fromService`).
- `AGENT_API_KEY` đặt bằng biến môi trường trên nền tảng (`generateValue: true`), không ghi vào code. Xem chi tiết trong [DEPLOYMENT.md](DEPLOYMENT.md).

**Kết quả 4 lệnh tự kiểm (đã chạy thật, dựa trên URL public):**

```text
$ curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"                          → 200
$ curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"                           → 200
$ curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'              → 401
$ curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" ... -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'                → 200
```

4 lệnh đều khớp kỳ vọng **200 / 200 / 401 / 200** (ảnh: `screenshots/test.png`, `screenshots/running.png`).

### So sánh `railway.toml` với `render.yaml` (nền tảng còn lại — Railway)

1. **Định dạng và phạm vi:** `railway.toml` chỉ là file cấu hình nhỏ (build/deploy của **một** service: builder DOCKERFILE, healthcheckPath, restart policy) — còn `render.yaml` là **Blueprint mô tả cả kiến trúc nhiều services**: khai báo thêm service Redis (`type: keyvalue`) và cách nối biến `REDIS_URL` từ Redis sang web service. Với Railway, Redis phải tạo riêng bằng CLI/dashboard rồi tự nối biến.
2. **Thứ cần kiểm soát khác nhau:** `railway.toml` tập trung vào **hành vi deploy** (restartPolicyType = ON_FAILURE, maxRetries = 3, healthcheckTimeout = 100s) — nhắm vào reliability khi deploy; `render.yaml` tập trung vào **nội dung stack** (plan, `rootDir`, `healthCheckPath`, `envVars`, secrets `generateValue`) — nhắm vào tái tạo được hạ tầng từ 1 file.
3. **Vì sao khác:** mỗi platform có mô hình khác nhau — Railway tự cấp PORT + domain và quan niệm "mỗi service 1 config", nên TOML chỉ cần khai báo override; Render Blueprint phải tự mô tả đủ (repo root, plan, service nối nhau) vì YAML đó chính là source of truth để tái tạo cả project. Kết quả cuối cùng như nhau: container health-checked, tự restart khi lỗi, có Redis + API key từ env var.

### Exercise 3.3 — Pipeline CI/CD Cloud Run (`03-cloud-deployment/production-cloud-run/`)

`cloudbuild.yaml` định nghĩa pipeline Cloud Build gồm 4 bước nối tiếp (dùng `waitFor`): **(1) test** — container `python:3.11-slim` cài requirements và chạy `pytest tests/`; **(2) build** — docker build image tag `gcr.io/$PROJECT_ID/ai-agent:$COMMIT_SHA` + `:latest` (dùng `--cache-from` cho layer cache); **(3) push** — đẩy image lên Google Container Registry; **(4) deploy** — `gcloud run deploy ai-agent` với image theo commit SHA, region `asia-southeast1`, `--min-instances=1` (tránh cold start) và `--max-instances=10`, memory 512Mi, secrets lấy từ Secret Manager. `service.yaml` khai báo phần lớn cấu hình runtime tương tự dưới dạng resource manifest (cpu, memory, scale, probes liveness/readiness trên `/health` và `/ready`, `--allow-unauthenticated` đi kèm API key auth trong app) để `gcloud run services replace service.yaml` — tách riêng "pipeline build" và "cấu hình service".

## Part 4: API Security

### Exercise 4.1: API Key authentication (`04-api-gateway/develop/app.py`)

- **API key được check ở đâu:** trong hàm `verify_api_key()`, dùng làm **FastAPI dependency** gắn vào endpoint `/ask` qua `Depends(verify_api_key)`. Nó đọc header `X-API-Key` (`APIKeyHeader(name="X-API-Key", auto_error=False)`) và so với `API_KEY = os.getenv("AGENT_API_KEY", ...)` — key đọc từ biến môi trường, không hardcode.
- **Nếu sai key:** thiếu header → **401 Unauthorized**; có header nhưng giá trị sai → **403 Forbidden**. Phân biệt 401/403: 401 = "chưa định danh", 403 = "đã định danh nhưng key này không được chấp nhận".
- **Làm sao rotate key:** vì key đọc từ env var, rotate = đặt giá trị `AGENT_API_KEY` mới trên nền tảng và restart/deploy lại. Demo chỉ hỗ trợ một key; trong production nên hỗ trợ **nhiều key cùng lúc** (key cũ + key mới cùng hợp lệ trong thời gian chuyển tiếp) để đổi không downtime, và key nên có prefix + ngày hết hạn.

Output `curl -i` thực tế (key đã che):

```text
# Không có key
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# Sai key
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

# Đúng key (X-API-Key: ****-***-123)
HTTP/1.1 200 OK
{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

(Chạy bằng `AGENT_API_KEY=secret-key-123 python app.py` theo lưu ý K5 số 6.)

### Exercise 4.2: JWT authentication (`04-api-gateway/production/`)

**JWT flow trong `auth.py`:** client `POST /auth/token` với username/password → server kiểm tra trong `DEMO_USERS` (`authenticate_user`), tạo JWT HS256 có payload `{sub: username, role, iat, exp}` ký bằng `JWT_SECRET` (env var, hết hạn sau 60 phút). Mỗi request sau đó gửi `Authorization: Bearer <token>`; `verify_token` decode + kiểm signature và expiry — **stateless**, không cần tra DB mỗi request. Payload của user: `student` = role `user`, `teacher` = role `admin`.

Mã HTTP của JWT: không gửi token → 401; token hết hạn → 401 (`ExpiredSignatureError`); token sai/temper → 403 (`InvalidTokenError`).

Output `curl -i` thực tế (token đã che):

```text
$ POST /auth/token  (username: student, password: demo123)
HTTP/1.1 200 OK
{"access_token":"eyJhbGciOiJI...(đã che, dài 168 ký tự)","token_type":"bearer","expires_in_minutes":60,...}

# Không gửi token
HTTP/1.1 401 Unauthorized
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# Gửi Bearer <token hợp lệ>
HTTP/1.1 200 OK
{"question":"Explain JWT","answer":"Đây là câu trả lời từ AI agent (mock)...",
 "usage":{"requests_remaining":9,"budget_remaining_usd":2.1e-05}}

# Gửi token giả
HTTP/1.1 403 Forbidden
{"detail":"Invalid token."}
```

### Exercise 4.3: Rate limiting (`rate_limiter.py`)

- **Algorithm:** **Sliding Window Counter** — mỗi user có một deque các timestamp; `check()` bỏ timestamps cũ hơn 60 giây, nếu số request trong window ≥ `max_requests` thì raise 429 kèm `Retry-After` (thời điểm request cũ nhất trong window + 60s). Chọn kỹ thuật nào trong số (token bucket, fixed window, sliding window): đây là **sliding window log** (biến thể counter), chính xác hơn fixed window (tránh bùng phát 2× limit ở ranh giới window).
- **Limit:** **10 requests/phút** với `rate_limiter_user` (role `user` — tài khoản `student`); **100 requests/phút** cho `rate_limiter_admin` (role `admin` — tài khoản `teacher`).
- **Bypass limit cho admin:** limit được chọn theo role trong `app.py` (`limiter = rate_limiter_admin if role == "admin" else rate_limiter_user`) — admin đã có 100/phút. Nếu cần bypass hẳn: cho admin key riêng (ví dụ check `role == "admin"` → skip limiter) — nhưng vẫn nên giữ một cap rất cao để chống abuse khi admin key bị lộ.
- State đang **in-memory** (`defaultdict(deque)`), tức bộ đếm chỉ đúng khi chạy 1 instance; khi scale nhiều instance thì các deque không nhìn thấy nhau và mỗi instance có limit riêng → phải chuyển sang Redis (đúng như Part 5/Part 6 dùng Redis).

Output vòng lặp 20 request (token student, đã gọi 1 lần ở 4.2 trước đó):

```text
req 1 → 200   req 2 → 200   ... req 9 → 200
req 10 → 429  req 11 → 429  ... req 20 → 429
```

Response 429 + headers (các dòng quan trọng):

```text
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795682383
retry-after: 33

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":46}}
```

### Exercise 4.4: Cost guard

**Cách bản `04-api-gateway/production/cost_guard.py` đang làm (in-memory):**
- Đếm token theo từng ngày bất kể thời điểm chạy; qua ngày mới, `_get_record()` tự tạo record mới → chi phí tự động reset mỗi ngày;
- Giá token tham chiếu GPT-4o-mini: $0.00015/1K input, $0.0006/1K output;
- `check_budget()` chạy **trước** khi gọi LLM: tổng toàn hệ thống vượt **global budget $10/ngày** → **503** (service unavailable); user riêng vượt **$1/ngày** → **402 Payment Required**; và cảnh báo warning ở **80%** budget (`warn_at_pct=0.8`);
- `record_usage()` ghi nhận thực tế sau khi gọi LLM xong, cộng chi phí vào record của user và global cost.
- Check của tôi qua `/me/usage` sau 10 request: `cost_usd: 0.000188 / budget 1.0` — cơ chế hoạt động.

**Cách làm cost guard như Exercise đề bài — Redis key `budget:{user_id}:{YYYY-MM}`, $10/tháng:**

```python
import redis
from datetime import datetime

r = redis.Redis(decode_responses=True)

def check_budget(user_id: str, estimated_cost: float) -> bool:
    """
    Return True nếu còn budget (và ghi nhận chi phí này), False nếu vượt.
    - Budget $10/tháng/user, track trong Redis
    - Reset đầu tháng: tên key có month → tháng mới = key mới tự nhiên
    """
    month_key = datetime.now().strftime("%Y-%m")
    key = f"budget:{user_id}:{month_key}"

    current = float(r.get(key) or 0)
    if current + estimated_cost > 10:   # chặn nếu vượt quá ngưỡng
        return False

    pipe = r.pipeline()
    pipe.incrbyfloat(key, estimated_cost)
    pipe.expire(key, 32 * 24 * 3600)    # TTL 32 ngày > một tháng, tự dọn dẹp
    pipe.execute()
    return True
```

Tại sao phải dùng Redis chứ không RAM: cost guard phải **chặt chẽ khi chạy nhiều instance** — RAM của từng instance không nhìn thấy nhau khiến tổng chi phí vượt budget gấp số instance; Redis là điểm đếm dùng chung. Cùng lý do mà rate limiter của Part 5/Part 6 cũng dùng Redis. Thứ tự thao tác quan trọng: check **trước** khi gọi LLM (chặn trước, không uổng tiền gọi hụt), tính theo **estimated_cost** (ước lượng theo giới hạn `max_tokens` của request), ghi chi phí thực tế sau đó — để không có request lớn nào đục thủng budget.

Tại sao cần cả rate limit (bảo vệ tốc độ/nguồn lực) **và** cost guard (bảo vệ tiền): rate limit chặn spam theo tần suất nhưng không để mắt đến chi phí từng request (ít request mà prompt dài vẫn đốt tiền); cost guard khống chế tổng tiền nhưng chỉ can thiệp **sau** khi tiền đã đổ vào. Hai lớp chặn đủ cặp rủi ro: quá nhanh (429) và quá đắt (402/503).

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks (`05-scaling-reliability/develop/app.py`)

App chuẩn bị sẵn cả hai endpoint — kết quả chạy thật (`python app.py`, cổng 8000):

```text
$ curl http://localhost:8000/health    → HTTP 200
{"status":"ok","uptime_seconds":10.3,"version":"1.0.0","environment":"development",
 "timestamp":"...","checks":{"memory":{"status":"ok","note":"psutil not installed"}}}

$ curl http://localhost:8000/ready     → HTTP 200
{"ready":true,"in_flight_requests":1}
```

**Liveness khác readiness ở chỗ nào:**
- `/health` (liveness) hỏi *"process còn sống không?"* — chỉ phụ thuộc chính process này. Trả non-200/timeout ⇒ platform **restart container**. Nó **không được** phụ thuộc dependency bên ngoài, vì Redis chết mà liveness fail ⇒ platform restart tất cả các container agent luôn ⇒ cả cụ sập vì lỗi của một phụ thuộc.
- `/ready` (readiness) hỏi *"sẵn sàng nhận traffic?"* — check Redis/DB (`r.ping()`, `SELECT 1`); fail ⇒ trả **503** và load balancer **ngừng route traffic vào** instance đó, nhưng **không restart**. Redis chết ⇒ chỉ instance báo not-ready rồi quay lại là được traffic khi Redis sống lại.
- Vì vậy ở CP5: `/health` phải trả 200 kể cả khi Redis chết, còn `/ready` phải trả 503 — đó chính là quy tắc hai probe này.

### Exercise 5.2: Graceful shutdown

App này làm 3 việc khi nhận SIGTERM (đúng 4 bước đề bài: 1. dừng nhận request mới — uvicorn đóng listener; 2. hoàn thành request đang chạy — middleware đếm `_in_flight_requests`, lifespan chờ tối đa 30s; 3. đóng connections; 4. exit):

Test thực tế: `kill -TERM <pid>`, log của server:

```text
INFO: Received signal 15 — uvicorn will handle graceful shutdown
INFO: Shutting down
INFO: Waiting for application shutdown.
INFO: 🔄 Graceful shutdown initiated...
INFO: ✅ Shutdown complete
INFO: Application shutdown complete.
INFO: Finished server process [23947]
```

Process thoát với exit code 0, không request nào bị cắt (mock LLM phản hồi rất nhanh nên không có request nào đang in-flight lúc kill). Trên nền tảng orchestration thật (Kubernetes), platform còn chờ `terminationGracePeriodSeconds` trước khi SIGKILL — request dài vẫn kịp hoàn thành.

### Exercise 5.3: Stateless design (`production/app.py`)

Sự khác biệt so với anti-pattern: state (session + history) **không có biến module-level** nào cả. Toàn bộ đi qua storage key trong Redis với TTL:

```python
# production/app.py — không còn conversation_history = {} trong RAM
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")   # từ env, qua compose
def save_session(sid, data, ttl_seconds=3600): _redis.setex(f"session:{sid}", ttl_seconds, ...)
def load_session(sid): return _redis.get(f"session:{sid}") ...
def append_to_history(sid, role, content):    # giữ tối đa 20 messages rồi save
```

Vì sao phải vậy: mỗi container có RAM riêng — instance 1 lưu session của user trong dict của nó thì request tiếp theo bị Nginx round-robin sang instance 2 → không tìm thấy session ⇒ bug. Lưu vào Redis thì **bất kỳ instance nào cũng đọc/ghi được state dùng chung** — instance nào chết cũng không mất dữ liệu. (App vẫn có fallback `_memory_store` khi không có Redis nhưng in log `⚠️ not scalable!` — chỉ để chạy demo 1 instance.)

### Exercise 5.4: Load balancing — chạy stack 3 instance

```bash
touch 05-scaling-reliability/production/.env.local          # compose cần file này (lưu ý K5 số 5)
docker compose -p k5-day14-scaling \
  -f 05-scaling-reliability/production/docker-compose.yml up -d --build --scale agent=3
```

Trạng thái sau khi up:

```text
SERVICE   STATUS
agent     Up (healthy)   ×3 repliche
nginx     Up             (cổng host 8080 → container 80)
redis     Up (healthy)
```

Lưu ý K5 số 7: stack này mở **cổng 8080** và endpoint là **`POST /chat`** (không phải cổng 80/`/ask` như CODE_LAB.md).

Phân tán request qua Nginx — gọi 10 lần cùng session in `served_by`:

```text
req 1 → instance-97dcc2   req 2 → instance-119fdd  req 3 → instance-79a54c
req 4 → instance-97dcc2   req 5 → instance-119fdd  req 6 → instance-79a54c
req 7 → instance-97dcc2   req 8 → instance-119fdd  req 9 → instance-79a54c
req 10 → instance-97dcc2          # 3 instance chia đều — Nginx round-robin
```

### Exercise 5.5: Test stateless (`test_stateless.py`)

Kết quả chạy `python test_stateless.py` (BASE_URL `http://localhost:8080`):

```text
Session ID: 2bed15eb-2dc4-4c83-a6b9-79642a0a4fe7
Request 1: [instance-119fdd]  Q: What is Docker?
Request 2: [instance-79a54c]  Q: Why do we need containers?
Request 3: [instance-97dcc2]  Q: What is Kubernetes?
Request 4: [instance-119fdd]  Q: How does load balancing work?
Request 5: [instance-79a54c]  Q: What is Redis used for?
Total requests: 5
Instances used: {'instance-97dcc2', 'instance-79a54c', 'instance-119fdd'}
✅ All requests served despite different instances!
--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

**Giải thích kết quả:** 5 request rơi vào **3 instance khác nhau** nhưng turn thêm dần 1→2→3, history đủ 10 messages (5 câu hỏi + 5 câu trả lời) — vì history lưu trong Redis key `session:{id}` chứ không phải RAM của từng instance, nên request đến instance nào cũng nối tiếp được conversation.

**Kiểm tra mạnh hơn nữa: kill instance giữa conversation** — dừng container `k5-day14-scaling-agent-1`, gọi tiếp cùng session:

```text
$ docker stop k5-day14-scaling-agent-1      # còn 2 agent + nginx + redis
$ POST /chat (cùng session)                 → HTTP 200
{"turn": 11, "served_by": "instance-79a54c", "storage": "redis"}     # vẫn nhận, turn 11
$ GET /chat/{session}/history               → 20 messages, đầy đủ kể cả msg sau khi kill
```

Quan sát vận hành đáng lưu ý: request gửi **ngay lập tức** sau `docker stop` bị treo ~60 giây rồi mới trả — Nginx giữ pool connection tới instance vừa chết; nhờ `proxy_next_upstream error timeout http_503` + `resolver ... valid=10s`, các request tiếp theo tự phục hồi và chỉ còn 2 instance phục vụ. Trong production nên thêm active health check hoặc `max_fails=2 fail_timeout=10s` trên upstream để drop instance chết chủ động thay vì chịu 1 request chậm.

Xong thì dọn dẹp: `docker compose -p k5-day14-scaling -f 05-scaling-reliability/production/docker-compose.yml down`.

## Part 6: Final Project — PASS 12/12

Hoàn thành các TODO trong `06-lab-complete/`: `app/config.py` (12-Factor env), `app/redis_client.py` (lazy connect, `redis_healthy()`), `app/auth.py` (401), `app/rate_limiter.py` (429, Redis ZSET sliding window + Retry-After, state sống sót qua restart), `app/cost_guard.py` (402, đếm daily `cost:{key}:{date}` + monthly), `app/main.py` (/health luôn 200, /ready 503 khi Redis chết, JSON logging bằng custom Formatter, lifespan shutdown), Dockerfile multi-stage (2 FROM, slim, non-root, HEALTHCHECK, `CMD ["sh","-c","exec uvicorn ... ${PORT:-8000} ... --workers 2"]`), compose agent+redis, `.dockerignore` (`.env`, `__pycache__`, `venv`), `.env.example` đủ biến, `railway.toml` + `render.yaml`.

Kết quả chấm thực tế — `python check_production_ready.py` (chạy đầy đủ, có Docker):

```text
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
```

Chi tiết đáng chú ý từ output chấm: image **262 MB** (< 500 MB); 429 sau **5** request đúng `RATE_LIMIT_PER_MINUTE=5` do env; **402 ở request thứ 2** khi budget bị ép về `0.000001`; restart agent **vẫn 429** (state trong Redis); `/ready` **503** khi Redis mất kết nối trong khi `/health` vẫn **200**; `docker stop` tắt êm — **exit code 0, 0.7s**; SIGTERM giữa chừng thì request đang chạy vẫn **200**.
