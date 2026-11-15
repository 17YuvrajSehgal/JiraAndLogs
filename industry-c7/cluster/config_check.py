"""Ask the server that is about to run a shard what it is actually serving.

Five shards on five clusters have to be ONE system. Five sbatch files that
agree on paper do not prove that: the local LM Studio server silently
ignored chat_template_kwargs and kept reasoning on while every config said
off, and a shard served at a different context window would be a confound
that nothing in the output records.

So each shard asks its own server, on the compute node, before the first
instance runs. Exits non-zero and the job refuses to start.

Env: C7 (tree root), ENDPOINT (http://host:port), WANT_MAXLEN.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.environ["C7"] + "/agent")
sys.path.insert(0, os.environ["C7"] + "/scripts")
import agent as A  # noqa: E402

EP = os.environ["ENDPOINT"]
WANT = int(os.environ["WANT_MAXLEN"])


def main() -> int:
    served = json.loads(
        urllib.request.urlopen(EP + "/v1/models", timeout=60).read())
    m = served["data"][0]
    got = m.get("max_model_len")
    print(f"  served model: {m['id']}  max_model_len={got}")
    if got != WANT:
        print(f"  REFUSING: server window {got} != {WANT}", file=sys.stderr)
        return 1

    body = {"model": A.MODEL, "temperature": 0, "max_tokens": 200, "seed": 42,
            "messages": [{"role": "user",
                          "content": "What is 17*23? Number only."}],
            **A.THINK_SWITCH}
    req = urllib.request.Request(
        EP + "/v1/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=300).read())
    except Exception as e:                                    # noqa: BLE001
        print(f"  the server REJECTED the thinking switch: {e}",
              file=sys.stderr)
        print(f"  switch sent: {json.dumps(A.THINK_SWITCH)}", file=sys.stderr)
        return 1

    msg = d["choices"][0]["message"]
    rt = (d.get("usage", {}).get("completion_tokens_details") or {}).get(
        "reasoning_tokens", 0)
    has = bool(msg.get("reasoning_content") or msg.get("reasoning"))
    print(f"  thinking requested: {A.ENABLE_THINKING}; server returned "
          f"reasoning_tokens={rt}, reasoning_field={has}")
    if not A.ENABLE_THINKING and (rt or has):
        print("  REFUSING: thinking is configured OFF and the server kept "
              "it ON.", file=sys.stderr)
        return 1
    if A.ENABLE_THINKING and not (rt or has):
        print("  REFUSING: thinking is configured ON and the server kept "
              "it OFF.", file=sys.stderr)
        return 1
    print("  config check ok: window, temperature 0, thinking off")
    return 0


if __name__ == "__main__":
    sys.exit(main())
