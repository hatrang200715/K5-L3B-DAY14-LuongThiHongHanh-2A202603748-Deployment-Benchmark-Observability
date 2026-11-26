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

### 4.1 Screenshot

- [ ] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals)
- [ ] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian)
- [ ] Một trace lỗi trong Jaeger (có event `exception`)
- [ ] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing**

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | | | |
| B | `MOCK_SLOW_RATE=0.3` | | | |
| C | `LLM_MODEL=mock-llm-large` | | | |
| D | `docker pause` 1 instance | | | |
| E | `AGENT_VERSION=v1` | | | |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

...

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được:

- `trace_id`: ...
- Tổng thời gian: ... ms
- Span chiếm nhiều thời gian nhất: ... (... ms, ...%)
- Dòng log tương ứng (grep theo `trace_id`):

```json

```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | | | | | |
| 3 | | | | | |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

...

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. ...
  2. ...
  3. ...
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?

...
