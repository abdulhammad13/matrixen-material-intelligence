#!/usr/bin/env python3
"""
Trim the bulky, *reproducible* parts of the raw collection so the workspace
stays inside the snapshot budget (~128 MB), while keeping every structured
extract and a documented sample of the original files.

Nothing here is the only copy of extracted information:
  * every CSV extract is kept in full
  * the NIT/tender HTML pages and PDFs are re-downloadable from the portals
    using the URLs recorded in the CSVs (detail_url, doc_url, nit_doc_url)

What is kept
  data/raw/ntpc/tenders/*.csv                 full
  data/raw/ntpc/tenders/raw_html_sample/      60 sample NIT pages
  data/raw/ntpc/documents/                    70 sample PDFs + full index
  data/raw/iocl/tenders/*.csv + source PDFs   full
  data/raw/iocl/tenders/raw_html_sample/      50 sample tender pages
  data/raw/oil_india/tenders/*.csv            full
  data/raw/oil_india/tenders/raw_html_sample/ 60 sample detail pages
  data/raw/oil_india/documents/               full (small)
  data/processed/extracted_items/*.csv        full
  data/processed/extracted_items/ntpc_text/   full (per-document text)

Everything removed is listed in PRUNED.txt with its size, so the collection can
be reproduced exactly by re-running the harvesters.
"""
import os
import shutil

ROOT = "data"
LOG = "PRUNED.txt"

removed = []


def size_of(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for dp, _, fns in os.walk(path):
        for fn in fns:
            total += os.path.getsize(os.path.join(dp, fn))
    return total


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def keep_sample(src_dir, sample_dir, keep, pattern=None, sort_key=None):
    """Move `keep` files out of src_dir into sample_dir, delete the rest."""
    if not os.path.isdir(src_dir):
        return
    files = sorted(os.listdir(src_dir))
    if pattern:
        files = [f for f in files if pattern(f)]
    if sort_key:
        files.sort(key=sort_key)
    os.makedirs(sample_dir, exist_ok=True)
    for i, fn in enumerate(files):
        src = os.path.join(src_dir, fn)
        dst = os.path.join(sample_dir, fn)
        if i < keep:
            shutil.move(src, dst)
        else:
            sz = os.path.getsize(src)
            os.remove(src)
            removed.append((src, sz))
    try:
        os.rmdir(src_dir)
    except OSError:
        pass


def main():
    # ---- NTPC NIT HTML pages (re-fetchable via detail_url in nit_details.csv)
    keep_sample("data/raw/ntpc/tenders",
                "data/raw/ntpc/tenders/raw_html_sample",
                keep=60,
                pattern=lambda f: f.endswith(".html"))

    # ---- NTPC tender PDFs (re-downloadable via documents_index.csv doc_url)
    keep_sample("data/raw/ntpc/documents",
                "data/raw/ntpc/documents",
                keep=70,
                sort_key=lambda f: os.path.getsize(
                    os.path.join("data/raw/ntpc/documents", f)))

    # ---- IOCL tender HTML pages (re-fetchable via detail_url)
    keep_sample("data/raw/iocl/tenders",
                "data/raw/iocl/tenders/raw_html_sample",
                keep=50,
                pattern=lambda f: f.startswith("tender_") and f.endswith(".html"))

    # ---- OIL India detail HTML pages (re-fetchable via detail_url)
    keep_sample("data/raw/oil_india/tenders/detail_pages",
                "data/raw/oil_india/tenders/raw_html_sample",
                keep=60,
                pattern=lambda f: f.endswith(".html"))

    # ---- empty scratch dirs
    for d in ("data/raw/iocl/documents", "data/raw/bpcl", "data/raw/coal_india",
              "data/raw/gem", "data/raw/ongc", "data/raw/sail",
              "data/raw/datagovin", "data/gold",
              "data/processed/tender_metadata", "data/processed/normalized_items",
              "data/processed/attributes",
              "data/raw/cppp/documents"):
        if os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)

    total = sum(sz for _, sz in removed)
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("# Files removed to stay inside the workspace snapshot budget\n")
        f.write("# All are re-downloadable; the CSVs record the source URLs.\n")
        f.write(f"# Total removed: {human(total)} across {len(removed)} files\n\n")
        for path, sz in removed:
            f.write(f"{human(sz):>10}  {path}\n")

    print(f"removed {len(removed)} files, {human(total)}")
    print(f"data/ is now {human(size_of(ROOT))}")
    print(f"see {LOG}")


if __name__ == "__main__":
    main()
