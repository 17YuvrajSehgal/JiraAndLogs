#!/usr/bin/env python3
"""Upload an anonymized dataset to Zenodo for double-blind review.

Streams files via Zenodo's bucket API (handles multi-GB files), shows progress,
verifies each upload's MD5, sets ANONYMIZED metadata (Creators = "Anonymous", no
funding, no code-repo links), and STOPS before publishing so you can review and
click Publish yourself in the web UI.

USAGE
-----
1. Get a Personal Access Token:
     - Production: https://zenodo.org/account/settings/applications/tokens/new/
     - Sandbox (recommended FIRST, for a dry run): https://sandbox.zenodo.org/...
       (sandbox + production are SEPARATE accounts with SEPARATE tokens)
   Scopes needed: deposit:write  (and deposit:actions only if you later publish via API)

2. Put the token in your environment (do NOT hard-code it):
     PowerShell:  $env:ZENODO_TOKEN = "xxxxx"
     bash:        export ZENODO_TOKEN=xxxxx

3. Dry-run on sandbox first:
     python scripts/research-lab/zenodo_upload.py --sandbox

4. Real upload (review + Publish in the browser afterwards):
     python scripts/research-lab/zenodo_upload.py

   Resume an interrupted run (skips already-uploaded files):
     python scripts/research-lab/zenodo_upload.py --deposition-id 1234567

Requires: requests  (pip install requests)
"""
from __future__ import annotations
import argparse, hashlib, os, sys, json

try:
    import requests
except ImportError:
    sys.exit("Missing dependency: pip install requests")

DEFAULT_STAGING = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "..", "..", "data", "zenodo-upload")

# ---- ANONYMIZED metadata (edit text freely; keep it identity-free) ----
METADATA = {
    "upload_type": "dataset",
    "title": "ARISE Datasets: Online Boutique, "
             "OpenTelemetry Demo, and World of Logs",
    "creators": [{"name": "Anonymous"}],          # <-- double-blind: no names/affiliation/ORCID
    "access_right": "open",
    "license": "cc-by-4.0",
    "language": "eng",
    "version": "1.0",
    "keywords": ["incident triage", "AIOps", "microservices observability",
                 "information retrieval", "Apache Jira", "datasets"],
    "description": (
        "<p>Three datasets for studying memory-augmented incident triage over "
        "microservices telemetry and real-world Apache Jira issues. "
        "<b>online-boutique</b> (6,720 telemetry windows x 347 tickets; full "
        "logs/traces/metrics/k8s events on the Google Online Boutique benchmark); "
        "<b>otel-demo</b> (1,643 windows x 147 tickets on the OpenTelemetry Demo, "
        "a cross-application generalization set); <b>world-of-logs</b> (9,341 real "
        "Apache-project Jira tickets, text only).</p>"
        "<p>Each archive extracts to a self-describing &lt;dataset-id&gt;/ directory "
        "with a dataset card, field schemas, gold relevance relations, and a "
        "MANIFEST.sha256.json integrity manifest; SHA256SUMS.txt lists archive "
        "checksums.</p>"
        "<p>This artifact accompanies a paper currently under double-blind review; "
        "author, institution, and source-repository information are intentionally "
        "withheld for anonymity. The World of Logs view contains only the "
        "Apache-Jira subset, derived from The Public Jira Dataset "
        "(doi:10.5281/zenodo.15719919, CC BY 4.0); the broader WoL source "
        "(The Stack / Stack Overflow / Common Crawl) is not redistributed.</p>"
    ),
    # Upstream sources only -- NEVER link your own code repo here (de-anonymizes).
    "related_identifiers": [
        {"identifier": "10.5281/zenodo.15719919", "relation": "references",
         "resource_type": "dataset"},
    ],
}

# Only these files get uploaded (explicit allowlist; excludes helper scripts/dirs).
def upload_files(staging: str) -> list[str]:
    out = []
    for fn in sorted(os.listdir(staging)):
        p = os.path.join(staging, fn)
        if not os.path.isfile(p):
            continue
        if fn.startswith("_") or fn.startswith("."):
            continue
        if fn.lower().endswith((".zip", ".md", ".txt")):
            out.append(p)
    return out


def md5_of(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class ProgressReader:
    """File wrapper that prints upload progress and exposes __len__ for requests."""
    def __init__(self, path):
        self.path = path
        self.size = os.path.getsize(path)
        self.name = os.path.basename(path)
        self._f = open(path, "rb")
        self._read = 0
        self._last_pct = -1

    def read(self, n=-1):
        chunk = self._f.read(n)
        self._read += len(chunk)
        pct = (self._read * 100 // self.size) if self.size else 100
        if pct != self._last_pct and (pct % 2 == 0 or not chunk):
            mb = self._read / 1e6
            print(f"\r    {self.name}: {pct:3d}%  ({mb:,.0f} MB)", end="", flush=True)
            self._last_pct = pct
        return chunk

    def __len__(self):
        return self.size

    def close(self):
        self._f.close()


def api(args):
    base = "https://sandbox.zenodo.org" if args.sandbox else "https://zenodo.org"
    return base, {"Authorization": f"Bearer {args.token}"}


def main():
    ap = argparse.ArgumentParser(description="Upload anonymized dataset to Zenodo (no auto-publish).")
    ap.add_argument("--staging-dir", default=DEFAULT_STAGING)
    ap.add_argument("--sandbox", action="store_true", help="Use sandbox.zenodo.org (dry run).")
    ap.add_argument("--deposition-id", type=int, default=None, help="Resume into an existing draft.")
    ap.add_argument("--no-metadata", action="store_true", help="Skip setting metadata.")
    ap.add_argument("--token", default=os.environ.get("ZENODO_TOKEN"))
    ap.add_argument("--metadata-file", default=None,
                    help="JSON file of Zenodo metadata; overrides the built-in dataset metadata.")
    args = ap.parse_args()

    if not args.token:
        sys.exit("No token. Set ZENODO_TOKEN env var or pass --token.")
    staging = os.path.abspath(args.staging_dir)
    files = upload_files(staging)
    if not files:
        sys.exit(f"No uploadable files (*.zip/*.md/*.txt) found in {staging}")
    base, headers = api(args)
    print(f"Target: {base}   staging: {staging}")
    print("Files to upload:")
    for f in files:
        print(f"  {os.path.getsize(f)/1e6:>10,.1f} MB  {os.path.basename(f)}")

    sess = requests.Session(); sess.headers.update(headers)

    # 1. Create or fetch the deposition
    if args.deposition_id:
        r = sess.get(f"{base}/api/deposit/depositions/{args.deposition_id}")
    else:
        r = sess.post(f"{base}/api/deposit/depositions", json={})
    if r.status_code not in (200, 201):
        sys.exit(f"Deposition create/fetch failed [{r.status_code}]: {r.text[:500]}")
    dep = r.json()
    dep_id = dep["id"]
    bucket = dep["links"]["bucket"]
    html = dep["links"].get("html", f"{base}/deposit/{dep_id}")
    reserved_doi = dep.get("metadata", {}).get("prereserve_doi", {}).get("doi")
    print(f"\nDeposition id: {dep_id}\n  edit page : {html}\n  reserved DOI: {reserved_doi}")

    # already-uploaded files (for resume)
    existing = {}
    rf = sess.get(f"{base}/api/deposit/depositions/{dep_id}/files")
    if rf.status_code == 200:
        for fi in rf.json():
            existing[fi.get("filename") or fi.get("key")] = fi.get("filesize") or fi.get("size")

    # 2. Upload each file via the bucket API (streamed)
    print("\nUploading:")
    for path in files:
        name = os.path.basename(path)
        size = os.path.getsize(path)
        if existing.get(name) == size:
            print(f"  = {name}: already uploaded ({size/1e6:,.0f} MB), skipping")
            continue
        pr = ProgressReader(path)
        try:
            resp = sess.put(f"{bucket}/{name}", data=pr,
                            headers={"Content-Length": str(size)}, timeout=None)
        finally:
            pr.close()
        print()  # newline after progress
        if resp.status_code not in (200, 201):
            sys.exit(f"  ! upload failed for {name} [{resp.status_code}]: {resp.text[:400]}")
        remote_md5 = resp.json().get("checksum", "").replace("md5:", "")
        local_md5 = md5_of(path)
        ok = remote_md5 == local_md5
        print(f"    -> {name}: md5 {'OK' if ok else 'MISMATCH!'} ({remote_md5[:12]}...)")
        if not ok:
            sys.exit(f"  ! MD5 mismatch for {name}: local {local_md5} vs zenodo {remote_md5}")

    # 3. Set anonymized metadata (best-effort; never blocks the upload)
    if not args.no_metadata:
        print("\nSetting anonymized metadata ...")
        meta = METADATA
        if args.metadata_file:
            with open(args.metadata_file, encoding="utf-8") as fh:
                meta = json.load(fh)
        mr = sess.put(f"{base}/api/deposit/depositions/{dep_id}",
                      json={"metadata": meta})
        if mr.status_code == 200:
            cr = [c.get("name") for c in meta.get("creators", [])]
            print(f"  metadata set (creators={cr}, license={meta.get('license')}, no funding/repo links).")
        else:
            print(f"  ! metadata not set [{mr.status_code}]: {mr.text[:400]}")
            print("  -> set it manually in the UI; here is the JSON to paste/adapt:")
            print(json.dumps(meta, indent=2))

    print("\nDONE. NOT published (by design).")
    print(f"Review and Publish here when ready: {html}")
    print("Reminder: confirm Creators='Anonymous', NO funding, NO links to your code repo.")


if __name__ == "__main__":
    main()
