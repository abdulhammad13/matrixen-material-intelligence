#!/usr/bin/env python3
"""
Recover the NIT document link for every OIL India tender whose detail page is
already saved on disk, without re-fetching anything.

The detail HTML is stored as data/raw/oil_india/tenders/detail_pages/<tender_no>.html,
so the tender number is the filename and the download link is inside the page:

    <a href="/download-tender-document?ten_detail=N2xy...">NIT (1.14 MB)</a>

The links are served by a download route with no file extension, which is why
the first version of the harvester (matching on .pdf/.doc/... ) found none.

Output: data/raw/oil_india/tenders/nit_documents_index.csv
"""
import csv
import glob
import os
import re

from bs4 import BeautifulSoup

SRC = "data/raw/oil_india/tenders/detail_pages"
SAMPLE = "data/raw/oil_india/tenders/raw_html_sample"
OUT = "data/raw/oil_india/tenders/nit_documents_index.csv"
B = "https://www.oil-india.com"

COLS = ["tender_no", "doc_label", "doc_size_text", "doc_url", "local_html"]


def parse(path):
    tender_no = os.path.basename(path)[:-5]  # strip .html
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            soup = BeautifulSoup(f.read(), "lxml")
    except Exception as e:
        return {"tender_no": tender_no, "doc_label": "", "doc_size_text": "",
                "doc_url": "", "local_html": path, "error": repr(e)}

    label = size_text = url = ""
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if len(trs) < 2:
            continue
        hdr = [re.sub(r"\s+", " ", c.get_text(" ", strip=True))
               for c in trs[0].find_all(["th", "td"])]
        if "Title" not in hdr or "Tender Doc" not in hdr:
            continue
        for a in trs[1].find_all("a", href=True):
            txt = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
            href = a["href"]
            if href.startswith("/"):
                href = B + href
            # "NIT" must be a whole token: a plain substring test also matches
            # words like "boundary" and would mislabel a title link as the NIT.
            if ("download-tender-document" in href
                    or re.search(r"\.(pdf|docx?|xlsx?|zip|rar)$", href, re.I)
                    or re.search(r"\bNIT\b", txt)):
                label = txt
                m = re.search(r"\(([\d\.]+\s*[KMGT]?B)\)", txt)
                size_text = m.group(1) if m else ""
                url = href
                break
        break
    return {"tender_no": tender_no, "doc_label": label,
            "doc_size_text": size_text, "doc_url": url, "local_html": path}


def main():
    paths = sorted(glob.glob(os.path.join(SRC, "*.html")))
    paths += sorted(glob.glob(os.path.join(SAMPLE, "*.html")))
    print(f"saved detail pages: {len(paths)}", flush=True)

    rows = [parse(p) for p in paths]
    with_url = [r for r in rows if r["doc_url"]]

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print(f"rows written        : {len(rows)} -> {OUT}")
    print(f"with a NIT link     : {len(with_url)} "
          f"({100.0 * len(with_url) / max(len(rows), 1):.1f}%)")
    sizes = []
    for r in with_url:
        m = re.match(r"([\d\.]+)\s*([KMGT]?)B", r["doc_size_text"] or "")
        if m:
            v = float(m.group(1))
            v *= {"": 1, "K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12}[m.group(2)]
            sizes.append(v)
    if sizes:
        print(f"advertised NIT size : {sum(sizes) / 1e6:.0f} MB total "
              f"across {len(sizes)} documents")


if __name__ == "__main__":
    main()
