#!/usr/bin/env python3
"""
Push the full SIH 26099 dataset to Hugging Face Hub.

Three phases, in order:
  1. the text tree  (data/ + scripts/, binary files excluded)
  2. the local PDFs (uploaded one by one so Xet storage is used)
  3. the NTPC tender PDFs that were pruned from the workspace, streamed
     straight from ntpctender.ntpc.co.in into Xet without ever touching disk

The token is read from ~/.hftoken (chmod 600), never hardcoded.
"""
import concurrent.futures as cf
import io
import os
import re
import sys
import threading
import time

import pandas as pd
import requests
from huggingface_hub import upload_file, upload_folder

tok = open(os.path.expanduser("~/.hftoken")).read().strip()
REPO = "Prasenjeet25/sih26099-cpse-material-codes"
DOCS = "data/raw/ntpc/tenders/documents_index.csv"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

lock = threading.Lock()
state = {"ok": 0, "fail": 0, "bytes": 0, "skip": 0}


def is_binary(path):
    with open(path, "rb") as f:
        return b"\x00" in f.read(8192)


def local_pdfs():
    out = []
    for root in ("data", "scripts"):
        for dp, _, fns in os.walk(root):
            for fn in fns:
                p = os.path.join(dp, fn)
                if os.path.isfile(p) and is_binary(p):
                    out.append(p)
    return sorted(out)


def phase1_text_tree():
    print("=" * 70, "\nPHASE 1  text tree", flush=True)
    # upload_folder would choke on binaries, so stage a text-only copy is not
    # needed: pass ignore_patterns for the known binary extensions instead.
    upload_folder(folder_path="data", path_in_repo="data", repo_id=REPO,
                  repo_type="dataset", token=tok,
                  ignore_patterns=["*.pdf", "*.zip", "*.PNG", "*.png",
                                   "*.jpg", "*.ico", "*.woff*", "*.ttf"])
    print("  uploaded data/", flush=True)
    upload_folder(folder_path="scripts", path_in_repo="scripts", repo_id=REPO,
                  repo_type="dataset", token=tok)
    print("  uploaded scripts/", flush=True)
    upload_file(path_or_fileobj="DATASET_README.md", path_in_repo="README.md",
                repo_id=REPO, repo_type="dataset", token=tok)
    upload_file(path_or_fileobj="MANIFEST.csv", path_in_repo="MANIFEST.csv",
                repo_id=REPO, repo_type="dataset", token=tok)
    upload_file(path_or_fileobj="PRUNED.txt", path_in_repo="PRUNED.txt",
                repo_id=REPO, repo_type="dataset", token=tok)
    print("  uploaded README.md, MANIFEST.csv, PRUNED.txt", flush=True)


def phase2_local_pdfs():
    print("=" * 70, "\nPHASE 2  local PDFs", flush=True)
    pdfs = local_pdfs()
    print(f"  {len(pdfs)} binary files", flush=True)
    for p in pdfs:
        upload_file(path_or_fileobj=p, path_in_repo=p, repo_id=REPO,
                    repo_type="dataset", token=tok)
        print(f"  + {p}", flush=True)


def expected_path(row):
    """Reproduce the filename harvest_ntpc.py used for this document."""
    name = re.sub(r"[^\w\.\-]+", "_", (row["doc_name"] or os.path.basename(row["doc_url"])))[:90]
    ext = os.path.splitext(row["doc_url"].split("?")[0])[1] or ".bin"
    if not name.lower().endswith(ext.lower()):
        name += ext
    return f"data/raw/ntpc/documents/{row['nit_id']}_{name}"


def push_one(row):
    path = expected_path(row)
    url = row["doc_url"]
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    for attempt in range(4):
        try:
            r = s.get(url, timeout=180)
            if r.status_code == 200 and r.content:
                buf = io.BytesIO(r.content)
                buf.name = os.path.basename(path)
                upload_file(path_or_fileobj=buf, path_in_repo=path,
                            repo_id=REPO, repo_type="dataset", token=tok)
                with lock:
                    state["ok"] += 1
                    state["bytes"] += len(r.content)
                return True
            last = f"HTTP {r.status_code}"
        except Exception as e:
            last = repr(e)
        time.sleep(2 * (attempt + 1))
    with lock:
        state["fail"] += 1
    print(f"  ! {path} :: {last}", file=sys.stderr, flush=True)
    return False


def phase3_ntpc_pdfs():
    print("=" * 70, "\nPHASE 3  NTPC tender PDFs streamed from source", flush=True)
    d = pd.read_csv(DOCS, dtype=str).fillna("")
    d = d[d["doc_url"] != ""].copy()
    d = d.drop_duplicates(subset=["doc_url"])
    print(f"  documents to stream: {len(d)} "
          f"(advertised {pd.to_numeric(d['bytes'], errors='coerce').sum() / 1e6:.0f} MB)",
          flush=True)
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for i, _ in enumerate(ex.map(push_one, d.to_dict("records")), 1):
            if i % 50 == 0:
                print(f"  ...{i}/{len(d)} ok={state['ok']} fail={state['fail']} "
                      f"{state['bytes'] / 1e6:.0f} MB", flush=True)
    print(f"  streamed ok={state['ok']} fail={state['fail']} "
          f"total={state['bytes'] / 1e6:.1f} MB", flush=True)


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    if phase in ("all", "1"):
        phase1_text_tree()
    if phase in ("all", "2"):
        phase2_local_pdfs()
    if phase in ("all", "3"):
        phase3_ntpc_pdfs()
    print("\nDONE", flush=True)
