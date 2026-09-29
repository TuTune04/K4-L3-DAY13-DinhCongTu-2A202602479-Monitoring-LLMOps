"""Thu evidence CP0–CP2 vào submission/evidence/ từ dữ liệu chạy thật.

- 01–03: output của pytest và hai validator.
- 04–05: trích từ data/logs.jsonl (structured log, PII redaction).
- 06–10: truy vấn Langfuse Public API của project cá nhân (key trong .env).
- 11: ảnh chụp dashboard (scripts/dashboard.py) bằng Playwright nếu đã cài.

Chạy:  python scripts/collect_evidence.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = REPO_ROOT / "submission" / "evidence"
LOG_PATH = REPO_ROOT / "data" / "logs.jsonl"
SAMPLE_QUERIES = REPO_ROOT / "data" / "sample_queries.jsonl"
PROMPT_NAME = "day13-chat"
PROMPT_TRACE_IDS = {
    "req-b1a5e001": "label baseline (v1)",
    "req-cad1d002": "label candidate (v2)",
    "req-a0d00002": "production sau khi promote sang v2",
    "req-a0d00001": "production sau khi rollback về v1",
}


def header(title: str, command: str | None = None) -> str:
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True
    ).stdout.strip()
    lines = [
        f"# {title}",
        f"# Thời điểm thu: {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC",
        f"# Commit HEAD khi thu: {sha} (working tree có thể chứa thay đổi chưa commit)",
    ]
    if command:
        lines.append(f"$ {command}")
    return "\n".join(lines) + "\n\n"


def run_command(filename: str, title: str, args: list[str]) -> None:
    result = subprocess.run(
        [sys.executable, *args], cwd=REPO_ROOT, capture_output=True, text=True
    )
    shown = "python " + " ".join(args)
    body = result.stdout + result.stderr + f"\n[exit code {result.returncode}]\n"
    (EVIDENCE / filename).write_text(header(title, shown) + body, encoding="utf-8")


def read_logs() -> list[dict]:
    records = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def structured_log(records: list[dict]) -> None:
    done = [r for r in records if r.get("event") == "response_sent"]
    cid = done[-1]["correlation_id"]
    lines = [r for r in records if r.get("correlation_id") == cid]
    out = header("Structured log — mọi dòng log của một request", f"grep {cid} data/logs.jsonl")
    out += "\n".join(json.dumps(r, ensure_ascii=False) for r in lines)
    out += "\n\n# Dạng dễ đọc (response_sent):\n"
    out += json.dumps(lines[-1], ensure_ascii=False, indent=2) + "\n"
    (EVIDENCE / "04-structured-log.txt").write_text(out, encoding="utf-8")


def pii_redaction(records: list[dict]) -> None:
    from app.pii import scrub_text

    out = header("PII redaction — input giả chứa PII và log thực tế sau khi scrub")
    inputs = [json.loads(line) for line in SAMPLE_QUERIES.read_text(encoding="utf-8").splitlines()]
    inputs.append(
        {
            "user_id": "u-pii-test",
            "message": "Test PII: email student@vinuni.edu.vn, phone 0987654321, "
            "CCCD 001203004567, card 4111 1111 1111 1111",
        }
    )
    received = [r for r in records if r.get("event") == "request_received"]
    for query in inputs:
        if not any(ch.isdigit() for ch in query["message"]) and "@" not in query["message"]:
            continue
        preview_start = scrub_text(query["message"])[:40]
        match = next(
            (r for r in reversed(received) if r["payload"]["message_preview"].startswith(preview_start)),
            None,
        )
        out += f"INPUT  (user_id={query['user_id']}): {query['message']}\n"
        out += f"scrub_text(): {scrub_text(query['message'])}\n"
        if match:
            out += f"LOG    ({match['correlation_id']}): {json.dumps(match, ensure_ascii=False)}\n"
        out += "\n"

    raw_values = ["student@vinuni.edu.vn", "0987654321", "001203004567", "4111 1111 1111 1111"]
    text = LOG_PATH.read_text(encoding="utf-8")
    out += "# Kiểm tra toàn bộ data/logs.jsonl còn chứa PII giả nguyên văn không:\n"
    for value in raw_values:
        out += f"grep -c '{value}' data/logs.jsonl -> {text.count(value)}\n"
    (EVIDENCE / "05-pii-redaction.txt").write_text(out, encoding="utf-8")


class Langfuse:
    def __init__(self) -> None:
        self.base = os.environ["LANGFUSE_BASE_URL"].rstrip("/")
        self.auth = (os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])

    def get(self, path: str, **params) -> dict:
        r = httpx.get(f"{self.base}{path}", params=params, auth=self.auth, timeout=30)
        r.raise_for_status()
        return r.json()

    def project_name(self) -> str:
        return self.get("/api/public/projects")["data"][0]["name"]

    def observations(self, hours: int = 24) -> list[dict]:
        now = datetime.now(timezone.utc)
        return self.get(
            "/api/public/v2/observations",
            fromStartTime=(now - timedelta(hours=hours)).isoformat(),
            toStartTime=now.isoformat(),
            limit=1000,
            fields="core,basic,usage,prompt,metadata,model",
        )["data"]


def clean_metadata(meta: dict | None) -> dict:
    return {
        k: v
        for k, v in (meta or {}).items()
        if not k.startswith(("scope.", "resourceAttributes.")) and "public_key" not in k
    }


def waterfall(tree: list[dict], width: int = 50) -> str:
    root = next(o for o in tree if o.get("parentObservationId") is None)
    t0 = datetime.fromisoformat(root["startTime"].replace("Z", "+00:00"))
    total_ms = float(root.get("latency") or 0) * 1000 or 1

    def offset(o, key):
        return (datetime.fromisoformat(o[key].replace("Z", "+00:00")) - t0).total_seconds() * 1000

    out = f"traceId: {root['traceId']}\ncorrelation_id: {(root.get('metadata') or {}).get('correlation_id')}\n\n"
    for o in sorted(tree, key=lambda o: (o.get("parentObservationId") is not None, o["startTime"])):
        start, end = offset(o, "startTime"), offset(o, "endTime")
        indent = "" if o.get("parentObservationId") is None else "  └─ "
        a = int(start / total_ms * width)
        b = max(a + 1, int(end / total_ms * width))
        bar = " " * a + "█" * (b - a)
        out += (
            f"{indent + o['name']:<22}{o['type']:<11}{end - start:7.0f} ms |{bar:<{width}}| "
            f"id={o['id']} parent={o.get('parentObservationId')}\n"
        )
    return out


def langfuse_evidence() -> None:
    lf = Langfuse()
    project = lf.project_name()
    obs = lf.observations()
    by_trace: dict[str, list[dict]] = {}
    for o in obs:
        by_trace.setdefault(o["traceId"], []).append(o)
    roots = sorted(
        (o for o in obs if o.get("parentObservationId") is None), key=lambda o: o["startTime"]
    )

    # 06 — trace list
    out = header(f"Trace list — Langfuse project `{project}`", "GET /api/public/v2/observations (24h)")
    full = [r for r in roots if len(by_trace[r["traceId"]]) >= 3]
    out += f"Project: {project}\nSố trace (24h): {len(roots)}\n"
    out += f"Số trace có đủ root + retrieval + llm-generation (sau CP2): {len(full)}\n"
    out += "Các trace không có children/correlation_id là baseline CP0, trước khi instrument.\n\n"
    out += f"{'startTime (UTC)':<26}{'traceId':<34}{'correlation_id':<16}{'userId (hash)':<15}children\n"
    for r in roots:
        children = sorted(o["name"] for o in by_trace[r["traceId"]] if o is not r)
        out += (
            f"{r['startTime']:<26}{r['traceId']:<34}"
            f"{str((r.get('metadata') or {}).get('correlation_id', '')):<16}"
            f"{str(r.get('userId')):<15}{', '.join(children)}\n"
        )
    (EVIDENCE / "06-trace-list.txt").write_text(out, encoding="utf-8")

    # 07 — waterfall + 08 — metadata of the latest complete trace
    complete = [r for r in roots if len(by_trace[r["traceId"]]) >= 3]
    root = complete[-1]
    tree = sorted(by_trace[root["traceId"]], key=lambda o: o["startTime"])
    out = header(f"Trace waterfall — project `{project}`", f"trace {root['traceId']}")
    out += waterfall(tree)
    (EVIDENCE / "07-trace-waterfall.txt").write_text(out, encoding="utf-8")

    out = header(f"Trace metadata — project `{project}`", f"trace {root['traceId']}")
    for o in tree:
        view = {
            "name": o["name"],
            "type": o["type"],
            "userId": o.get("userId"),
            "sessionId": o.get("sessionId"),
            "environment": o.get("environment"),
            "model": o.get("model"),
            "promptName": o.get("promptName"),
            "promptVersion": o.get("promptVersion"),
            "usageDetails": o.get("usageDetails"),
            "costDetails": o.get("costDetails"),
            "metadata": clean_metadata(o.get("metadata")),
        }
        out += json.dumps({k: v for k, v in view.items() if v not in (None, {}, "")}, ensure_ascii=False, indent=2)
        out += "\n\n"
    (EVIDENCE / "08-trace-metadata.txt").write_text(out, encoding="utf-8")

    # 09 — prompt versions
    out = header(f"Prompt versions — project `{project}`", f"GET /api/public/v2/prompts/{PROMPT_NAME}?version=N")
    for version in (1, 2):
        p = lf.get(f"/api/public/v2/prompts/{PROMPT_NAME}", version=version)
        out += f"--- {PROMPT_NAME} v{p['version']}  labels={p['labels']}  commit={p.get('commitMessage')!r}\n"
        out += p["prompt"] + "\n\n"
    (EVIDENCE / "09-prompt-versions.txt").write_text(out, encoding="utf-8")

    # 10 — promote / rollback proven by traces
    out = header(f"Prompt promote/rollback — project `{project}`")
    out += (
        "Các bước đã chạy (langfuse.update_prompt):\n"
        "  1. Trước:    v1 ['baseline','production']  v2 ['candidate','latest']\n"
        "  2. Promote:  update_prompt(version=2, new_labels=['candidate','production'])\n"
        "               -> v1 ['baseline']  v2 ['candidate','production','latest']\n"
        "  3. Rollback: update_prompt(version=1, new_labels=['baseline','production'])\n"
        "               -> v1 ['baseline','production']  v2 ['candidate','latest']\n\n"
        "Trace chứng minh (cùng input 'Explain the monitoring policy'):\n"
    )
    for r in roots:
        meta = r.get("metadata") or {}
        cid = meta.get("correlation_id")
        if cid in PROMPT_TRACE_IDS:
            out += (
                f"  {r['startTime']}  {r['traceId']}  {cid:<14} "
                f"label={meta.get('prompt_label'):<10} version={meta.get('prompt_version')}  "
                f"<- {PROMPT_TRACE_IDS[cid]}\n"
            )
    out += "\nTrạng thái label hiện tại:\n"
    for version in (1, 2):
        p = lf.get(f"/api/public/v2/prompts/{PROMPT_NAME}", version=version)
        out += f"  v{version} {p['labels']}\n"
    (EVIDENCE / "10-prompt-rollback.txt").write_text(out, encoding="utf-8")


def dashboard_screenshot() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Bỏ qua 11-dashboard-overview.png: chưa cài playwright")
        return
    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "dashboard.html"
        subprocess.run(
            [sys.executable, "scripts/dashboard.py", "--once", str(html_path)], cwd=REPO_ROOT, check=True
        )
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1400, "height": 900}, device_scale_factor=1.5)
            page.goto(html_path.as_uri())
            page.screenshot(path=str(EVIDENCE / "11-dashboard-overview.png"), full_page=True)
            browser.close()


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def incident_evidence(args) -> None:
    """12–14: metric → log → trace cho một khoảng sự cố và một correlation_id."""
    start, end = parse_ts(args.start), parse_ts(args.end)
    threshold = args.threshold_ms
    records = [r for r in read_logs() if start <= parse_ts(r["ts"]) <= end]

    # 12 — metric theo từng phút + các mốc bật/tắt incident
    out = header(
        f"Incident metric — {args.challenge_id}",
        f"data/logs.jsonl, {args.start} → {args.end}, ngưỡng {threshold} ms",
    )
    out += "Mốc điều khiển incident trong log:\n"
    for r in records:
        if r.get("event", "").startswith("incident_"):
            out += f"  {r['ts']}  {r['event']}  {r['payload']}\n"
    out += f"\n{'phút (UTC)':<12}{'requests':>9}{'P50 ms':>9}{'P95 ms':>9}{'max ms':>9}{'> ngưỡng':>10}{'error %':>9}\n"
    buckets: dict[str, list[dict]] = {}
    for r in records:
        buckets.setdefault(r["ts"][11:16], []).append(r)
    for minute, recs in sorted(buckets.items()):
        lat = sorted(r["latency_ms"] for r in recs if r.get("event") == "response_sent")
        received = sum(r.get("event") == "request_received" for r in recs)
        failed = sum(r.get("event") == "request_failed" for r in recs)
        if not received:
            continue
        pct = lambda q: lat[max(0, -(-q * len(lat) // 100) - 1)] if lat else 0  # noqa: E731
        out += (
            f"{minute:<12}{received:>9}{pct(50):>9}{pct(95):>9}{(lat[-1] if lat else 0):>9}"
            f"{sum(v > threshold for v in lat):>10}{failed / received * 100:>9.1f}\n"
        )
    (EVIDENCE / "12-incident-metric.txt").write_text(out, encoding="utf-8")

    # 13 — log line của các request vượt ngưỡng, nhấn mạnh correlation_id được chọn
    slow = [r for r in records if r.get("event") == "response_sent" and r["latency_ms"] > threshold]
    out = header(
        f"Incident log — {args.challenge_id}",
        f"response_sent có latency_ms > {threshold} trong {args.start} → {args.end}",
    )
    out += f"{len(slow)} request vượt ngưỡng:\n"
    for r in slow:
        out += f"  {r['ts']}  {r['correlation_id']}  feature={r.get('feature')}  latency_ms={r['latency_ms']}  ttft_ms={r.get('ttft_ms')}\n"
    out += f"\n# Mọi dòng log của request được chọn: grep {args.cid} data/logs.jsonl\n"
    for r in read_logs():
        if r.get("correlation_id") == args.cid:
            out += json.dumps(r, ensure_ascii=False) + "\n"
    if args.baseline_cid:
        out += f"\n# Đối chứng trước incident: grep {args.baseline_cid} data/logs.jsonl (response_sent)\n"
        for r in read_logs():
            if r.get("correlation_id") == args.baseline_cid and r.get("event") == "response_sent":
                out += json.dumps(r, ensure_ascii=False) + "\n"
    (EVIDENCE / "13-incident-log.txt").write_text(out, encoding="utf-8")

    # 14 — trace cùng correlation_id, so với trace baseline
    lf = Langfuse()
    project = lf.project_name()
    now = datetime.now(timezone.utc)
    obs = lf.get(
        "/api/public/v2/observations",
        fromStartTime=(start - timedelta(minutes=5)).isoformat(),
        toStartTime=now.isoformat(),
        limit=1000,
        fields="core,basic,metadata",
    )["data"]
    by_trace: dict[str, list[dict]] = {}
    for o in obs:
        by_trace.setdefault(o["traceId"], []).append(o)

    def trace_for(cid: str) -> list[dict]:
        for tree in by_trace.values():
            if any((o.get("metadata") or {}).get("correlation_id") == cid and o.get("parentObservationId") is None for o in tree):
                return tree
        raise SystemExit(f"Không tìm thấy trace cho {cid}")

    out = header(f"Incident trace — {args.challenge_id}, project `{project}`", f"trace có correlation_id = {args.cid}")
    out += "## Trace trong incident\n" + waterfall(trace_for(args.cid))
    if args.baseline_cid:
        out += "\n## Trace đối chứng trước incident\n" + waterfall(trace_for(args.baseline_cid))
    (EVIDENCE / "14-incident-trace.txt").write_text(out, encoding="utf-8")


def incident_dashboard_screenshot() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Bỏ qua 12-incident-metric.png: chưa cài playwright")
        return
    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "dashboard.html"
        subprocess.run(
            [sys.executable, "scripts/dashboard.py", "--once", str(html_path)], cwd=REPO_ROOT, check=True
        )
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1400, "height": 900}, device_scale_factor=1.5)
            page.goto(html_path.as_uri())
            page.screenshot(path=str(EVIDENCE / "12-incident-metric.png"), full_page=True)
            browser.close()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Thu evidence vào submission/evidence/")
    parser.add_argument("--incident", action="store_true", help="Chỉ thu evidence 12–14 của incident")
    parser.add_argument("--challenge-id", default="")
    parser.add_argument("--start", help="Đầu khoảng incident (ISO, UTC)")
    parser.add_argument("--end", help="Cuối khoảng incident (ISO, UTC)")
    parser.add_argument("--cid", help="correlation_id của request bất thường")
    parser.add_argument("--baseline-cid", help="correlation_id đối chứng trước incident")
    parser.add_argument("--threshold-ms", type=int, default=2000)
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    sys.path.insert(0, str(REPO_ROOT))
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    if args.incident:
        incident_evidence(args)
        incident_dashboard_screenshot()
        return 0
    run_command("01-pytest.txt", "Pytest", ["-m", "pytest", "-q"])
    run_command("02-log-validator.txt", "Log validator", ["scripts/validate_logs.py"])
    run_command("03-dashboard-validator.txt", "Dashboard validator", ["scripts/validate_dashboard.py"])
    records = read_logs()
    structured_log(records)
    pii_redaction(records)
    langfuse_evidence()
    dashboard_screenshot()
    for path in sorted(EVIDENCE.iterdir()):
        print(path.relative_to(REPO_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
