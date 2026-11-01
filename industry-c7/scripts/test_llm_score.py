"""Self-check for the LLM path resolver (llm_score.Resolver).

The resolver decides whether a model-returned path counts as a hit, so a
bug here silently moves every LLM accuracy number. Run it before scoring.

Usage:
    python industry-c7/scripts/test_llm_score.py
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm_score import Resolver  # noqa: E402

UNIVERSE = [
    "core/src/main/scala/kafka/log/LogManager.scala",
    "clients/src/main/java/org/apache/kafka/common/network/KafkaChannel.java",
    "src/mongo/db/catalog/collection.cpp",
    "src/mongo/db/catalog/collection.h",
    "storage/innobase/btr/btr0cur.cc",
]
CASES = [
    ("core/src/main/scala/kafka/log/LogManager.scala", UNIVERSE[0]),
    ("./core/src/main/scala/kafka/log/LogManager.scala", UNIVERSE[0]),
    ("kafka/core/src/main/scala/kafka/log/LogManager.scala", UNIVERSE[0]),
    ("LogManager.scala", UNIVERSE[0]),
    ("btr0cur.cc", UNIVERSE[4]),
    ("db/catalog/collection.cpp", UNIVERSE[2]),
    ("collection.cpp", UNIVERSE[2]),
    ("does/not/exist.java", None),
    ("", None),
    (None, None),
]


def main() -> int:
    r, stats, bad = Resolver(UNIVERSE), Counter(), 0
    for raw, want in CASES:
        got = r.resolve(raw, stats)
        if got != want:
            bad += 1
            print(f"FAIL {raw!r}: got {got!r}, want {want!r}")
    assert stats["dropped"] == 3, f"expected 3 drops, got {stats['dropped']}"
    assert bad == 0, f"{bad} resolver mismatches"
    print(f"resolver: {len(CASES)} cases pass; {dict(stats)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
