from __future__ import annotations

import json
import asyncio
from pathlib import Path

import httpx

from app import logging_config
from app.main import app


def test_chat_response_log_exposes_quality_for_dashboard(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            return await client.post(
                "/chat",
                json={
                    "user_id": "student-01",
                    "session_id": "session-01",
                    "feature": "qa",
                    "message": "Explain observability",
                },
            )

    response = asyncio.run(send_request())

    assert response.status_code == 200
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    response_event = next(event for event in events if event["event"] == "response_sent")
    assert response_event["quality_score"] == response.json()["quality_score"]
    assert response_event["ttft_ms"] == response.json()["ttft_ms"]
    assert response_event["tool_name"] == "retrieval"
    assert response_event["tool_success"] is True


def test_slow_retrieval_does_not_serialize_concurrent_requests(
    monkeypatch, tmp_path: Path
) -> None:
    import time

    from app import agent as agent_module

    monkeypatch.setattr(logging_config, "LOG_PATH", tmp_path / "logs.jsonl")

    def slow_retrieve(message: str) -> list[str]:
        time.sleep(0.4)
        return ["doc"]

    monkeypatch.setattr(agent_module, "retrieve", slow_retrieve)

    async def send_requests() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await asyncio.gather(
                *(
                    client.post(
                        "/chat",
                        json={
                            "user_id": f"student-{i}",
                            "session_id": "session-01",
                            "feature": "qa",
                            "message": "Explain observability",
                        },
                    )
                    for i in range(4)
                )
            )

    started = time.perf_counter()
    responses = asyncio.run(send_requests())
    elapsed = time.perf_counter() - started

    assert all(r.status_code == 200 for r in responses)
    assert len({r.headers["x-request-id"] for r in responses}) == 4
    # Serialized handling would take >= 4 x (0.4 s retrieval + 0.15 s LLM) = 2.2 s.
    assert elapsed < 1.5
