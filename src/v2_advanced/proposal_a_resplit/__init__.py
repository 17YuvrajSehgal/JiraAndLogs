"""Proposal A — in-distribution train/val/test split.

The v1 panel splits by `scenario_family` so the families in test never
appear in train. That's out-of-distribution evaluation — fine for some
research questions but punishing for the production scenario the system
is actually built for ("we've seen this kind of problem before, find it
again fast").

Proposal A adds a SECOND split manifest, keyed by window_id, that
assigns each individual window to train / val / test at 70/15/15
stratified by scenario_family. Both manifests live side-by-side; the
comparison harness can be pointed at either one.

Files:
    make_resplit.py     — script that generates the new manifest
    window_split.py     — loader + iter_split equivalent for window-level
"""
