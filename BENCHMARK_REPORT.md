# Benchmark & Observability Report — Day 14

**Họ tên:** Luong Thi Hong Hanh — 2A202603748
**Ngày chạy:** 26/11/2026
**Môi trường:** macOS (Apple Silicon), Docker Desktop, agent chạy trong container `python:3.11-slim` (app `06-lab-complete/benchmark-observability/develop/`), load test / eval chạy bằng Python 3.15 + httpx trên máy host.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | User bắt đầu cảm thấy "lag" ở cỡ nửa giây; p95 đại diện cho 95% request, không bị 1 vài request outliers che giấu như average. |
| Error rate `/ask` | < 2 % | Cho phép lỗi nền từ upstream LLM (mock có `MOCK_ERROR_RATE=0.01`); vượt 2% nghĩa là có sự cố thật chứ không phải nhiễu. |
| Accuracy trên golden dataset | ≥ 80 % | 23 câu golden dataset — dưới 80% nghĩa là agent trả sai quá nhiều để đưa lên production; quality gate của lab yêu cầu không regression so với baseline. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

Số liệu từ `develop/reports/load_v2_c{1,10,50,100}.json` (300 requests/lần, MOCK_SLOW_RATE=0.03):

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.25 | 196.3 | 228.4 | 1705.9 | 1.67% | ✅ PASS |
| 10 | 39.26 | 195.7 | 224.6 | 1711.2 | 1.00% | ✅ PASS |
| 50 | 104.67 | 212.1 | 385.4 | 1717.5 | 0.67% | ✅ PASS |
| 100 | 42.50 | 724.0 | 4529.0 | 5078.6 | 0.33% | ❌ FAIL (p95) |

**Nhận xét:** RPS tăng gần tuyến tính từ c=1 → c=50 (4.25 → 104.67 req/s) vì agent chủ yếu `await asyncio.sleep` (I/O-bound, event loop còn rảnh). Từ c=50 lên c=100 RPS lại **giảm** xuống 42.5 và p95 nổ lên 4529ms: vượt quá sức xử lý của 1 process uvicorn (mặc định `MOCK_RETRIEVAL_MS` + sleep LLM), các request dồn hàng chờ — throughput không tăng thêm, latency tăng vọt. Đây là lý do phải scale ngang nhiều instance.

### 2.2 Tail latency

Số liệu từ `develop/reports/load_v2_slow_*.json` (300 requests, concurrency 20):

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 195.0 | 225.1 | 251.8 |
| 0.03 (mặc định) | 255.2 | 233.9 | 1713.6 |
| 0.1 | 407.4 | 1726.8 | 1918.6 |

**Nhận xét:** Chỉ số nhạy nhất là **p95/p99** (tail): chỉ 3% request chậm đã đẩy p99 từ 252ms lên 1714ms (gấp ~7 lần), trong khi p50 gần như không đổi (194→196→212ms). Average chỉ nhỉnh hơn một chút nên che giấu hiện tượng. SLO không nên đặt theo average vì user chịu rủi ro theo từng request: với 1000 request/ngày, 1% request chậm 1.7s = 10 user/phút gặp trải nghiệm tệ mà average vẫn "trông đẹp".

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Số liệu từ `develop/reports/eval_v1.json`, `eval_v2.json`, `eval_v2_fixed.json` (23 câu golden dataset):

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100% (23/23) |
| Avg tokens / câu | 57.1 | 108.7 | 118.7 |
| Tổng cost (USD) | 0.000405 | 0.000756 | 0.000834 |
| Cost / câu đúng (USD) | 0.00040455 | 0.00003599 | 0.00003628 |
| Quality gate | ❌ FAIL | ✅ PASS | ✅ PASS |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| security-02 | `token`, `hết hạn`, `chữ ký` | Câu "JWT khác gì API key trong xác thực?" không match entry nào trong `KNOWLEDGE_BASE` → trả lời generic. Thêm entry trigger `["jwt", "api key", "xác thực"]` với câu trả lời nhắc đủ: JWT là token có chữ ký số, có thời điểm hết hạn (exp), còn API key là chuỗi tĩnh phải rotate thủ công. |
| scaling-03 | `cpu`, `memory`, `custom metrics` | Câu "Kubernetes HPA scale dựa trên những chỉ số nào?" cũng rơi vào generic. Thêm entry trigger `["hpa", "kubernetes", "k8s"]` giải thích HPA scale theo CPU, memory và custom metrics. |

Sau khi sửa `KNOWLEDGE_BASE` (trong `develop/utils/mock_llm.py`, đã đồng bộ sang `production/utils/mock_llm.py` cho CP8), tắt rồi bật lại v2 (app không tự nạp lại code) và chạy:

```bash
python eval/run_eval.py --url http://localhost:8002 --min-accuracy 1.0 \
  --baseline reports/eval_v2.json --out reports/eval_v2_fixed.json
# Quality gate (accuracy ≥ 100%, không regression): ✅ PASS — exit code 0
# ✨ Câu được cải thiện : 2  |  ⚠️ Câu bị regression : 0
```

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:** v2 tốn gấp đôi token mỗi câu (108.7 vs 57.1) và chậm hơn ~40ms p95 (232.7 vs 192.4ms) vì phải chạy retrieval (RAG) trước khi sinh câu trả lời. Đổi lại accuracy tăng 4.3% → 91.3% (+87 điểm %) và **cost / câu đúng giảm hơn 11 lần** ($0.00040455 → $0.00003599). Cost / câu đúng là chỉ số công bằng hơn cost / câu: v1 "rẻ" vì phần lớn câu trả lời sai — tiền trả cho câu sai là tiền bỏ đi.

### Quality gate trong CI (Exercise 7.3)

`run_eval.py` trả **exit code 1** khi accuracy < `--min-accuracy` hoặc có regression so với baseline — kiểm chứng bằng cách chạy eval cho v1 với baseline v2: report in `❌ FAIL` (20 câu regression) và `exit_code=1`.

File job CI nộp kèm: `.github/workflows/quality-gate.yml` — bước chính:

```yaml
- name: Quality gate (eval ≥ 100%, không regression so với baseline)
  run: |
    python eval/run_eval.py --url http://localhost:8002 \
      --min-accuracy 1.0 --baseline reports/eval_v2.json --out reports/eval_ci.json
```

Exit code khác 0 → step fail → pull request không merge được. Như vậy một thay đổi làm câu trả lời tệ đi sẽ bị chặn ngay ở CI, trước khi kịp tới production.

---

## 4. Observability stack (production)

Stack bật bằng: `docker compose -p k5-day14-observability up -d --build --scale agent=1` (theo lưu ý K5 #7). Agent chạy image `benchmark-observability/production` (fix 1 lỗi skeleton: `useradd -d /app agent` làm user site-packages lệch đường dẫn → đổi thành `-d /home/agent`).

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals) — lưu `screenshots/grafana-dashboard.png`
- [x] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian) — lưu `screenshots/jaeger-slow-trace.png`
- [x] Một trace lỗi trong Jaeger (có event `exception`) — lưu `screenshots/jaeger-error-trace.png`
- [x] Trang Alerts của Prometheus với ít nhất 2 alert đang **firing** — lưu `screenshots/prometheus-alert-firing.png`

Bằng chứng API trạng thái alerts lúc 2 alert cùng firing: `screenshots/prometheus-alerts-api.json` (`AgentHighErrorRate` value 23.78% + `LLMCostBurnRateHigh` value $2.05/giờ, đều `state: firing`).

### 4.2 Thí nghiệm "phá hệ thống"

Giữ Locust chạy 30 users liên tục trong suốt thí nghiệm. Đổi cấu hình qua `.env` + `docker compose up -d`; thời điểm firing đọc từ Prometheus API `/api/v1/alerts` (poll 10s/lần).

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (critical) | điều kiện đúng t+24s, **firing t+~84s** (for: 1m); error rate 23.78%. Kèm theo: `LLMCostBurnRateHigh` firing ở phút thứ 5 ($2.05/giờ) | Panel Error rate đỏ; Jaeger thấy trace lỗi |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (warning) | điều kiện đúng khi traffic đều, **firing sau ~2 phút 6 giây** (for: 2m) | p95/p99 tăng vọt (~1.7–1.9s), avg tăng ít hơn |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (warning) | burn rate leo $3.7 → $17.6/giờ, **firing sau ~2 phút 40 giây** (for: 2m) | Panel Cost USD/giờ (tăng ~16 lần), LLM p95 tăng |
| D | `docker pause` 1 instance | `AgentInstanceDown` (critical) | pending t+16s, **firing t+48s** (up==0 đủ for: 30s + chu kỳ scrape) | Panel Instances up giảm 3→2; Locust thấy 504 nhưng Error rate của agent vẫn xanh |
| E | `AGENT_VERSION=v1` | **Không có** (chỉ còn dư âm cost alert từ C) | sau 90s không alert mới nào | Panel "version đang chạy" đổi thành v1, Retrieval hit ratio mất, tokens/câu giảm |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?** Đây là lỗi **chất lượng** (agent trả lời sai/nông), không phải lỗi hạ tầng — metrics RED/golden signals vẫn xanh. Cách phát hiện: (1) **eval chất lượng trên golden dataset** chạy định kỳ hoặc trong CI/CD (quality gate như Exercise 7.3 — chính là bước đã bắt được v1 4.3% vs v2 91.3%); (2) theo dõi **business metrics** từ dashboard (Retrieval hit ratio rớt về 0, tokens/câu giảm đột ngột) và đặt alert theo chúng; (3) synthetic checks — gửi câu hỏi biết-sẵn-đáp-án vào agent mỗi phút và so keyword. Bài học: "dashboard xanh ≠ agent đúng".

### 4.3 Debug bằng trace

Trace chậm nhất (tìm bằng log → Jaeger; span chậm nhất là span LLM, không phải code app):

- `trace_id`: `4af8deae735b2ff01a951f5b17dd2006`
- Tổng thời gian: **1727 ms**
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (**1699 ms, ~98%**) — còn lại `agent.run`, `agent.retrieve_context` chỉ chiếm vài chục ms → nút thắt nằm ở LLM provider, không phải code app.
- Dòng log tương ứng (grep theo `trace_id`, lưu trong `screenshots/trace-evidence.jsonl`):

```json
{"ts": "2026-11-26T16:14:15.158528+00:00", "level": "INFO", "service": "observable-agent", "instance": "149deca93f58", "event": "llm_call", "trace_id": "4af8deae735b2ff01a951f5b17dd2006", "span_id": "ef745ba056475385", "request_id": "d5fe596f363f", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 99, "output_tokens": 61, "cost_usd": 5.1e-05, "llm_ms": 1699.0}
{"ts": "2026-11-26T16:14:15.159501+00:00", "level": "INFO", "service": "observable-agent", "instance": "149deca93f58", "event": "http_request", "trace_id": "4af8deae735b2ff01a951f5b17dd2006", "span_id": "ef745ba056475385", "request_id": "d5fe596f363f", "method": "POST", "route": "/ask", "status": 200, "ms": 1727.1}
```

Trace lỗi (span `chat ...` có event `exception`, mock upstream 503):

```json
{"ts": "2026-11-26T16:12:29.165288+00:00", "level": "INFO", "service": "observable-agent", "instance": "1f051a3c0093", "event": "llm_error", "trace_id": "f95d3b17c3753ebe3b40cd93331ac77b", "span_id": "7f9a11a40774b762", "request_id": "61136c5e6ec5", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
{"ts": "2026-11-26T16:12:29.166181+00:00", "level": "INFO", "service": "observable-agent", "instance": "1f051a3c0093", "event": "http_request", "trace_id": "f95d3b17c3753ebe3b40cd93331ac77b", "span_id": "7f9a11a40774b762", "request_id": "61136c5e6ec5", "method": "POST", "route": "/ask", "status": 503, "ms": 123.3}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Số liệu từ `production/benchmark-results/scale_1_stats.csv` và `scale_3_stats.csv` (Locust headless `-u 100 -r 10 -t 2m --csv`, endpoint `/ask` qua Nginx):

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 57.53 | 200 | 810 | 1700 | 83/6872 (1.21%) |
| 3 | 58.37 | 200 | 590 | 1700 | 69/6927 (1.00%) |

**Giải thích kết quả:** Scale 1→3 **không tăng RPS** (57.5 → 58.4 req/s) vì 100 Locust users là tải cố định — mỗi user chờ response xong mới gửi tiếp, nên throughput bị chặn bởi số user × 1/latency, không phải bởi sức chứa hệ thống. Đổi lại **p95 giảm từ 810 → 590ms** (~27%): hàng chờ trên từng instance ngắn hơn khi Nginx chia tải đều. p99/p50 gần như không đổi vì p99 nằm ở nhóm request "slow" (mock 1.5s, đều như nhau ở mọi instance). Nút thắt thực sự nằm ở **LLM call** (sleep mô phỏng ~1700ms với 3% request) — nhìn panel LLM p95 của Grafana sẽ thấy đúng giá trị này; muốn tăng throughput thật phải tăng số users và scale agent song song, hoặc giảm latency LLM.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. **Average che giấu tail latency**: chỉ 3% request chậm đã đẩy p99 gấp ~7 lần trong khi p50 gần như không đổi — SLO phải đặt theo p95/p99 và alert phải dựa trên percentile, không phải mean.
  2. **Observability có 3 lớp trả lời 3 câu hỏi khác nhau**: metrics nói *có vấn đề không* (alert), traces nói *vấn đề nằm ở đâu* (span LLM chiếm 98%), logs nói *chi tiết sự kiện gì* (grep `trace_id` khớp từng request). Một mình một lớp là không đủ debug.
  3. **Metric của một service chỉ nhìn thấy những gì service đó thấy**: `docker pause` instance làm Locust ăn 504 từ Nginx nhưng Error rate của agent vẫn xanh (request chưa tới agent); và dashboard xanh không có nghĩa là agent trả lời đúng (thí nghiệm E) — cần eval + synthetic check + giám sát ở tầng LB.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?
  - **Alert theo SLO burn rate** (multi-window, vd 5m + 1h) thay vì ngưỡng cứng; alert disk/memory của container.
  - **Metric từ tầng vào trước agent**: 5xx/504 của Nginx (hoặc Ingress), số connection bị reject — như thí nghiệm D cho thấy.
  - **Business/quality metrics**: retrieval hit ratio alert khi về 0, eval accuracy chạy định kỳ, và alert khi tỉ lệ câu trả lời "từ chối/generic" tăng.
  - **Sampling trace** (vd 10% + luôn giữ trace lỗi và trace chậm > p99) để không phát tốn tiền khi traffic lớn, và `user_id` hash (không raw) nếu cần segment — nhưng chú ý cardinality.
