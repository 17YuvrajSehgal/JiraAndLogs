"""Concurrent, restart-safe batch client for the vLLM endpoint.

Reads a prompts JSONL where each row carries its own `messages`,
`max_tokens` and JSON `schema`; writes one response row per prompt,
appending as results land. Re-running skips ids already present, so a
killed SLURM job resumes exactly where it stopped.

Stdlib only (compute nodes have no pip and no internet).

Each output row:
  id, parsed (schema-validated object or null), raw content, reasoning
  length, usage, finish_reason, latency_s, attempts, error

Usage (on the cluster):
    python llm_run.py --prompts prompts-a1.jsonl --out resp-a1.jsonl \
        --endpoint http://trig0051:8000/v1 --model qwen3.8-27b \
        --workers 24 --thinking on
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

JSON_RE = re.compile(r"\{.*\}", re.S)
_lock = threading.Lock()
_done_count = 0


def extract(content: str):
    """Parse the model's JSON answer, tolerating prose or fences around it."""
    if not content:
        return None
    try:
        return json.loads(content)
    except Exception:  # noqa: BLE001
        pass
    stripped = re.sub(r"^```(?:json)?|```$", "", content.strip(),
                      flags=re.M).strip()
    try:
        return json.loads(stripped)
    except Exception:  # noqa: BLE001
        pass
    m = JSON_RE.search(stripped)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:  # noqa: BLE001
            return None
    return None


def call_one(row: dict, args) -> dict:
    body = {"model": args.model, "messages": row["messages"],
            "max_tokens": row.get("max_tokens", 2000), "temperature": 0,
            "seed": args.seed}
    if args.thinking == "off":
        body["chat_template_kwargs"] = {"enable_thinking": False}
    if args.schema and row.get("schema"):
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "answer", "schema": row["schema"]}}
    data = json.dumps(body).encode()
    t0 = time.time()
    last = ""
    for attempt in range(1, args.retries + 1):
        try:
            req = urllib.request.Request(
                f"{args.endpoint}/chat/completions", data=data,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=args.timeout) as r:
                resp = json.load(r)
            ch = resp["choices"][0]
            msg = ch.get("message", {})
            content = msg.get("content") or ""
            return {"id": row["id"], "stage": row.get("stage"),
                    "project": row.get("project"),
                    "issue_key": row.get("issue_key"),
                    "variant": row.get("variant"),
                    "parsed": extract(content), "content": content[:4000],
                    "reasoning_chars": len(msg.get("reasoning") or ""),
                    "finish_reason": ch.get("finish_reason"),
                    "usage": resp.get("usage"),
                    "latency_s": round(time.time() - t0, 2),
                    "attempts": attempt, "error": None}
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            if isinstance(e, urllib.error.HTTPError):
                try:
                    last += " | " + e.read().decode()[:300]
                except Exception:  # noqa: BLE001
                    pass
                if e.code == 400:  # malformed/too long: do not retry
                    break
            if attempt < args.retries:
                time.sleep(min(60, 5 * attempt))
    return {"id": row["id"], "stage": row.get("stage"),
            "project": row.get("project"), "issue_key": row.get("issue_key"),
            "variant": row.get("variant"), "parsed": None, "content": "",
            "reasoning_chars": 0, "finish_reason": None, "usage": None,
            "latency_s": round(time.time() - t0, 2),
            "attempts": args.retries, "error": last}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prompts", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--endpoint", default="http://localhost:8000/v1")
    ap.add_argument("--model", required=True)
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--retries", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--thinking", choices=["on", "off"], default="on")
    ap.add_argument("--schema", type=int, default=1,
                    help="1 = constrain output with the row's JSON schema")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--deadline-min", type=int, default=0,
                    help="stop launching new calls after N minutes")
    args = ap.parse_args()

    done = set()
    try:
        with open(args.out, encoding="utf-8") as fh:
            for line in fh:
                try:
                    done.add(json.loads(line)["id"])
                except Exception:  # noqa: BLE001
                    pass
    except FileNotFoundError:
        pass
    todo = []
    with open(args.prompts, encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row["id"] not in done:
                todo.append(row)
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(done)} done, {len(todo)} to go, {args.workers} workers, "
          f"thinking={args.thinking} schema={args.schema}", flush=True)

    out = open(args.out, "a", encoding="utf-8")
    t0 = time.time()
    tok = {"in": 0, "out": 0}
    stop = threading.Event()

    def work(row):
        global _done_count
        if stop.is_set():
            return
        res = call_one(row, args)
        with _lock:
            out.write(json.dumps(res, ensure_ascii=False) + "\n")
            out.flush()  # restart-safety: a killed job must lose nothing
            _done_count += 1
            n = _done_count
            u = res.get("usage") or {}
            tok["in"] += u.get("prompt_tokens", 0) or 0
            tok["out"] += u.get("completion_tokens", 0) or 0
            if n % 25 == 0 or n == len(todo):
                out.flush()
                el = time.time() - t0
                rate = n / el
                print(f"  {n}/{len(todo)}  {el / 60:.1f}min  "
                      f"{rate * 60:.1f}/min  in={tok['in'] / 1e6:.2f}M "
                      f"out={tok['out'] / 1e6:.2f}M  "
                      f"eta={(len(todo) - n) / rate / 60:.0f}min", flush=True)
            if args.deadline_min and (time.time() - t0) > args.deadline_min * 60:
                stop.set()

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(work, todo))
    out.close()
    el = time.time() - t0
    print(f"finished {_done_count} in {el / 60:.1f} min; "
          f"in={tok['in'] / 1e6:.2f}M out={tok['out'] / 1e6:.2f}M tokens; "
          f"{tok['in'] / max(el, 1):.0f} in-tok/s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
