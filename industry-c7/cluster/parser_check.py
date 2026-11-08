"""Are the tree-sitter parsers present on THIS compute node?

tree_sitter_language_pack fetches its parsers from GitHub at RUNTIME, and
compute nodes have no internet. The cache also defaults under /home, which
GPU compute nodes do not mount. Both were true on the first real run: 178
of 185 instances died with a DownloadError while the job looked healthy
from the outside, a server up and rows being written.

The languages come from function_stage.LANG_OF rather than a typed list.
An earlier version hardcoded java/cpp/scala and would have passed on a node
with no Go parser.

Env: C7 (tree root).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.environ["C7"] + "/scripts")
from function_stage import LANG_OF  # noqa: E402
from tree_sitter_language_pack import get_parser  # noqa: E402


def main() -> int:
    langs = sorted(set(LANG_OF.values()))
    bad = []
    for lg in langs:
        try:
            get_parser(lg)
        except Exception as e:                                # noqa: BLE001
            bad.append(f"{lg}: {type(e).__name__}")
    if bad:
        print("  MISSING PARSERS: " + "; ".join(bad), file=sys.stderr)
        return 1
    print("  parsers ok: " + ", ".join(langs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
