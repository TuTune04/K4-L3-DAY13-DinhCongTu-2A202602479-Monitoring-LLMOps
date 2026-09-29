# Template Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

## Alert 1

- Tên: `high_latency_p95`
- Severity: P2
- Duration: 5m
- Kênh thông báo: Slack `#day13-l3a-alerts`
- SLI/SLO liên quan: SLO `fast_successful_requests` (99.5% request trả lời trong ≤ 3000 ms, cửa sổ 28 ngày); panel Latency.
- Điều kiện và thời gian duy trì: P95 `latency_ms` của `response_sent` trong cửa sổ 5 phút > 3000 ms, kéo dài liên tục 5 phút.
- Ảnh hưởng tới người dùng: người dùng chờ lâu bất thường; mỗi request vượt 3000 ms đốt error budget.
- Ba bước kiểm tra đầu tiên:
  1. Mở dashboard, so P95 với TTFT P95: nếu TTFT không đổi mà latency tăng thì phần chậm nằm trước hoặc sau bước sinh token đầu tiên.
  2. Lọc `data/logs.jsonl` các `response_sent` có `latency_ms > 3000`, lấy `correlation_id`.
  3. Mở trace có cùng `correlation_id` trên Langfuse, xem waterfall: span `retrieval` hay `llm-generation` chiếm phần lớn thời gian.
- Mitigation tạm thời: nếu retrieval chậm, tắt/khởi động lại vector store hoặc bật fallback không retrieval; nếu LLM chậm, chuyển sang model nhỏ hơn hoặc giảm độ dài output.
- Owner: Đinh Công Tú (on-call LLMOps)

## Alert 2

- Tên: `high_error_rate`
- Severity: P1
- Duration: 5m
- Kênh thông báo: Slack `#day13-l3a-alerts`
- SLI/SLO liên quan: SLO `fast_successful_requests` và guardrail `error_rate_pct_max: 2`; panel Errors. Error rate 2% đốt budget nhanh gấp 4 lần, giữ liên tục sẽ hết budget 28 ngày sau 7 ngày.
- Điều kiện và thời gian duy trì: `count(request_failed) / count(request_received) * 100` trong cửa sổ 5 phút > 2%, kéo dài liên tục 5 phút.
- Ảnh hưởng tới người dùng: người dùng nhận HTTP 500, không có câu trả lời.
- Ba bước kiểm tra đầu tiên:
  1. Xem breakdown `error_type` và retrieval success trên panel Errors để biết lỗi tập trung ở đâu.
  2. Lọc log `request_failed`, đọc `error_type`, `tool_name`, `payload.detail` và lấy `correlation_id`.
  3. Mở trace tương ứng, tìm observation có level ERROR (ví dụ `retrieval`) và thời điểm bắt đầu lỗi; đối chiếu với deploy/đổi prompt gần nhất.
- Mitigation tạm thời: rollback deploy hoặc label `production` của prompt nếu lỗi bắt đầu sau thay đổi; nếu dependency (vector store) lỗi, bật fallback trả lời không retrieval và báo người dùng.
- Owner: Đinh Công Tú (on-call LLMOps)

## Alert 3

- Tên: `cost_per_request_spike`
- Severity: P3
- Duration: 15m
- Kênh thông báo: Slack `#day13-l3a-alerts`
- SLI/SLO liên quan: guardrail `daily_cost_usd_max: 2.5`; panel Cost và Tokens. Baseline ≈ 0.002 USD/request.
- Điều kiện và thời gian duy trì: trung bình `cost_usd` mỗi `response_sent` trong cửa sổ 15 phút > 0.004 USD (gấp 2 baseline), kéo dài 15 phút.
- Ảnh hưởng tới người dùng: chưa gây lỗi ngay, nhưng câu trả lời dài bất thường và ngân sách ngày có thể cạn, dẫn tới phải chặn traffic.
- Ba bước kiểm tra đầu tiên:
  1. Trên panel Tokens, xem `tokens_out` hay `tokens_in` tăng để biết nguyên nhân là output dài hay prompt/context phình.
  2. Lọc log `response_sent` có `cost_usd` cao, lấy `correlation_id`, `feature` và `model`.
  3. Mở trace, xem observation `llm-generation`: usage, cost, `prompt_version`/`prompt_label` để biết có đổi prompt hoặc model gần đây không.
- Mitigation tạm thời: rollback label `production` về prompt version trước; đặt giới hạn `max_tokens` cho output; nếu cần, chuyển feature tốn kém sang model rẻ hơn.
- Owner: Đinh Công Tú (on-call LLMOps)
