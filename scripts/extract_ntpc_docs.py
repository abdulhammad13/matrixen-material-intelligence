#!/usr/bin/env python3
"""
Memory-safe text/table extraction over the downloaded NTPC tender documents.

The sandbox has ~2 GB RAM, so this runs strictly sequentially, frees each PDF
immediately, uses pypdf (cheap) for full text and pdfplumber (expensive) only
for the first few pages where the BOQ / technical tables live, and appends to
CSV as it goes with a checkpoint so it can be resumed.

Outputs
  data/processed/extracted_items/ntpc_doc_text.csv
  data/processed/extracted_items/ntpc_doc_tables.csv
  data/processed/extracted_items/ntpc_text/<doc>.txt
"""
import csv
import glob
import json
import os
import re
import sys

SRC = "data/raw/ntpc/documents"
OUT = "data/processed/extracted_items"
TXT = os.path.join(OUT, "ntpc_text")
CKPT = os.path.join(OUT, "ntpc_extract_checkpoint.json")

TABLE_PAGES = int(os.environ.get("TABLE_PAGES", "12"))

from pypdf import PdfReader  # noqa: E402


def text_via_pypdf(path):
    try:
        r = PdfReader(path)
        n = len(r.pages)
        parts = []
        for p in r.pages:
            try:
                parts.append(p.extract_text() or "")
            except Exception:
                parts.append("")
        return "\n".join(parts), n
    except Exception as e:
        return "", 0


def tables_via_pdfplumber(path, limit):
    rows = []
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages[:limit]):
                try:
                    for tb in (page.extract_tables() or []):
                        for r in tb:
                            cells = [re.sub(r"\s+", " ", (c or "")).strip() for c in r]
                            if any(cells):
                                rows.append({"page": i + 1, "cells": " | ".join(cells)})
                except Exception:
                    pass
    except Exception:
        pass
    return rows


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(TXT, exist_ok=True)
    files = sorted(glob.glob(os.path.join(SRC, "*")))
    pdfs = [f for f in files if f.lower().endswith(".pdf")]
    print(f"pdfs: {len(pdfs)}", flush=True)

    done = set()
    if os.path.exists(CKPT):
        done = set(json.load(open(CKPT)).get("done", []))
        print(f"resuming, {len(done)} already done", flush=True)

    text_path = os.path.join(OUT, "ntpc_doc_text.csv")
    tab_path = os.path.join(OUT, "ntpc_doc_tables.csv")
    new_text = not os.path.exists(text_path)
    new_tab = not os.path.exists(tab_path)
    ft = open(text_path, "a", newline="", encoding="utf-8")
    fb = open(tab_path, "a", newline="", encoding="utf-8")
    wt = csv.DictWriter(ft, fieldnames=["nit_id", "doc_name", "n_pages", "n_chars",
                                        "text_head", "text_path", "error"])
    wb = csv.DictWriter(fb, fieldnames=["nit_id", "doc_name", "page", "cells"])
    if new_text:
        wt.writeheader()
    if new_tab:
        wb.writeheader()

    n = 0
    for path in pdfs:
        base = os.path.basename(path)
        if base in done:
            continue
        m = re.match(r"^(\d+)_(.+)$", base)
        nit_id = m.group(1) if m else ""
        doc_name = m.group(2) if m else base
        try:
            full, npages = text_via_pypdf(path)
            tpath = os.path.join(TXT, base.rsplit(".", 1)[0] + ".txt")
            with open(tpath, "w", encoding="utf-8") as f:
                f.write(full)
            wt.writerow({"nit_id": nit_id, "doc_name": doc_name, "n_pages": npages,
                         "n_chars": len(full),
                         "text_head": re.sub(r"\s+", " ", full)[:1500],
                         "text_path": tpath, "error": ""})
            for r in tables_via_pdfplumber(path, TABLE_PAGES):
                wb.writerow({"nit_id": nit_id, "doc_name": doc_name, **r})
        except Exception as e:
            wt.writerow({"nit_id": nit_id, "doc_name": doc_name, "n_pages": "",
                         "n_chars": 0, "text_head": "", "text_path": "",
                         "error": repr(e)})
        done.add(base)
        n += 1
        if n % 50 == 0:
            ft.flush()
            fb.flush()
            json.dump({"done": sorted(done)}, open(CKPT, "w"))
            print(f"  ...{len(done)}/{len(pdfs)}", flush=True)

    ft.close()
    fb.close()
    json.dump({"done": sorted(done)}, open(CKPT, "w"))
    print(f"DONE {len(done)}/{len(pdfs)} documents extracted", flush=True)


if __name__ == "__main__":
    main()
