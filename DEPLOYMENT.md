# Deployment Information

## Public URL

https://day14-production-agent-u0ci.onrender.com

## Platform

**Render** (Blueprint từ `06-lab-complete/render.yaml`)

- Web Service: `day14-production-agent` (runtime `docker`, build từ `Dockerfile` multi-stage trong `06-lab-complete/`, health check `/health`)
- Key Value: `day14-redis` (Redis managed của Render, private — chỉ nhận kết nối từ service trong cùng environment, cấp `REDIS_URL` cho web service qua `fromService`)

## Test Commands

### Health Check

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://day14-production-agent-u0ci.onrender.com/health
# 200
# body: {"status":"ok","uptime_seconds":...}

curl -s -o /dev/null -w '%{http_code}\n' https://day14-production-agent-u0ci.onrender.com/ready
# 200 (kiểm tra Redis: xuống 503 nếu Redis chết)
```

### Authentication required (không có key)

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://day14-production-agent-u0ci.onrender.com/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"Hello"}'
# 401 — {"detail":"Missing or invalid API key. Include header: X-API-Key: <your-key>"}
```

### API Test (with authentication)

```bash
curl -s -X POST https://day14-production-agent-u0ci.onrender.com/ask \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  --data-raw '{"question":"hello from render"}'
# 200 — {"question":"hello from render","answer":"Đây là câu trả lời từ AI agent (mock). ...","usage":{"input_tokens":6,"output_tokens":34,"cost_usd":2.1e-05}}
```

### Kết quả 4 lệnh tự kiểm của CP6 (đã chạy thật)

| # | Lệnh | Kết quả |
| --- | --- | --- |
| 1 | `GET /health` | **200** |
| 2 | `GET /ready` | **200** |
| 3 | `POST /ask` không key | **401** |
| 4 | `POST /ask` có `X-API-Key` | **200** + JSON `answer` |

Ảnh chứng minh: `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png`.

> Free tier Render: instance đi ngủ sau ~15 phút không có request; lần gọi đầu có thể chờ ~30–50 giây (cold start) rồi trả lại 200.

## Environment Variables Set

Biến môi trường đặt trên nền tảng (dashboard Render → Environment), **không hardcode trong code**:

- `AGENT_API_KEY` — generate tự động bởi Render (`generateValue: true` trong `render.yaml`)
- `REDIS_URL` — tự nối từ service Key Value `day14-redis` (connection string, internal)
- `RATE_LIMIT_PER_MINUTE=10`
- `DAILY_BUDGET_USD=1.0`
- `MONTHLY_BUDGET_USD=10.0`
- `PORT` — Render tự cấp cho process nghe

## Deploy pipeline

1. Push code (commit `06-lab-complete/` + `render.yaml` có `rootDir: 06-lab-complete`) lên GitHub `main`.
2. Render dashboard → **New → Blueprint** → chọn repo → Render đọc `render.yaml`, tạo 2 services (web + keyvalue).
3. Web service build Docker image (multi-stage, non-root) rồi chạy với health check `/health`; Redis tạo song song.
4. Deploy **tự động lại** khi có commit mới lên `main`.
