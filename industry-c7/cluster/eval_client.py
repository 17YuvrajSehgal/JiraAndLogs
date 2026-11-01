"""Checkpointed eval client for the vLLM OpenAI endpoint.

Reads a JSONL of {"id": ..., "messages": [...]} (or {"id","prompt"}),
appends {"id", "response", "usage", "error"} to --out as each call
finishes. Restart-safe: ids already in --out are skipped, so a killed
job resumes where it stopped. Stdlib only (no pip needed on compute
nodes).

Usage:
    python eval_client.py --prompts p.jsonl --endpoint http://localhost:8000/v1 \
        --model qwen3-235b-fp8 --out responses.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request


def call(endpoint: str, model: str, messages: list, max_tokens: int,
         retries: int = 3) -> dict:
    body = json.dumps({"model": model, "messages": messages,
                       "max_tokens": max_tokens, "temperature": 0}).encode()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                f"{endpoint}/chat/completions", data=body,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001 - retry anything, report last
            if attempt == retries - 1:
                return {"error": str(e)}
            time.sleep(10 * (attempt + 1))
    return {"error": "unreachable"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prompts", required=True)
    ap.add_argument("--endpoint", default="http://localhost:8000/v1")
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-tokens", type=int, default=600)
    args = ap.parse_args()

    done = set()
    try:
        for line in open(args.out, encoding="utf-8"):
            done.add(json.loads(line)["id"])
    except FileNotFoundError:
        pass

    todo = [json.loads(l) for l in open(args.prompts, encoding="utf-8")]
    todo = [t for t in todo if t["id"] not in done]
    print(f"{len(done)} already done, {len(todo)} to go", flush=True)

    t0 = time.time()
    with open(args.out, "a", encoding="utf-8") as out:
        for i, t in enumerate(todo):
            messages = t.get("messages") or [{"role": "user",
                                              "content": t["prompt"]}]
            r = call(args.endpoint, args.model, messages, args.max_tokens)
            row = {"id": t["id"]}
            if "error" in r:
                row["error"] = r["error"]
            else:
                row["response"] = r["choices"][0]["message"]["content"]
                row["usage"] = r.get("usage", {})
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            if i % 20 == 0:
                rate = (i + 1) / (time.time() - t0)
                print(f"  {i + 1}/{len(todo)} ({rate:.2f}/s, "
                      f"eta {int((len(todo) - i - 1) / max(rate, 1e-9) / 60)}m)",
                      flush=True)
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
