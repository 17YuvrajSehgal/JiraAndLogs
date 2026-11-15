"""Does match_symbol match the names tree-sitter actually produces?

The bug this pins: the qualifier was stripped from the submitted symbol but
not from the stored name, so every qualified C++ name missed. tree-sitter
gives "JOIN::exec" for sql_select.cc; the submitted "JOIN::exec" became
"exec", never matched, and was recorded as a symbol the file does not
contain. The unresolved rate then tracked language and not difficulty: qt
85%, mongodb 75%, impala 62%, mariadb 44%, against 10-20% on Java.

Run: python industry-c7/scripts/test_match_symbol.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from localize import match_symbol  # noqa: E402

CPP = [("dbug_serve_apcs", 10, 20), ("JOIN::prepare", 30, 90),
       ("JOIN::exec", 100, 160), ("JOIN::exec_inner", 170, 200),
       ("Pushdown_select::execute", 210, 230)]
JAVA = [("Vectorizer", 5, 9), ("vectorizeMapWork", 20, 40),
        ("doVectorize", 50, 70)]
AMBIG = [("A::run", 10, 20), ("B::run", 30, 40)]

cases = [
    # (funcs, submitted, expected matched name or None)
    (CPP,  "JOIN::exec",                "JOIN::exec"),       # the bug
    (CPP,  "exec",                      "JOIN::exec"),       # bare still works
    (CPP,  "JOIN::exec()",              "JOIN::exec"),       # trailing parens
    (CPP,  "JOIN::exec(THD *thd)",      "JOIN::exec"),       # with args
    (CPP,  "join::EXEC",                "JOIN::exec"),       # wrong case
    (CPP,  "Pushdown_select::execute",  "Pushdown_select::execute"),
    (CPP,  "JOIN::exec_inner",          "JOIN::exec_inner"), # not the prefix
    (CPP,  "JOIN.exec",                 "JOIN::exec"),       # dot form
    (CPP,  "JOIN#exec",                 "JOIN::exec"),       # hash form
    (CPP,  "JOIN::nonsense",            None),               # real miss
    (CPP,  "totally_absent",            None),               # real miss
    (JAVA, "vectorizeMapWork",          "vectorizeMapWork"),
    (JAVA, "Vectorizer.doVectorize",    "doVectorize"),      # qualified java
    (JAVA, "vectorize",                 None),               # close but absent
    (AMBIG,"run",                       "A::run"),           # first definition
    (AMBIG,"B::run",                    "B::run"),           # qualifier wins
    ([],   "anything",                  None),               # nothing parsed
    (CPP,  "",                          None),               # empty symbol
]
fail = 0
for funcs, sym, want in cases:
    got = match_symbol(funcs, sym)
    name = got[0] if got else None
    ok = name == want
    fail += not ok
    print(f"{'ok ' if ok else 'FAIL'} {sym!r:<28} -> {name!r:<28} want {want!r}")
print(f"\n{len(cases)} cases, {fail} failed")
sys.exit(1 if fail else 0)
