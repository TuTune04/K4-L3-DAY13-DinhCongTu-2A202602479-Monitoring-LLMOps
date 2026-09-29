# Báo cáo cá nhân — K4-L3A Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Đinh Công Tú
- **MSSV:** 2A202602479
- **Lớp:** K4-L3A
- **Repository URL:** https://github.com/TuTune04/K4-L3-DAY13-DinhCongTu-2A202602479-Monitoring-LLMOps
- **Commit SHA cuối:**
- **Challenge ID:**
- **Tên project Langfuse cá nhân:** `day13-k4-l3a-02479`

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Pytest cuối | `evidence/01-pytest.png` |
| Log validator | `evidence/02-log-validator.png` |
| Dashboard validator | `evidence/03-dashboard-validator.png` |
| Structured log | `evidence/04-structured-log.png` |
| PII redaction | `evidence/05-pii-redaction.png` |
| Trace list | `evidence/06-trace-list.png` |
| Trace waterfall | `evidence/07-trace-waterfall.png` |
| Trace metadata | `evidence/08-trace-metadata.png` |
| Prompt versions | `evidence/09-prompt-versions.png` |
| Prompt rollback | `evidence/10-prompt-rollback.png` |
| Dashboard runtime | `evidence/11-dashboard-overview.png` |
| Incident metric | `evidence/12-incident-metric.png` |
| Incident log | `evidence/13-incident-log.png` |
| Incident trace | `evidence/14-incident-trace.png` |

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 — 23 records, 20 thiếu required fields, 20 thiếu enrichment, 0 correlation ID, 0 PII leak | 100/100 — 20 records, 0 thiếu required, 0 thiếu enrichment, 10 correlation ID, 0 PII leak | Baseline CP0; FAILED required fields / correlation ID / enrichment, PASSED PII scrubbing |
| `validate_dashboard.py` | HỢP LỆ: 6/6 panel có trong dashboard contract | HỢP LỆ: 6/6 panel | Baseline CP0 |
| `pytest` | 22 passed | 27 passed (CP2) | Chạy bằng `.venv/bin/python -m pytest -q` (Python 3.12) |
| Số traces hợp lệ | 10 trace `lab-agent-run` từ load test | 26 trace (CP2), mỗi trace có `retrieval` + `llm-generation` | Xác nhận qua Langfuse Observations API v2, project `day13-k4-l3a-02479`; `userId` đều là hash 12 ký tự |
| Số PII leak | 0 | 0 | Log và trace chỉ chứa preview đã scrub |
| Latency P95 / TTFT P95 | | 545 ms / 50 ms | Dashboard, 60 phút, không incident |
| Retrieval success rate | | 100% | Error rate 0% |

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** `CorrelationIdMiddleware` gọi `clear_contextvars()` đầu mỗi request, lấy header `x-request-id` nếu client gửi, nếu không thì sinh `req-<8-hex>` từ `uuid4`. ID được `bind_contextvars` để mọi log trong request đều có `correlation_id`, lưu vào `request.state` để truyền cho agent/trace, và trả lại qua header `x-request-id` cùng `x-response-time-ms`.
- **Các metadata được ghi vào structured log:** `ts`, `level`, `service`, `event`, `correlation_id`; enrichment `user_id_hash` (SHA-256 cắt 12 ký tự), `session_id`, `feature`, `model`, `env` được bind trong `/chat` trước `request_received`; `response_sent` thêm `latency_ms`, `ttft_ms`, `tokens_in/out`, `cost_usd`, `quality_score`, `tool_name`, `tool_success`.
- **Cách bảo đảm PII được scrub trước khi ghi:** processor `scrub_event` đứng trước `JsonlFileProcessor` và `JSONRenderer`, scrub mọi giá trị string ở top-level và trong `payload`. `app/pii.py` có pattern cho thẻ, CCCD, email, số điện thoại VN và hộ chiếu; pattern số dài chạy trước để `phone_vn` không cắt mất một phần số thẻ/CCCD. User ID chỉ ghi dưới dạng hash.
- **Cách kiểm chứng kết quả:** đổi tên log baseline thành `data/logs.cp0-baseline.jsonl`, chạy load test mới rồi `validate_logs.py` đạt 100/100; `pytest` 26 passed (thêm test CCCD, thẻ, hộ chiếu, text thường không bị đổi); `curl` `/chat` trả `x-request-id: req-xxxxxxxx`, gửi `x-request-id: req-deadbeef` thì nhận lại đúng ID; log của câu hỏi chứa email chỉ còn `[REDACTED_EMAIL]`.

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:** gọi Langfuse Public API bằng key trong `.env` của tôi: `/api/public/projects` trả đúng project `day13-k4-l3a-02479`, `/api/public/v2/observations` trả các trace có `correlation_id` trùng với log local (ví dụ `req-b1a5e001`).
- **Cấu trúc root/retrieval/generation observations:** root `lab-agent-run` (type AGENT, `@observe`, không capture input/output) → con `retrieval` (RETRIEVER, input là `query_preview` đã scrub, output `doc_count`) → con `llm-generation` (GENERATION, có `model`, link tới prompt `day13-chat`, `usage_details` input/output, `cost_details` input/output/total, metadata `ttft_ms`). Hai observation con có `parentObservationId` là root, nên waterfall cho thấy ngay bước nào chậm.
- **Cách nối trace với log:** `correlation_id` từ middleware được truyền vào `LabAgent.run` và đưa vào trace metadata qua `propagate_attributes`; cùng giá trị đó có trong mọi dòng log của request. Tìm log → lấy `correlation_id` → lọc metadata trên Langfuse (hoặc ngược lại).
- **Prompt name:** `day13-chat` (text prompt)
- **Version/label baseline:** v1 — labels `baseline`, `production`; template gốc `Feature/Docs/Question`.
- **Version/label candidate:** v2 — label `candidate`; thêm dòng `Answer in at most 3 concise bullet points.` (`tokens_in` 36 → 47 với cùng input).
- **Trace ID của mỗi version:** cùng input `Explain the monitoring policy`:
  - baseline v1: `d03d1363a6117941e037e26bb89589a7` (`req-b1a5e001`)
  - candidate v2: `cecb566c8204ea89edb7e38f28ee8099` (`req-cad1d002`)
  - production sau khi promote → v2: `13633b8b1841b0f975d6051491d18b4e` (`req-a0d00002`)
  - production sau khi rollback → v1: `decd785d6239c758ac70a8367ffff88a` (`req-a0d00001`)
- **Cách promote và rollback `production`:** `langfuse.update_prompt(name="day13-chat", version=2, new_labels=["candidate", "production"])` chuyển label `production` từ v1 sang v2 (Langfuse tự gỡ label khỏi v1); rollback bằng `update_prompt(version=1, new_labels=["baseline", "production"])`. App chỉ đọc label `production` (cache 60 s), nên rollback không cần deploy lại code. Trace sau mỗi bước ghi đúng `prompt_version`.

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:** `python scripts/dashboard.py` (stdlib + PyYAML) mở http://127.0.0.1:8050, đọc `data/logs.jsonl` và `config/dashboard.yaml`, time range 60 phút, auto refresh 30 s. Mỗi panel có tên, đơn vị, đường threshold nét đứt đỏ và badge OK/VƯỢT NGƯỠNG: (1) latency P50/P95/P99 + TTFT P95, (2) request/phút, (3) error rate + breakdown `error_type` + retrieval success, (4) cost theo phút + lũy kế, (5) tokens_in/tokens_out lũy kế, (6) mean quality. Baseline: P95 545 ms, TTFT P95 50 ms, error 0%, retrieval 100%, cost $0.055, tokens 967/3 490, quality 0.86. Traffic 0.47 req/phút dưới ngưỡng ≥ 1 vì chỉ có load test rời rạc.
- **SLO và lý do chọn:** giữ SLO `fast_successful_requests`: 99.5% request trả `response_sent` trong ≤ 3000 ms, cửa sổ 28 ngày. 3000 ms gấp ~5.5 lần P95 baseline (545 ms) nên traffic bình thường không đốt budget, còn `rag_slow` (+2.5 s) vượt ngưỡng ngay. Chi tiết trong `config/slo.yaml`.
- **Cách tính error budget:** budget = 100% − 99.5% = 0.5%, tức 50 request xấu trên 10 000 request, hoặc 0.5% × 28 ngày = 201.6 phút (≈ 3 giờ 22 phút) sự cố toàn phần. Error rate 2% (ngưỡng alert 2) đốt budget nhanh gấp 4 lần, giữ liên tục sẽ hết budget sau 7 ngày.
- **Ba alert và runbook tương ứng:** trong `config/alert_rules.yaml` và `docs/alerts.md`, cùng kênh Slack `#day13-l3a-alerts`:
  - `high_latency_p95` (P2): P95 > 3000 ms trong 5 phút → runbook `docs/alerts.md#alert-1`
  - `high_error_rate` (P1): error rate > 2% trong 5 phút → `docs/alerts.md#alert-2`
  - `cost_per_request_spike` (P3): cost trung bình > 0.004 USD/request (gấp 2 baseline 0.002) trong 15 phút → `docs/alerts.md#alert-3`

## 7. Điều tra challenge

- **Challenge ID:**
- **Khoảng thời gian điều tra:**
- **Triệu chứng từ metrics:**
- **Log line và correlation ID liên quan:**
- **Trace ID và span gây ảnh hưởng:**
- **Root cause:**
- **Fix action:**
- **Preventive measure:**

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:**
- **Một lỗi/blocker đã gặp:**
- **Cách tìm nguyên nhân và xử lý:**
- **Cách hiểu luồng Metrics → Logs → Traces:**
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:**
- **Điều quan trọng nhất đã học:**
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:**

## 9. Checklist trước khi nộp

- [ ] Kết quả và evidence thuộc commit SHA cuối.
- [ ] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [ ] Incident evidence nối đúng metric → log → trace.
- [ ] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [ ] Repository chạy lại được theo README.
- [ ] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [ ] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
