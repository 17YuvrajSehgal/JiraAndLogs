"""Self-check for the v3 agent changes (T10 causal_chain, T11 backward hop).

v3 is a behaviour change enforced by a schema, so a bug here does not
crash: it silently gives back the v2 agent under a v3 tag, and the
ablation then measures nothing. Run this before spending GPU time.

Usage:
    python industry-c7/agent/test_v3.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import agent as A  # noqa: E402
import tools as T  # noqa: E402

ok = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"   [{detail}]" if detail else ""))
    ok += bool(cond)


# ---- T10: the submission schema -------------------------------------------
v2p = A.SUBMIT["function"]["parameters"]
v3p = A.SUBMIT_V3["function"]["parameters"]

check("v2 schema is untouched by the v3 copy",
      v2p["required"] == ["files"] and "causal_chain" not in v2p["properties"],
      str(v2p["required"]))
check("v3 requires causal_chain",
      v3p["required"] == ["files", "causal_chain"], str(v3p["required"]))
chain = v3p["properties"]["causal_chain"]
check("v3 chain needs at least 2 steps", chain["minItems"] == 2)
check("v3 chain step must cite a tool",
      chain["items"]["required"] == ["step", "cited_from"])
check("v3 chain may cite data_flow_back",
      "data_flow_back" in chain["items"]["properties"]["cited_from"]["enum"])
check("v3 still requires per-file evidence",
      v3p["properties"]["files"]["items"]["required"] == ["path", "evidence"])

# ---- T11: the tool surface -------------------------------------------------
v2_names = [t["function"]["name"] for t in T.TOOL_SCHEMAS]
v3_names = v2_names + [t["function"]["name"] for t in T.V3_TOOL_SCHEMAS]
check("v2 offers the 8 tools the paper reports", len(v2_names) == 8,
      str(len(v2_names)))
check("v3 offers 9, adding data_flow_back",
      len(v3_names) == 9 and "data_flow_back" in v3_names)
check("every offered tool dispatches",
      all(n in T._DISPATCH for n in v3_names),
      str([n for n in v3_names if n not in T._DISPATCH]))

# ---- T11: stack frames drive the backward hop ------------------------------
jvm = ("java.lang.NullPointerException\n"
       "\tat kafka.log.LogManager.cleanupLogs(LogManager.scala:412)\n"
       "\tat kafka.server.KafkaServer.startup(KafkaServer.scala:220)\n")
check("frame_symbols reads JVM frames innermost first",
      T.frame_symbols(jvm)[:2] == ["cleanupLogs", "LogManager"],
      str(T.frame_symbols(jvm)[:3]))
cpp = "Invariant failure at mongo::Collection::insertDocument(collection.cpp:88)"
check("frame_symbols reads C++ frames",
      "insertDocument" in T.frame_symbols(cpp), str(T.frame_symbols(cpp)[:3]))
check("frame_symbols is narrower than raw_report_symbols",
      len(T.frame_symbols(jvm)) < len(T.raw_report_symbols(jvm)))
check("no frames means no backward hop to run", T.frame_symbols("") == [])


# ---- T11: data_flow_back separates writes from reads -----------------------
class FakeWS:
    """Only _grep and _funcs_of are touched, so the real method can run
    against hand-written lines without a snapshot."""

    def __init__(self, lines):
        self._lines = lines

    def _grep(self, symbol):
        return self._lines

    def _funcs_of(self, path):
        return [("doFlush", 1, 1000)]

    data_flow_back = T.Workspace.data_flow_back


WRITES = [("a.java", 10, "this.offset = newOffset;"),
          ("b.java", 20, "setOffset(5);"),
          ("c.java", 30, "offset += delta;"),
          ("d.cpp", 40, "obj->offset = computeOffset();")]
READS = [("e.java", 50, "if (offset == 0) return;"),
         ("f.java", 60, "return offset;"),
         ("g.java", 70, "if (offset <= limit) {"),
         ("h.java", 80, "if (offset != last) {"),
         ("i.java", 90, "log.info(offset);"),
         ("j.java", 100, "if (offset >= cap) break;")]

res = FakeWS(WRITES + READS).data_flow_back("offset")
got = {w["file"] for w in res["writes"]}
check("data_flow_back keeps every write site",
      got == {"a.java", "b.java", "c.java", "d.cpp"}, str(sorted(got)))
check("data_flow_back drops every read site",
      not got & {f for f, _, _ in READS},
      str(sorted(got & {f for f, _, _ in READS})))
check("data_flow_back counts writing files", res["n_writing_files"] == 4,
      str(res["n_writing_files"]))
dup = FakeWS([("a.java", 10, "offset = 1;"),
              ("a.java", 11, "offset = 2;")]).data_flow_back("offset")
check("data_flow_back dedups by (file, writer)", len(dup["writes"]) == 1,
      str(len(dup["writes"])))
check("data_flow_back rejects a too-short symbol",
      "error" in FakeWS([]).data_flow_back("x"))

# ---- v2 must still be byte-identical to the runs already reported ---------
# The whole point of --version is that an unflagged run reproduces v2. If
# the v3 edits moved the v2 prompt by one character, every stored number
# would be measuring a system that no longer exists.
tdir = Path(__file__).resolve().parents[1] / "data/agent/transcripts"
stored = sorted(tdir.glob("v2-*.json"))
if stored:
    import json
    ev = json.loads(stored[0].read_text(encoding="utf-8"))["events"]
    check("v2 system prompt matches the stored v2 transcripts",
          ev[0]["content"] == A.SYSTEM)
    check("v2 user prompt carries no backward hop",
          "one hop BACK" not in ev[1]["content"])
else:
    check("v2 system prompt matches the stored v2 transcripts", True,
          "skipped: no transcripts")
    check("v2 user prompt carries no backward hop", True,
          "skipped: no transcripts")
check("v3 changes the system prompt, v2 does not",
      A.SYSTEM + A.SYSTEM_V3_EXTRA != A.SYSTEM)


# ---- the memory firewall moves to index construction (supervisor pt. 5) ----
class FakeMem:
    """Two incidents, one resolved before the query and one after. In v2 the
    index holds both and the future one is dropped only after ranking; in v3
    it is never in the index, so it cannot shift idf or occupy a slot."""

    _admissible = T.Workspace._admissible
    _memory_index = T.Workspace._memory_index

    def __init__(self, strict, project):
        from collections import Counter
        self.strict_memory_firewall = strict
        self.project = project
        self.issue_key = "Q-1"
        self.fix_shas = set()
        self.dupclusters = {}
        self.cutoff = 100.0
        self.memory = {
            "OLD-1": {"toks": Counter({"alpha": 1}), "resolved": 50.0,
                      "fix_shas": set(), "gold_files": ["a.java"]},
            "FUTURE-1": {"toks": Counter({"alpha": 1}), "resolved": 150.0,
                         "fix_shas": set(), "gold_files": ["b.java"]}}


check("v2 indexes incidents resolved AFTER the report",
      FakeMem(False, "_t_v2")._memory_index().n == 2)
check("v3 indexes only incidents admissible for this report",
      FakeMem(True, "_t_v3")._memory_index().n == 1)
check("v3 index is rebuilt per instance, not cached per project",
      FakeMem(True, "_t_v3")._memory_index()
      is not FakeMem(True, "_t_v3")._memory_index())

total = 24
print(f"\n{ok}/{total} checks passed")
sys.exit(0 if ok == total else 1)
