# Báo cáo cá nhân — K4-L3A Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Đinh Công Tú
- **MSSV:** 2A202602479
- **Lớp:** K4-L3A
- **Repository URL:** https://github.com/TuTune04/K4-L3-DAY13-DinhCongTu-2A202602479-Monitoring-LLMOps
- **Commit SHA cuối:** `15858779b049de665e6457cee4100eaf770d34e8` — commit chứa toàn bộ source, config và evidence; commit ngay sau nó chỉ ghi SHA này vào report.
- **Challenge ID:** `day13-k4-l3a-monitoring-llmops-v1` (cohort K4, incident `rag_slow`, feature `monitoring`, ngưỡng 2000 ms)
- **Tên project Langfuse cá nhân:** `day13-k4-l3a-2A202602479`

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Pytest cuối | [evidence/01-pytest.txt](evidence/01-pytest.txt) |
| Log validator | [evidence/02-log-validator.png](evidence/02-log-validator.png) |
| Dashboard validator | [evidence/03-dashboard-validator.png](evidence/03-dashboard-validator.png) |
| Structured log | [evidence/04-structured-log.png](evidence/04-structured-log.png) |
| PII redaction | [evidence/05-pii-redaction.png](evidence/05-pii-redaction.png) |
| Trace list | [evidence/06-trace-list.png](evidence/06-trace-list.png) |
| Trace waterfall | [evidence/07-trace-waterfall.png](evidence/07-trace-waterfall.png) |
| Trace metadata | [evidence/08-trace-metadata.png](evidence/08-trace-metadata.png) |
| Prompt versions | [evidence/09-prompt-versions.png](evidence/09-prompt-versions.png) |
| Prompt rollback | [evidence/10-prompt-rollback.png](evidence/10-prompt-rollback.png) |
| Dashboard runtime | [evidence/11-dashboard-overview.png](evidence/11-dashboard-overview.png) |
| Incident metric | [evidence/12-incident-metric.png](evidence/12-incident-metric.png) |
| Incident log | [evidence/13-incident-log.png](evidence/13-incident-log.png) |
| Incident trace | [evidence/14-incident-trace.png](evidence/14-incident-trace.png) |

Nguồn evidence:
- 01 là output `python -m pytest -q` do [`scripts/collect_evidence.py`](../scripts/collect_evidence.py) ghi lại.
- 02–05 và 13 là output thật của lệnh (validator; `curl` tới API :8000; `grep`/`python` trên `data/logs.jsonl`) được chạy và render thành ảnh terminal bằng `python scripts/collect_evidence.py --terminal`. Ảnh 04 thấy header `x-request-id`/`x-response-time-ms` và log JSON của `req-e04e04e0`; ảnh 05 thấy email/điện thoại/CCCD/thẻ giả bị redact và grep toàn file log = 0; ảnh 13 thấy mốc bật/tắt incident, 20 request > 2000 ms và hai dòng log của `req-bc1bf62d`.
- 06–10 và 14 là ảnh chụp giao diện Langfuse project `day13-k4-l3a-2A202602479`; `scope.attributes.public_key` trong ảnh 08 đã được che. Ảnh 14 là tab Timeline của trace `91ccac37d93222d97ef06b679aab3327`.
- 11 và 12 là ảnh chụp headless của `scripts/dashboard.py`: 11 ở trạng thái baseline (08:28 UTC), 12 ngay sau incident (09:46 UTC).

![Dashboard overview](evidence/11-dashboard-overview.png)

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 — 23 records, 20 thiếu required fields, 20 thiếu enrichment, 0 correlation ID, 0 PII leak | 100/100 — 260 records, 0 thiếu required, 0 thiếu enrichment, 121 correlation ID, 0 PII leak | Baseline FAILED required fields/correlation ID/enrichment vì `correlation_id = "MISSING"` và chưa bind context; sau CP1 PASSED cả 4 mục |
| `validate_dashboard.py` | HỢP LỆ: 6/6 panel có trong dashboard contract | HỢP LỆ: 6/6 panel | Contract đã đúng từ đầu; dashboard runtime ở `evidence/11-dashboard-overview.png` |
| `pytest` | 22 passed | 28 passed | Thêm 6 test (PII, child observations, request đồng thời không bị xếp hàng); chạy bằng `.venv/bin/python -m pytest -q` (Python 3.12) |
| Số traces hợp lệ | 10 trace `lab-agent-run` từ load test | 76 trace có đủ root + `retrieval` + `llm-generation` (98 trace trong 24h, gồm 10 trace baseline CP0) | Xác nhận qua Langfuse Observations API v2, project `day13-k4-l3a-2A202602479`; `userId` đều là hash 12 ký tự |
| Số PII leak | 0 | 0 | Baseline 0 vì starter đã scrub preview; cuối cùng scrub mọi field string, grep 4 loại PII giả trong log đều = 0 |
| Latency P95 / TTFT P95 | ~250 ms / – (load test CP0, chưa có dashboard) | 485 ms / 50 ms | Dashboard lúc 08:28 UTC, 60 phút, 89 request, không incident |
| Retrieval success rate | – (chưa có field `tool_success` trong log CP0) | 100% | Error rate 0%, quality mean 0.87, cost $0.18 |

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** `CorrelationIdMiddleware` gọi `clear_contextvars()` đầu mỗi request, lấy header `x-request-id` nếu client gửi, nếu không thì sinh `req-<8-hex>` từ `uuid4`. ID được `bind_contextvars` để mọi log trong request đều có `correlation_id`, lưu vào `request.state` để truyền cho agent/trace, và trả lại qua header `x-request-id` cùng `x-response-time-ms`.
- **Các metadata được ghi vào structured log:** `ts`, `level`, `service`, `event`, `correlation_id`; enrichment `user_id_hash` (SHA-256 cắt 12 ký tự), `session_id`, `feature`, `model`, `env` được bind trong `/chat` trước `request_received`; `response_sent` thêm `latency_ms`, `ttft_ms`, `tokens_in/out`, `cost_usd`, `quality_score`, `tool_name`, `tool_success`.
- **Cách bảo đảm PII được scrub trước khi ghi:** processor `scrub_event` đứng trước `JsonlFileProcessor` và `JSONRenderer`, scrub mọi giá trị string ở top-level và trong `payload`. `app/pii.py` có pattern cho thẻ, CCCD, email, số điện thoại VN và hộ chiếu; pattern số dài chạy trước để `phone_vn` không cắt mất một phần số thẻ/CCCD. User ID chỉ ghi dưới dạng hash.
- **Cách kiểm chứng kết quả:** đổi tên log baseline thành `data/logs.cp0-baseline.jsonl`, chạy load test mới rồi `validate_logs.py` đạt 100/100; `pytest` 26 passed (thêm test CCCD, thẻ, hộ chiếu, text thường không bị đổi); `curl` `/chat` trả `x-request-id: req-xxxxxxxx`, gửi `x-request-id: req-deadbeef` thì nhận lại đúng ID; log của câu hỏi chứa email chỉ còn `[REDACTED_EMAIL]`. Request test `req-9119e5ed` chứa email, điện thoại, CCCD và thẻ giả được ghi thành `[REDACTED_EMAIL]`, `[REDACTED_PHONE_VN]`, `[REDACTED_CCCD]`, `[REDACTED_CREDIT_CARD]` (`evidence/05-pii-redaction.png`).

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:** gọi Langfuse Public API bằng key trong `.env` của tôi: `/api/public/projects` trả đúng project `day13-k4-l3a-2A202602479`, `/api/public/v2/observations` trả các trace có `correlation_id` trùng với log local (ví dụ `req-b1a5e001`).
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

- **Dashboard và sáu panel:** `python scripts/dashboard.py` (stdlib + PyYAML) mở http://127.0.0.1:8050, đọc `data/logs.jsonl` và `config/dashboard.yaml`, time range 60 phút, auto refresh 30 s. Mỗi panel có tên, đơn vị, đường threshold nét đứt đỏ và badge OK/VƯỢT NGƯỠNG: (1) latency P50/P95/P99 + TTFT P95, (2) request/phút, (3) error rate + breakdown `error_type` + retrieval success, (4) cost theo phút + lũy kế, (5) tokens_in/tokens_out lũy kế, (6) mean quality. Ảnh `evidence/11-dashboard-overview.png` (08:28 UTC, 89 request): P50/P95/P99 151/485/568 ms, TTFT P95 50 ms, 1.48 req/phút, error 0%, retrieval 100%, cost $0.1788, tokens 3 040/11 313, quality 0.87 — cả 6 panel OK.
- **SLO và lý do chọn:** giữ SLO `fast_successful_requests`: 99.5% request trả `response_sent` trong ≤ 3000 ms, cửa sổ 28 ngày. 3000 ms gấp ~6 lần P95 baseline (~0.5 s: 545 ms khi đo CP2, 485 ms trong ảnh dashboard) nên traffic bình thường không đốt budget, còn `rag_slow` (+2.5 s) vượt ngưỡng ngay. Chi tiết trong `config/slo.yaml`.
- **Cách tính error budget:** budget = 100% − 99.5% = 0.5%, tức 50 request xấu trên 10 000 request, hoặc 0.5% × 28 ngày = 201.6 phút (≈ 3 giờ 22 phút) sự cố toàn phần. Error rate 2% (ngưỡng alert 2) đốt budget nhanh gấp 4 lần, giữ liên tục sẽ hết budget sau 7 ngày.
- **Ba alert và runbook tương ứng:** trong `config/alert_rules.yaml` và `docs/alerts.md`, cùng kênh Slack `#day13-l3a-alerts`:
  - `high_latency_p95` (P2): P95 > 3000 ms trong 5 phút → runbook `docs/alerts.md#alert-1`
  - `high_error_rate` (P1): error rate > 2% trong 5 phút → `docs/alerts.md#alert-2`
  - `cost_per_request_spike` (P3): cost trung bình > 0.004 USD/request (gấp 2 baseline 0.002) trong 15 phút → `docs/alerts.md#alert-3`

## 7. Điều tra challenge

- **Challenge ID:** `day13-k4-l3a-monitoring-llmops-v1` — chạy bằng `python scripts/inject_incident.py` và `python scripts/load_test.py --challenge --concurrency 5` (5 query feature `monitoring`, seed 1311).
- **Khoảng thời gian điều tra:** 2026-09-29 09:42:13 → 09:45:28 UTC.

  | Thời điểm (UTC) | Sự kiện | Bằng chứng |
  |---|---|---|
  | 09:42:13 | Baseline: 5 query challenge, mỗi request ~151 ms | log `response_sent` `req-170bd1c4` |
  | 09:42:19 | `incident_enabled rag_slow` | log `req-a0a0d362` |
  | 09:42:21 → 09:44:07 | 15 request challenge, tất cả 2651–2653 ms | `evidence/13-incident-log.png` |
  | 09:45:23 | Triển khai fix handler đồng bộ, incident vẫn bật | client ~3.1 s thay vì 13.3 s |
  | 09:45:27 | `incident_disabled rag_slow` | 5 request ~152 ms, hệ thống hồi phục |

- **Triệu chứng từ metrics:** panel Latency chuyển **VƯỢT NGƯỠNG**: P50 2651 ms, P95 3006 ms, P99 3008 ms (SLO dashboard ≤ 3000 ms), trong khi TTFT P95 vẫn 50 ms (`evidence/12-incident-metric.png`). Theo phút, P50 tăng từ 151 ms lên 2651 ms ở 09:43 và 09:44; 20/20 request `response_sent` từ 09:42 đến 09:46 vượt ngưỡng challenge 2000 ms (`evidence/13-incident-log.png`). Error rate 0% và retrieval success 100%: request không lỗi mà chỉ chậm, nên đây là sự cố latency, không phải availability. Phía client còn tệ hơn: request cuối của mỗi đợt 5 request chờ 13.3 s.
- **Log line và correlation ID liên quan:** `req-bc1bf62d` (session `k4-l3a-challenge-s02`, câu hỏi “How should an engineer investigate tail latency?”):

  ```json
  {"service": "api", "latency_ms": 2651, "ttft_ms": 50, "tokens_in": 34, "tokens_out": 128, "cost_usd": 0.002022, "tool_name": "retrieval", "tool_success": true, "event": "response_sent", "feature": "monitoring", "correlation_id": "req-bc1bf62d", "model": "claude-sonnet-4-5", "ts": "2026-09-29T09:44:07.021366Z"}
  ```

  Log cho thấy `latency_ms` 2651 nhưng `ttft_ms` chỉ 50, token và cost bình thường, nên thời gian không nằm ở LLM. `request_received` của request này ghi lúc 09:44:04.368, dù client gửi cả đợt lúc ~09:43:53: request đã phải chờ ~10.6 s trước khi được xử lý.
- **Trace ID và span gây ảnh hưởng:** trace `91ccac37d93222d97ef06b679aab3327` (cùng `correlation_id` `req-bc1bf62d`): root `lab-agent-run` 2652 ms, trong đó span **`retrieval` (RETRIEVER) 2500 ms ≈ 94%**, `llm-generation` 151 ms. Trace đối chứng trước incident `9539f1c02d0e5efcef3711d79c85f959` (`req-170bd1c4`): `retrieval` 0 ms, `llm-generation` 151 ms, tổng 152 ms (`evidence/14-incident-trace.png`). Ngoài ra, thời điểm bắt đầu của 5 trace trong cùng đợt cách nhau đúng ~2.65 s: request được xử lý tuần tự dù gửi song song.
- **Root cause:** bước retrieval (vector store) chậm thêm ~2.5 s mỗi request (incident `rag_slow` trong `app/mock_rag.py`), trong khi LLM không đổi. Metric (P50/P95 tăng, TTFT không đổi), log (`latency_ms` 2651, `ttft_ms` 50) và trace (`retrieval` 2500 ms) cùng chỉ về một nguyên nhân. **Yếu tố khuếch đại:** endpoint `/chat` là `async def` nhưng gọi code đồng bộ (`time.sleep` trong retrieval/LLM), nên chặn event loop; 5 request đồng thời bị xử lý nối tiếp và độ trễ phía client tăng lên tới 5 × 2.65 s = 13.3 s.
- **Fix action:**
  1. Mitigation: tắt incident (`python scripts/inject_incident.py --disable`, tương đương khôi phục vector store) lúc 09:45:27; challenge chạy lại 152 ms mỗi request, client ~165 ms.
  2. Sửa code: đổi `async def chat` thành `def chat` trong [`app/main.py`](../app/main.py) để FastAPI chạy handler trong threadpool, một retrieval chậm chỉ giữ một worker thread. Kiểm chứng lúc 09:45:23 khi incident vẫn bật: 5 request song song đều xong trong ~3.1 s thay vì 2.7 → 13.3 s. Test hồi quy `test_slow_retrieval_does_not_serialize_concurrent_requests` fail trên code cũ và pass sau khi sửa.
- **Preventive measure:**
  - Đặt timeout cho retrieval (ví dụ 800 ms, ~5× baseline) và fallback trả lời không có context khi quá hạn; ghi `tool_success=false` + `error_type=RetrievalTimeout` để panel Errors bắt được, thay vì chỉ thấy latency.
  - Thêm alert riêng cho dependency: P95 thời gian span `retrieval` > 1000 ms trong 5 phút (P2), bên cạnh alert `high_latency_p95` hiện có; ghi `retrieval_ms` vào log `response_sent` để dashboard tách được retrieval và LLM mà không cần mở trace.
  - Giữ test hồi quy concurrency và quy tắc review: không gọi I/O đồng bộ trong `async def`; nếu dùng client async thì phải `await`.

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:** không capture raw input/output vào trace mà chỉ ghi `query_preview`, `prompt_preview`, `answer_preview` đã qua `scrub_text`. Prompt compile chứa nguyên câu hỏi của người dùng, nên nếu để SDK tự capture thì trace sẽ chứa PII dù log đã sạch. Nhờ vậy vẫn debug được (thấy đầu câu hỏi, số doc, token, cost) mà không đưa PII lên dịch vụ ngoài. Quyết định thứ hai: dashboard đọc thẳng `data/logs.jsonl` và threshold từ `config/dashboard.yaml`, nên contract và hình ảnh không thể lệch nhau.
- **Một lỗi/blocker đã gặp:** (1) `python -m pytest` báo `No module named pytest` và `pip install -r requirements.txt` lỗi build `pydantic-core`. (2) Khi chạy thử promote/rollback prompt, hai trace `production` không xuất hiện trên Langfuse. (3) `GET /api/public/traces` trả `LEGACY_API_UNAVAILABLE_FOR_NEW_ORGANIZATION`. (4) Ở CP3, server ghi mỗi request 2651 ms nhưng client đo tới 13.3 s.
- **Cách tìm nguyên nhân và xử lý:** (1) `python --version` là 3.14 của hệ thống, trong khi API chạy bằng `.venv` Python 3.12; chạy test bằng `.venv/bin/python -m pytest -q` thì pass. (2) Server tạm bị kill ngay sau request nên Langfuse SDK chưa kịp flush batch span; chạy lại, chờ vài giây rồi dừng bằng SIGINT để SDK flush khi shutdown, trace xuất hiện đủ. (3) Đọc thông báo lỗi, chuyển sang `GET /api/public/v2/observations` và dựng lại cây trace từ `parentObservationId`. (4) So `request_received.ts` với thời điểm gửi và thấy start time các trace cách nhau đúng 2.65 s → request bị xếp hàng; nguyên nhân là handler `async def` gọi code blocking. Đổi sang `def` và thêm test hồi quy.
- **Cách hiểu luồng Metrics → Logs → Traces:** metrics (dashboard) trả lời *có vấn đề không, lúc nào, nặng cỡ nào* — ví dụ P95 vượt 3000 ms từ 08:30. Logs trả lời *request nào bị ảnh hưởng* — lọc `response_sent` có `latency_ms > 3000` trong khoảng đó, lấy `correlation_id`, `feature`, `model`. Traces trả lời *chậm/lỗi ở bước nào* — mở trace có cùng `correlation_id`, waterfall cho thấy `retrieval` hay `llm-generation` chiếm thời gian. `correlation_id` là khóa nối log với trace; thiếu nó thì hai nguồn không ghép được.
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:** prompt là một phần của "code" nhưng đổi được mà không deploy, nên mỗi trace phải ghi `prompt_name/version/label` để biết thay đổi hành vi đến từ đâu. Ví dụ v2 thêm một dòng hướng dẫn làm `tokens_in` tăng 36 → 47 (~30%) trên cùng input — nhân với traffic thật sẽ thành chi phí đáng kể, và alert `cost_per_request_spike` bắt được loại thay đổi này. Rollback chỉ là chuyển label `production` về v1, có hiệu lực sau cache 60 s mà không cần deploy. SLO và error budget giúp quyết định khi nào dừng thử nghiệm: nếu version mới làm tăng latency/lỗi và đốt budget nhanh thì rollback ngay.
- **Điều quan trọng nhất đã học:** observability phải được thiết kế từ đầu request: clear context, gắn `correlation_id`, scrub PII trước khi ghi, và tách span theo từng bước. Nếu thiếu một mắt xích (ví dụ trace không có child observation hoặc log không có ID) thì đến lúc incident sẽ không khoanh vùng được nguyên nhân.
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:** timeout/fallback cho retrieval và alert riêng cho span `retrieval` mới được đề xuất, chưa triển khai. Lượt chạy CP3 đầu tiên (09:42) được thực hiện trước khi tôi xác nhận kế hoạch, nên tôi dùng nó làm baseline + incident thay vì chạy lại từ đầu; thứ tự sự kiện vẫn đầy đủ trong log. Quality score chỉ là heuristic đơn giản và FakeLLM luôn trả cùng câu, nên panel quality ít biến động; SLO/alert chưa được nối vào hệ thống gửi Slack thật.

## 9. Checklist trước khi nộp

- [x] Kết quả và evidence thuộc commit SHA cuối.
- [x] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [x] Incident evidence nối đúng metric → log → trace.
- [x] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [x] Repository chạy lại được theo README.
- [x] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [ ] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
