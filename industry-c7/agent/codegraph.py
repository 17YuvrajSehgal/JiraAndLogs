"""Code graph for the two agentic baselines (T25).

LocAgent (ACL 2025) and CoSIL (arXiv 2503.22424) both navigate a graph over
code entities. Neither can be run on this benchmark as published: both parse
Python with the `ast` module, and every project here is Java, Scala, C or
C++. See BASELINES.md for the full porting decision. This module rebuilds
the graph layer their algorithms need on the tree-sitter parsers the
function-level stage already uses, so the SEARCH STRATEGY is theirs and only
the parser underneath is ours.

Entities follow LocAgent's identifier format exactly: a fully qualified name
prefixed by the file, e.g. `src/utils.py:MathUtils.calculate_sum` becomes
`core/src/.../Herder.java:DistributedHerder.tick`. Edges are the four
LocAgent relation types, which are a superset of CoSIL's two call graphs:

    contain   directory -> file -> class -> function   (tree-sitter)
    import    file -> file                             (import / #include)
    invoke    function -> function                     (call-shaped names)
    inherit   class -> class                           (extends / : public)

Everything is computed ON DEMAND and cached per Workspace. A C++ repository
of this size has no few-second whole-graph build, which is the one place the
port cannot match LocAgent's published cost; the edge RELATION is the same,
only the materialisation differs. Resolution is capped per call so a single
traversal cannot spend the instance's whole time budget on `git grep`.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from function_stage import parser_for  # noqa: E402

# Resolution caps. Each unresolved name costs one `git grep`, and the grep
# cache is shared with the Workspace tools, so these bound the worst case
# rather than the typical one.
MAX_CALLEES = 12
MAX_NEIGHBOURS = 30
TREE_CHARS = 8000

CLASS_NODES = {
    "class_declaration", "interface_declaration", "enum_declaration",
    "record_declaration",                                    # java
    "class_definition", "object_definition", "trait_definition",  # scala
    "class_specifier", "struct_specifier",                   # cpp
}

# Call-shaped: an identifier immediately followed by `(`. Deliberately
# syntactic. A real callee resolver needs type inference, which is the thing
# neither baseline has either -- CoSIL asks the LLM to infer the call graph
# from source text, so a syntactic candidate list is the faithful input.
CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\s*\(")
JAVA_IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)", re.M)
CPP_INCLUDE_RE = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', re.M)
EXTENDS_RE = re.compile(
    r"\b(?:extends|implements)\s+([A-Za-z_][\w.]*)"      # java / scala
    r"|:\s*(?:public|protected|private)\s+([A-Za-z_][\w:]*)")  # cpp

# Names that resolve to thousands of lines and carry no structure. Mirrors
# tools.GENERIC_SYMBOLS in purpose; kept separate because the call-shaped
# regex catches a different family (control keywords, not exception types).
NOISE_CALLS = {
    "if", "for", "while", "switch", "catch", "return", "sizeof", "assert",
    "new", "delete", "throw", "super", "this", "println", "printf", "print",
    "get", "set", "add", "put", "run", "main", "size", "length", "value",
    "max", "min", "std", "string", "vector", "map", "list", "require",
}


class Graph:
    """Lazy code graph over one snapshot. Wraps a Workspace for file access."""

    def __init__(self, ws):
        self.ws = ws
        self._classes: dict[str, list] = {}
        self._imports: dict[str, list[str]] = {}
        self._rev_imports: dict[str, list[str]] | None = None
        self._by_basename: dict[str, list[str]] | None = None

    # ---- contain -----------------------------------------------------------
    def classes_of(self, path: str) -> list[tuple[str, int, int]]:
        """(name, start_line, end_line) for class-like nodes, 1-based."""
        if path in self._classes:
            return self._classes[path]
        out: list[tuple[str, int, int]] = []
        p = parser_for(path)
        blob = self.ws.snap.blob_of.get(path)
        if p is not None and blob:
            txt = self.ws._text_of(path)
            tree = p.parse(txt.encode("utf-8", "replace"))
            stack = [tree.root_node]
            while stack:
                n = stack.pop()
                if n.type in CLASS_NODES:
                    nm = n.child_by_field_name("name")
                    if nm is not None:
                        out.append((nm.text.decode("utf-8", "replace"),
                                    n.start_point[0] + 1, n.end_point[0] + 1))
                stack.extend(n.children)
            out.sort(key=lambda c: c[1])
        self._classes[path] = out
        return out

    def entities_of(self, path: str) -> list[dict]:
        """Every class and function in a file, as LocAgent-style entities.

        A function inside a class gets the qualified id `path:Class.func`,
        which is how both papers address a class member function.
        """
        classes = self.classes_of(path)
        out = [{"id": f"{path}:{c}", "type": "class", "name": c,
                "file": path, "line": s, "end": e}
               for c, s, e in classes]
        for fn, s, e in self.ws._funcs_of(path):
            owner = next((c for c, cs, ce in classes if cs <= s <= ce), None)
            # C++ out-of-line definitions already carry `Class::method`.
            bare = fn.rsplit("::", 1)[-1]
            qual = f"{owner}.{bare}" if owner else fn.replace("::", ".")
            out.append({"id": f"{path}:{qual}", "type": "function",
                        "name": bare, "file": path, "line": s, "end": e,
                        "owner": owner})
        return out

    def resolve(self, entity_id: str) -> dict | None:
        """An id back to its entity, tolerating a missing qualifier."""
        path, _, qual = (entity_id or "").partition(":")
        path = path.strip().replace("\\", "/").lstrip("./")
        if path not in self.ws.snap.blob_of:
            return None
        if not qual:
            return {"id": path, "type": "file", "name": path.rsplit("/", 1)[-1],
                    "file": path, "line": 1, "end": 1}
        ents = self.entities_of(path)
        for e in ents:
            if e["id"] == entity_id:
                return e
        tail = qual.replace("::", ".").rsplit(".", 1)[-1].lower()
        return next((e for e in ents if e["name"].lower() == tail), None)

    # ---- import ------------------------------------------------------------
    def _basename_index(self) -> dict[str, list[str]]:
        if self._by_basename is None:
            idx: dict[str, list[str]] = defaultdict(list)
            for f in self.ws.snap.files:
                idx[f.rsplit("/", 1)[-1].lower()].append(f)
            self._by_basename = dict(idx)
        return self._by_basename

    def imports_of(self, path: str) -> list[str]:
        """Files this file imports or includes, resolved inside the snapshot.

        CoSIL's module call graph is exactly this relation. Java and Scala
        imports name a package path; C and C++ includes name a file path.
        Both resolve by suffix against the snapshot, so an include that
        leaves the repository (a system header) simply drops out, which is
        the same filtering CoSIL applies by keeping only repository modules.
        """
        if path in self._imports:
            return self._imports[path]
        txt = self.ws._text_of(path)[:20000]
        idx, out = self._basename_index(), []
        for dotted in JAVA_IMPORT_RE.findall(txt):
            parts = dotted.split(".")
            if parts[-1] in ("*", ""):
                parts = parts[:-1]
            if not parts:
                continue
            stem = parts[-1].lower()
            for ext in (".java", ".scala"):
                for cand in idx.get(stem + ext, []):
                    if cand != path:
                        out.append(cand)
        for inc in CPP_INCLUDE_RE.findall(txt):
            inc = inc.replace("\\", "/")
            for cand in idx.get(inc.rsplit("/", 1)[-1].lower(), []):
                # an include of "db/foo.h" must not match "net/foo.h"
                if cand != path and cand.lower().endswith(inc.lower()):
                    out.append(cand)
        out = list(dict.fromkeys(out))[:MAX_NEIGHBOURS]
        self._imports[path] = out
        return out

    def imported_by(self, path: str) -> list[str]:
        """Reverse import edge, by grepping for this file's own basename."""
        base = path.rsplit("/", 1)[-1]
        stem = base.rsplit(".", 1)[0]
        hits = self.ws._grep(base) or self.ws._grep(stem)
        out = [f for f, _l, text in hits
               if f != path and ("import" in text or "#include" in text)]
        return list(dict.fromkeys(out))[:MAX_NEIGHBOURS]

    # ---- invoke ------------------------------------------------------------
    def body_of(self, ent: dict) -> str:
        lines = self.ws._text_of(ent["file"]).splitlines()
        return "\n".join(lines[ent["line"] - 1:ent["end"]])

    def invokes(self, ent: dict, limit: int = MAX_CALLEES) -> list[dict]:
        """Entities this one calls. Forward invoke edge.

        CoSIL needs this direction (it walks outward from a seed); our own
        `callers_of` only walks backward, so this is the one genuinely new
        traversal the baselines require.
        """
        names, seen = [], set()
        for m in CALL_RE.findall(self.body_of(ent)):
            low = m.lower()
            if low in NOISE_CALLS or low == ent["name"].lower() or m in seen:
                continue
            seen.add(m)
            names.append(m)
            if len(names) >= limit * 3:
                break
        out = []
        for nm in names:
            for f, lno, _t in self.ws._grep(nm)[:6]:
                if f == ent["file"]:
                    continue
                host = next((e for e in self.entities_of(f)
                             if e["type"] == "function"
                             and e["line"] <= lno <= e["end"]
                             and e["name"] == nm), None)
                if host:
                    out.append(host)
                    break
            if len(out) >= limit:
                break
        return out

    def invoked_by(self, ent: dict, limit: int = MAX_CALLEES) -> list[dict]:
        """Entities that call this one. Reuses the Workspace grep cache."""
        out = []
        for c in (self.ws.callers_of(ent["name"]) or {}).get("callers", []):
            host = self.resolve(f"{c['file']}:{c['caller']}")
            if host and host["id"] != ent["id"]:
                out.append(host)
            if len(out) >= limit:
                break
        return out

    # ---- inherit -----------------------------------------------------------
    def inherits(self, ent: dict, limit: int = 6) -> list[dict]:
        head = "\n".join(self.body_of(ent).splitlines()[:3])
        out = []
        for a, b in EXTENDS_RE.findall(head):
            nm = (a or b).replace("::", ".").rsplit(".", 1)[-1]
            if not nm:
                continue
            for f in self._basename_index().get(nm.lower() + ".java", []) + \
                    self._basename_index().get(nm.lower() + ".h", []):
                tgt = self.resolve(f"{f}:{nm}")
                if tgt:
                    out.append(tgt)
                    break
            if len(out) >= limit:
                break
        return out

    # ---- traversal ---------------------------------------------------------
    def neighbours(self, ent: dict, relations: set[str],
                   direction: str) -> list[dict]:
        """One hop under the chosen relation and direction types."""
        out: list[dict] = []
        if "contain" in relations:
            if ent["type"] == "file":
                out += self.entities_of(ent["file"])
            elif direction in ("downstream", "both"):
                out += [e for e in self.entities_of(ent["file"])
                        if e["type"] == "function"
                        and ent["line"] <= e["line"] <= ent["end"]
                        and e["id"] != ent["id"]]
        if "invoke" in relations and ent["type"] == "function":
            if direction in ("downstream", "both"):
                out += self.invokes(ent)
            if direction in ("upstream", "both"):
                out += self.invoked_by(ent)
        if "inherit" in relations and ent["type"] == "class":
            out += self.inherits(ent)
        if "import" in relations:
            paths = (self.imports_of(ent["file"])
                     if direction in ("downstream", "both") else [])
            if direction in ("upstream", "both"):
                paths += self.imported_by(ent["file"])
            out += [{"id": p, "type": "file", "name": p.rsplit("/", 1)[-1],
                     "file": p, "line": 1, "end": 1} for p in paths]
        uniq, seen = [], {ent["id"]}
        for e in out:
            if e["id"] not in seen:
                seen.add(e["id"])
                uniq.append(e)
        return uniq[:MAX_NEIGHBOURS]

    def traverse(self, start: list[str], relations: set[str], direction: str,
                 hops: int, entity_types: set[str]) -> dict:
        """Type-aware BFS. LocAgent's TraverseGraph: one action, many hops."""
        frontier, seen, levels = [], set(), []
        for sid in start[:5]:
            e = self.resolve(sid)
            if e and e["id"] not in seen:
                seen.add(e["id"])
                frontier.append(e)
        if not frontier:
            return {"error": "no start entity resolved", "start": start}
        levels.append([e["id"] for e in frontier])
        for _ in range(max(1, min(int(hops or 1), 3))):
            nxt = []
            for e in frontier[:12]:
                for n in self.neighbours(e, relations, direction):
                    if n["id"] in seen:
                        continue
                    if entity_types and n["type"] not in entity_types:
                        continue
                    seen.add(n["id"])
                    nxt.append(n)
            if not nxt:
                break
            levels.append([e["id"] for e in nxt][:MAX_NEIGHBOURS])
            frontier = nxt
        return {"start": levels[0], "hops": len(levels) - 1,
                "relations": sorted(relations), "direction": direction,
                "levels": [{"hop": i, "entities": ids}
                           for i, ids in enumerate(levels)],
                "n_reached": sum(len(x) for x in levels[1:])}

    # ---- structure trees (CoSIL) -------------------------------------------
    def repo_tree(self, budget: int = TREE_CHARS) -> str:
        """CoSIL's repository structure tree, elided to fit a prompt.

        CoSIL feeds the whole tree. A Python SWE-bench repo has a few
        hundred source files; MongoDB has thousands, so directories past the
        budget are summarised by file count rather than listed. This is a
        deviation forced by repository size and is reported as one.
        """
        dirs = sorted(self.ws.dirs())
        rows, used, elided = [], 0, 0
        for d in dirs:
            files = [f.rsplit("/", 1)[-1] for f in self.ws.snap.files
                     if f.rsplit("/", 1)[0] == d]
            if not files:
                continue
            line = f"{d}/  ({len(files)} files)"
            if used + len(line) < budget:
                shown = ", ".join(sorted(files)[:12])
                more = "" if len(files) <= 12 else f", +{len(files) - 12} more"
                line = f"{d}/\n    {shown}{more}"
                rows.append(line)
                used += len(line)
            else:
                elided += len(files)
        if elided:
            rows.append(f"... {elided} further source files in "
                        f"{len(dirs) - len(rows)} directories not listed")
        return "\n".join(rows)

    def file_tree(self, paths: list[str]) -> str:
        """CoSIL's file structure tree: classes and functions per file."""
        rows = []
        for p in paths[:20]:
            ents = self.entities_of(p)
            cls = [e for e in ents if e["type"] == "class"]
            fns = [e for e in ents if e["type"] == "function"]
            rows.append(f"{p}")
            for c in cls[:12]:
                members = [e["name"] for e in fns if e.get("owner") == c["name"]]
                rows.append(f"  class {c['name']}  "
                            f"[{', '.join(members[:14]) or 'no members parsed'}]")
            free = [e["name"] for e in fns if not e.get("owner")]
            if free:
                rows.append(f"  functions: {', '.join(free[:20])}")
        return "\n".join(rows)
