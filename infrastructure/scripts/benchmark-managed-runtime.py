#!/usr/bin/env python3
"""Compare two llama-server executables with Knemora's production arguments."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import statistics
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SHORT_PROMPT = "Reply with one concise sentence explaining why source citations matter."
LONG_PROMPT = (
    " ".join(
        [
            "Knemora keeps local knowledge traceable to immutable source records and explicit citations."
        ]
        * 48
    )
    + " Summarize the design in six concise bullet points."
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--port", type=int, default=18080)
    return parser.parse_args()


def _wait_ready(port: int, process: subprocess.Popen[str]) -> float:
    started = time.monotonic()
    deadline = started + 600
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"llama-server exited during model load with {process.returncode}"
            )
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=2
            ) as response:
                if response.status == 200:
                    return time.monotonic() - started
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
    raise RuntimeError("llama-server did not become ready within 600 seconds")


def _request(port: int, prompt: str, max_tokens: int) -> dict[str, Any]:
    body = json.dumps(
        {
            "model": "local",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "seed": 4242,
            "max_tokens": max_tokens,
            "stream": True,
            "chat_template_kwargs": {"enable_thinking": False},
        }
    ).encode()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=300)
    started = time.monotonic()
    connection.request(
        "POST",
        "/v1/chat/completions",
        body=body,
        headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
    )
    response = connection.getresponse()
    if response.status != 200:
        raise RuntimeError(
            f"completion failed with HTTP {response.status}: {response.read()!r}"
        )
    first_token: float | None = None
    completion = ""
    timings: dict[str, Any] = {}
    while line := response.readline():
        text = line.decode("utf-8").strip()
        if not text.startswith("data: ") or text == "data: [DONE]":
            continue
        event = json.loads(text[6:])
        if isinstance(event.get("timings"), dict):
            timings = event["timings"]
        choices = event.get("choices", [])
        if not choices:
            continue
        content = choices[0].get("delta", {}).get("content", "")
        if content:
            if first_token is None:
                first_token = time.monotonic() - started
            completion += content
    total = time.monotonic() - started
    connection.close()
    if first_token is None or not completion:
        raise RuntimeError("stream produced no visible completion tokens")
    return {
        "ttft_seconds": first_token,
        "total_seconds": total,
        "characters": len(completion),
        "timings": timings,
    }


def _rss_mb(pid: int) -> float | None:
    result = subprocess.run(
        ["/bin/ps", "-o", "rss=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return int(result.stdout.strip()) / 1024
    except ValueError:
        return None


def _median(samples: list[dict[str, Any]], key: str) -> float:
    return statistics.median(float(sample[key]) for sample in samples)


def _server_command(executable: Path, model: Path, port: int) -> list[str]:
    return [
        str(executable),
        "--model",
        str(model),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--ctx-size",
        "8192",
        "--parallel",
        "1",
        "--threads",
        "6",
        "--n-gpu-layers",
        "99",
        "--batch-size",
        "128",
        "--ubatch-size",
        "64",
        "--cache-type-k",
        "q8_0",
        "--cache-type-v",
        "q8_0",
        "--load-mode",
        "mmap",
        "--no-reasoning-preserve",
        "--metrics",
    ]


def _stop(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _startup_samples(
    executable: Path, model: Path, port: int, repetitions: int
) -> list[float]:
    samples: list[float] = []
    for _ in range(repetitions):
        with tempfile.TemporaryFile(mode="w+") as log:
            process = subprocess.Popen(
                _server_command(executable, model, port),
                cwd=executable.parent,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                samples.append(_wait_ready(port, process))
            finally:
                _stop(process)
    return samples


def _run_runtime(
    label: str,
    executable: Path,
    model: Path,
    port: int,
    repetitions: int,
) -> dict[str, Any]:
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError(f"{label} executable is not runnable: {executable}")
    startup_samples = _startup_samples(executable, model, port, repetitions)
    with tempfile.NamedTemporaryFile(
        mode="w+", prefix=f"knemora-{label}-", suffix=".log", delete=False
    ) as log:
        log_path = Path(log.name)
        process = subprocess.Popen(
            _server_command(executable, model, port),
            cwd=executable.parent,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            ready = _wait_ready(port, process)
            _request(port, SHORT_PROMPT, 32)
            short = [_request(port, SHORT_PROMPT, 32) for _ in range(repetitions)]
            long = [_request(port, LONG_PROMPT, 128) for _ in range(repetitions)]
            rss_mb = _rss_mb(process.pid)
        finally:
            _stop(process)
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    evidence = [
        line
        for line in log_text.splitlines()
        if "metal" in line.casefold() or "offload" in line.casefold()
    ]
    return {
        "label": label,
        "executable": str(executable.resolve()),
        "startup_to_ready_seconds": ready,
        "prepared_startup_samples_seconds": startup_samples,
        "rss_mb_after_workloads": rss_mb,
        "short": short,
        "long": long,
        "summary": {
            "short_median_ttft_seconds": _median(short, "ttft_seconds"),
            "short_median_total_seconds": _median(short, "total_seconds"),
            "long_median_ttft_seconds": _median(long, "ttft_seconds"),
            "long_median_total_seconds": _median(long, "total_seconds"),
            "prepared_startup_median_seconds": statistics.median(startup_samples),
        },
        "metal_evidence": evidence[-30:],
        "log": str(log_path),
    }


def main() -> None:
    args = _arguments()
    if args.repetitions < 5:
        raise SystemExit("At least five measured repetitions are required.")
    if not args.model.is_file():
        raise SystemExit(f"Model not found: {args.model}")
    result = {
        "formatVersion": 1,
        "model": str(args.model.resolve()),
        "modelSize": args.model.stat().st_size,
        "arguments": {
            "ctxSize": 8192,
            "parallel": 1,
            "threads": 6,
            "gpuLayers": 99,
            "batchSize": 128,
            "ubatchSize": 64,
            "cacheTypeK": "q8_0",
            "cacheTypeV": "q8_0",
            "loadMode": "mmap",
            "reasoningPreserved": False,
        },
        "repetitions": args.repetitions,
        "runtimes": [
            _run_runtime(
                "baseline", args.baseline, args.model, args.port, args.repetitions
            ),
            _run_runtime(
                "managed", args.candidate, args.model, args.port + 1, args.repetitions
            ),
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
