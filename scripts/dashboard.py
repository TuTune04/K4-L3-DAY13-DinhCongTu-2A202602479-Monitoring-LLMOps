"""Dashboard 6 panel đọc trực tiếp từ data/logs.jsonl theo contract config/dashboard.yaml.

Chạy:  python scripts/dashboard.py            -> http://127.0.0.1:8050
       python scripts/dashboard.py --once out.html  -> ghi một file HTML tĩnh
"""
from __future__ import annotations

import argparse
import html
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "config" / "dashboard.yaml"
LOG_PATH = REPO_ROOT / "data" / "logs.jsonl"

SERIES_COLORS = ["#2563eb", "#d97706", "#7c3aed", "#059669"]
THRESHOLD_COLOR = "#dc2626"


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(pct / 100 * len(ordered)) - 1)
    return ordered[rank]


def load_records(window_minutes: int, now: datetime) -> list[dict]:
    if not LOG_PATH.exists():
        return []
    start = now - timedelta(minutes=window_minutes)
    records = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
            ts = datetime.fromisoformat(rec["ts"].replace("Z", "+00:00"))
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
        if start <= ts <= now:
            rec["_minute"] = ts.replace(second=0, microsecond=0)
            records.append(rec)
    return records


def minute_axis(window_minutes: int, now: datetime) -> list[datetime]:
    end = now.replace(second=0, microsecond=0)
    return [end - timedelta(minutes=i) for i in range(window_minutes - 1, -1, -1)]


def compute(records: list[dict], minutes: list[datetime]) -> dict:
    by_min: dict[datetime, list[dict]] = defaultdict(list)
    for rec in records:
        by_min[rec["_minute"]].append(rec)

    def per_minute(fn):
        return [fn(by_min.get(m, [])) for m in minutes]

    def events(recs, name):
        return [r for r in recs if r.get("event") == name]

    def field(recs, name, key):
        return [r[key] for r in events(recs, name) if isinstance(r.get(key), (int, float))]

    def error_rate(recs):
        received = len(events(recs, "request_received"))
        return None if received == 0 else len(events(recs, "request_failed")) / received * 100

    def summed(key):
        def fn(recs):
            vals = field(recs, "response_sent", key)
            return sum(vals) if vals else None
        return fn

    def cumulative(series):
        total, out = 0.0, []
        for v in series:
            total += v or 0
            out.append(total)
        return out

    def mean(vals):
        return sum(vals) / len(vals) if vals else None

    tool_flags = [r["tool_success"] for r in records if isinstance(r.get("tool_success"), bool)]
    cost_per_min = per_minute(summed("cost_usd"))
    tokens_in_per_min = per_minute(summed("tokens_in"))
    tokens_out_per_min = per_minute(summed("tokens_out"))

    return {
        "latency": {
            "series": {
                "latency P50": per_minute(lambda r: percentile(field(r, "response_sent", "latency_ms"), 50)),
                "latency P95": per_minute(lambda r: percentile(field(r, "response_sent", "latency_ms"), 95)),
                "latency P99": per_minute(lambda r: percentile(field(r, "response_sent", "latency_ms"), 99)),
                "TTFT P95": per_minute(lambda r: percentile(field(r, "response_sent", "ttft_ms"), 95)),
            },
            "stats": {
                "p50": percentile(field(records, "response_sent", "latency_ms"), 50),
                "p95": percentile(field(records, "response_sent", "latency_ms"), 95),
                "p99": percentile(field(records, "response_sent", "latency_ms"), 99),
                "ttft_p95": percentile(field(records, "response_sent", "ttft_ms"), 95),
            },
        },
        "traffic": {
            "series": {"requests/min": per_minute(lambda r: len(events(r, "request_received")))},
            "stats": {
                "count": len(events(records, "request_received")),
                "rate_per_minute": len(events(records, "request_received")) / len(minutes),
            },
        },
        "errors": {
            "series": {"error rate %": per_minute(error_rate)},
            "stats": {
                "error_rate_pct": error_rate(records),
                "tool_success_rate_pct": (
                    sum(tool_flags) / len(tool_flags) * 100 if tool_flags else None
                ),
            },
            "breakdown": Counter(
                r.get("error_type") or "unknown" for r in events(records, "request_failed")
            ),
        },
        "cost": {
            "series": {
                "cost/min": cost_per_min,
                "cumulative cost": cumulative(cost_per_min),
            },
            "threshold_series": "cumulative cost",
            "stats": {"total": sum(v or 0 for v in cost_per_min)},
        },
        "tokens": {
            "series": {
                "cumulative tokens_in": cumulative(tokens_in_per_min),
                "cumulative tokens_out": cumulative(tokens_out_per_min),
            },
            "stats": {
                "tokens_in": sum(v or 0 for v in tokens_in_per_min),
                "tokens_out": sum(v or 0 for v in tokens_out_per_min),
            },
        },
        "quality": {
            "series": {"mean quality": per_minute(lambda r: mean(field(r, "response_sent", "quality_score")))},
            "stats": {"mean": mean(field(records, "response_sent", "quality_score"))},
        },
    }


def fmt(value: float | None, unit: str = "") -> str:
    if value is None:
        return "–"
    if unit == "usd":
        return f"${value:.4f}"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:,.2f}"
    return f"{value:,.0f}"


def breaches(value: float | None, threshold: dict) -> bool:
    if value is None:
        return False
    return value > threshold["value"] if threshold["operator"] == "lte" else value < threshold["value"]


def svg_chart(series: dict[str, list], minutes: list[datetime], threshold: float, unit: str) -> str:
    width, height, pad_l, pad_r, pad_t, pad_b = 560, 200, 56, 12, 12, 28
    values = [v for vals in series.values() for v in vals if v is not None]
    y_max = max(values + [threshold]) * 1.15 or 1
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    n = len(minutes)

    def x(i):
        return pad_l + (i / max(1, n - 1)) * plot_w

    def y(v):
        return pad_t + plot_h - (v / y_max) * plot_h

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" preserveAspectRatio="none">']
    for frac in (0, 0.5, 1):
        gy = pad_t + plot_h * (1 - frac)
        parts.append(f'<line x1="{pad_l}" x2="{width - pad_r}" y1="{gy}" y2="{gy}" class="grid"/>')
        parts.append(f'<text x="{pad_l - 6}" y="{gy + 4}" text-anchor="end" class="axis">{fmt(y_max * frac)}</text>')
    for i in (0, n // 2, n - 1):
        parts.append(
            f'<text x="{x(i)}" y="{height - 8}" text-anchor="middle" class="axis">'
            f'{minutes[i].strftime("%H:%M")}</text>'
        )
    ty = y(threshold)
    parts.append(
        f'<line x1="{pad_l}" x2="{width - pad_r}" y1="{ty}" y2="{ty}" stroke="{THRESHOLD_COLOR}" '
        f'stroke-dasharray="6 4" stroke-width="1.5"/>'
    )
    parts.append(
        f'<text x="{width - pad_r}" y="{ty - 4}" text-anchor="end" class="axis" fill="{THRESHOLD_COLOR}">'
        f'threshold {fmt(threshold, unit)}</text>'
    )
    for color, (name, vals) in zip(SERIES_COLORS, series.items()):
        path, pen_up = [], True
        for i, v in enumerate(vals):
            if v is None:
                pen_up = True
                continue
            path.append(f'{"M" if pen_up else "L"}{x(i):.1f},{y(v):.1f}')
            pen_up = False
        if path:
            parts.append(f'<path d="{" ".join(path)}" fill="none" stroke="{color}" stroke-width="2"/>')
        for i, v in enumerate(vals):
            if v is not None:
                parts.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="2.5" fill="{color}"/>')
    parts.append("</svg>")
    return "".join(parts)


def render(config: dict, now: datetime) -> str:
    dash = config["dashboard"]
    window = dash["time_range_minutes"]
    minutes = minute_axis(window, now)
    records = load_records(window, now)
    data = compute(records, minutes)

    cards = []
    for panel in dash["panels"]:
        pid, unit, threshold = panel["id"], panel["unit"], panel["threshold"]
        pdata = data[pid]
        stats = pdata["stats"]
        stat_key = threshold["aggregation"]
        checked = (
            max(stats["tokens_in"], stats["tokens_out"]) if stat_key == "sum_by_field" else stats.get(stat_key)
        )
        status = "breach" if breaches(checked, threshold) else "ok"
        op = "≤" if threshold["operator"] == "lte" else "≥"
        stat_html = "".join(
            f'<div class="stat"><span>{html.escape(k)}</span><b>{fmt(v, unit)}</b></div>'
            for k, v in stats.items()
        )
        legend = "".join(
            f'<span class="key"><i style="background:{c}"></i>{html.escape(name)}</span>'
            for c, name in zip(SERIES_COLORS, pdata["series"])
        )
        extra = ""
        if pid == "errors":
            rows = "".join(
                f"<li>{html.escape(k)}: {v}</li>" for k, v in pdata["breakdown"].most_common()
            ) or "<li>Không có request_failed</li>"
            extra = f'<div class="breakdown"><b>Breakdown error_type</b><ul>{rows}</ul></div>'
        cards.append(
            f'<section class="panel {status}">'
            f'<header><h2>{html.escape(panel["title"])}</h2>'
            f'<span class="badge">{"VƯỢT NGƯỠNG" if status == "breach" else "OK"}</span></header>'
            f'<p class="meta">Đơn vị: <b>{html.escape(unit)}</b> · Time range: {window} phút · '
            f'Threshold: {html.escape(stat_key)} {op} {fmt(threshold["value"], unit)}</p>'
            f'<div class="stats">{stat_html}</div>'
            f'<div class="legend">{legend}<span class="key"><i class="dash"></i>threshold/SLO</span></div>'
            f'{svg_chart(pdata["series"], minutes, threshold["value"], unit)}'
            f"{extra}</section>"
        )

    refresh = dash["refresh_seconds"]
    return f"""<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="{refresh}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(dash["title"])}</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;padding:20px;background:#f8fafc;color:#0f172a}}
h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#475569;margin:0 0 16px}}
.grid-wrap{{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:16px}}
.panel{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:14px}}
.panel.breach{{border-color:{THRESHOLD_COLOR}}}
.panel header{{display:flex;justify-content:space-between;align-items:center}}
h2{{font-size:15px;margin:0}} .meta{{font-size:12px;color:#475569;margin:6px 0}}
.badge{{font-size:11px;padding:2px 8px;border-radius:99px;background:#dcfce7;color:#166534}}
.breach .badge{{background:#fee2e2;color:#991b1b}}
.stats{{display:flex;flex-wrap:wrap;gap:14px;margin:8px 0}}
.stat span{{display:block;font-size:11px;color:#64748b}} .stat b{{font-size:17px}}
.legend{{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;color:#334155}}
.key i{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px}}
.key i.dash{{height:0;border-top:2px dashed {THRESHOLD_COLOR};border-radius:0}}
svg{{width:100%;height:200px;margin-top:6px}} .grid{{stroke:#e2e8f0}}
.axis{{font-size:10px;fill:#64748b}} .breakdown{{font-size:12px}} .breakdown ul{{margin:4px 0}}
</style></head><body>
<h1>{html.escape(dash["title"])}</h1>
<p class="sub">Nguồn: data/logs.jsonl · {len(records)} log records trong {window} phút gần nhất ·
cập nhật {now.strftime("%Y-%m-%d %H:%M:%S")} UTC · auto refresh {refresh}s</p>
<div class="grid-wrap">{"".join(cards)}</div></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Dashboard 6 panel cho Day 13")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--once", type=Path, help="Ghi HTML ra file rồi thoát")
    args = parser.parse_args()
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

    if args.once:
        args.once.write_text(render(config, datetime.now(timezone.utc)), encoding="utf-8")
        print(f"Đã ghi {args.once}")
        return 0

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = render(config, datetime.now(timezone.utc)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            return None

    print(f"Dashboard: http://127.0.0.1:{args.port}  (Ctrl+C để dừng)")
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
