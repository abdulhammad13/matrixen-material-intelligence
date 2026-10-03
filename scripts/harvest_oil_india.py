#!/usr/bin/env python3
"""
Oil India Limited portal harvester (https://www.oil-india.com)  [Drupal]

Written to run inside a small (2 GB) sandbox: low concurrency, incremental CSV
writes, and a checkpoint file so an interrupted run resumes where it stopped.

Usage
  python3 scripts/harvest_oil_india.py live      # live + archive + corrigendum + EoI
  python3 scripts/harvest_oil_india.py old       # 13k historical tenders (resumable)
  python3 scripts/harvest_oil_india.py details   # detail pages + NIT downloads
"""
import csv
import json
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings()

B = "https://www.oil-india.com"
OUT = "data/raw/oil_india"
TDIR = os.path.join(OUT, "tenders")
DDIR = os.path.join(OUT, "documents")
CKPT = os.path.join(OUT, "checkpoint.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

CATEGORIES = {
    "63": "National Tenders",
    "64": "Global Tenders",
    "65": "Limited Tenders",
    "124": "GeM Tenders",
    "265": "Micro and Small Enterprises (MSEs)",
}

S = requests.Session()
S.verify = False
S.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})


def get(url, timeout=60, tries=4):
    last = None
    for i in range(tries):
        try:
            r = S.get(url, timeout=timeout)
            if r.status_code == 200 and r.content:
                return r
            last = f"HTTP {r.status_code}"
        except Exception as e:
            last = repr(e)
        time.sleep(1.0 * (i + 1))
    print(f"  ! GET failed {url[:110]} :: {last}", file=sys.stderr, flush=True)
    return None


def _clean(x):
    return re.sub(r"\s+", " ", x or "").strip()


def load_ckpt():
    if os.path.exists(CKPT):
        with open(CKPT) as f:
            return json.load(f)
    return {}


def save_ckpt(d):
    with open(CKPT, "w") as f:
        json.dump(d, f)


# ------------------------------------------------------------------ parsers --
def parse_tender_table(html):
    soup = BeautifulSoup(html, "lxml")
    out = []
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if len(trs) < 2:
            continue
        hdr = [_clean(c.get_text(" ", strip=True)) for c in trs[0].find_all(["th", "td"])]
        if "Tender No" not in hdr:
            continue
        for tr in trs[1:]:
            cells = [_clean(c.get_text(" ", strip=True)) for c in tr.find_all("td")]
            if len(cells) < 3:
                continue
            link = ""
            a = tr.find("a", href=re.compile(r"tender-details"))
            if a:
                link = a["href"]
                if link.startswith("/"):
                    link = B + link
            out.append({"sr_no": cells[0], "tender_no": cells[1],
                        "tender_title": cells[2],
                        "location": cells[3] if len(cells) > 3 else "",
                        "pre_bid_date": cells[4] if len(cells) > 4 else "",
                        "bid_closing_date": cells[5] if len(cells) > 5 else "",
                        "bid_opening_date": cells[6] if len(cells) > 6 else "",
                        "detail_url": link})
    return out


def parse_old_table(html):
    """Sr.No | Tender No | Title | Tender Category | Post Date | Details"""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if len(trs) < 2:
            continue
        hdr = [_clean(c.get_text(" ", strip=True)) for c in trs[0].find_all(["th", "td"])]
        if "Tender No" not in hdr or "Tender Category" not in hdr:
            continue
        for tr in trs[1:]:
            cells = [_clean(c.get_text(" ", strip=True)) for c in tr.find_all("td")]
            if len(cells) < 4:
                continue
            title = cells[2]
            m = re.match(r"^(.*?\.{3})\s*(.+)$", title)
            full = m.group(2) if m else title
            link = ""
            for a in tr.find_all("a", href=True):
                if re.search(r"\.(pdf|doc|docx|xls|xlsx|zip|rar)$", a["href"], re.I):
                    link = a["href"] if a["href"].startswith("http") else B + a["href"]
                    break
            out.append({"sr_no": cells[0], "tender_no": cells[1],
                        "tender_title": full,
                        "tender_title_as_rendered": title,
                        "tender_category": cells[3] if len(cells) > 3 else "",
                        "post_date": cells[4] if len(cells) > 4 else "",
                        "document_url": link})
    return out


def parse_corrigendum(html):
    soup = BeautifulSoup(html, "lxml")
    out = []
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if len(trs) < 2:
            continue
        hdr = [_clean(c.get_text(" ", strip=True)) for c in trs[0].find_all(["th", "td"])]
        if "Tender No" not in hdr:
            continue
        for tr in trs[1:]:
            cells = [_clean(c.get_text(" ", strip=True)) for c in tr.find_all("td")]
            if len(cells) < 3:
                continue
            doc = ""
            for a in tr.find_all("a", href=True):
                if re.search(r"\.(pdf|doc|docx|xls|xlsx|zip|rar)$", a["href"], re.I):
                    doc = a["href"] if a["href"].startswith("http") else B + a["href"]
                    break
            out.append({"tender_no": cells[1], "tender_title": cells[2],
                        "document_type": cells[3] if len(cells) > 3 else "",
                        "published": cells[4] if len(cells) > 4 else "",
                        "document_url": doc})
    return out


def parse_generic(html, label, src_url):
    """EoI / pre-bid meeting style tables -> generic cols|values rows."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if len(trs) < 2:
            continue
        hdr = [_clean(c.get_text(" ", strip=True)) for c in trs[0].find_all(["th", "td"])]
        if "Sr. No." not in hdr:
            continue
        for tr in trs[1:]:
            cells = [_clean(c.get_text(" ", strip=True)) for c in tr.find_all("td")]
            if len(cells) < 2:
                continue
            doc = ""
            for a in tr.find_all("a", href=True):
                href = a["href"]
                if href.startswith("/"):
                    href = B + href
                if re.search(r"\.(pdf|doc|docx|xls|xlsx|zip|rar)$", href, re.I):
                    doc = href
                    break
            out.append({"source_section": label, "cols": " | ".join(hdr),
                        "values": " | ".join(cells), "document_url": doc,
                        "source_url": src_url})
    return out


# -------------------------------------------------------------------- write --
def append_csv(path, rows, cols):
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


LIVE_COLS = ["category", "source_section", "sr_no", "tender_no", "tender_title",
             "location", "pre_bid_date", "bid_closing_date", "bid_opening_date",
             "list_page", "source_url", "detail_url"]
OLD_COLS = ["sr_no", "tender_no", "tender_title", "tender_title_as_rendered",
            "tender_category", "post_date", "document_url", "list_page", "source_url"]
CORR_COLS = ["category", "source_section", "tender_no", "tender_title",
             "document_type", "published", "document_url"]
GEN_COLS = ["source_section", "cols", "values", "document_url", "source_url"]


# --------------------------------------------------------------- stage: live --
def cmd_live():
    os.makedirs(TDIR, exist_ok=True)
    live_path = os.path.join(TDIR, "live_tenders.csv")
    arch_path = os.path.join(TDIR, "archive_tenders.csv")
    corr_path = os.path.join(TDIR, "corrigenda.csv")
    gen_path = os.path.join(TDIR, "eoi_and_meetings.csv")
    for p in (live_path, arch_path, corr_path, gen_path):
        if os.path.exists(p):
            os.remove(p)

    print("STAGE live listings", flush=True)
    tot = 0
    for cid, label in CATEGORIES.items():
        page, n, seen_no = 0, 0, set()
        while True:
            url = f"{B}/tender-list/{cid}" + (f"?page={page}&op=" if page else "")
            r = get(url)
            if r is None:
                break
            got = parse_tender_table(r.text)
            if not got:
                break
            for g in got:
                g.update({"source_section": f"live:{label}", "category": cid,
                          "list_page": page, "source_url": url})
            append_csv(live_path, got, LIVE_COLS)
            n += len(got)
            fresh = [g for g in got if g["tender_no"] not in seen_no]
            if not fresh:
                print(f"  live:{label} page {page} no new tender_no -> stopping",
                      flush=True)
                break
            seen_no.update(g["tender_no"] for g in got)
            page += 1
            if page > 200:
                break
            time.sleep(0.12)
        print(f"  live:{label} = {n}", flush=True)
        tot += n

    print("STAGE archive listings", flush=True)
    for cid, label in CATEGORIES.items():
        page, n, seen_no = 0, 0, set()
        while True:
            url = f"{B}/archive-tender-data/{cid}" + (f"?page={page}&op=" if page else "")
            r = get(url)
            if r is None:
                break
            got = parse_tender_table(r.text)
            if not got:
                break
            for g in got:
                g.update({"source_section": f"archive:{label}", "category": cid,
                          "list_page": page, "source_url": url})
            append_csv(arch_path, got, LIVE_COLS)
            n += len(got)
            # Drupal's pager on this view keeps returning rows past the end of
            # the result set (it loops), so stop as soon as a page yields no
            # tender_no we have not already seen.
            fresh = [g for g in got if g["tender_no"] not in seen_no]
            if not fresh:
                print(f"  archive:{label} page {page} returned no new tender_no "
                      f"-> pager exhausted, stopping", flush=True)
                break
            seen_no.update(g["tender_no"] for g in got)
            page += 1
            if page > 3000:
                break
            time.sleep(0.12)
        print(f"  archive:{label} = {n}", flush=True)
        tot += n

    print("STAGE corrigenda", flush=True)
    for cid, label in CATEGORIES.items():
        for page in range(0, 40):
            url = f"{B}/corrigendum-tender/{cid}" + (f"?page={page}&op=" if page else "")
            r = get(url)
            if r is None:
                break
            got = parse_corrigendum(r.text)
            if not got:
                break
            for g in got:
                g.update({"source_section": f"corrigendum:{label}", "category": cid})
            append_csv(corr_path, got, CORR_COLS)
            time.sleep(0.1)

    print("STAGE eoi / pre-bid meetings", flush=True)
    for path, label in [("/expressions-interest-list", "eoi"),
                        ("/pretender-meeting-list", "pretender_meeting")]:
        for page in range(0, 40):
            url = B + path + (f"?page={page}&op=" if page else "")
            r = get(url)
            if r is None:
                break
            got = parse_generic(r.text, label, url)
            if not got:
                break
            append_csv(gen_path, got, GEN_COLS)
            time.sleep(0.1)
    print(f"DONE live/archive total = {tot}", flush=True)


# ---------------------------------------------------------------- stage: old --
def cmd_old():
    os.makedirs(TDIR, exist_ok=True)
    path = os.path.join(TDIR, "old_tenders.csv")
    ck = load_ckpt()
    start = ck.get("old_page", 0)

    first = get(B + "/old-tender")
    if first is None:
        return
    soup = BeautifulSoup(first.text, "lxml")
    el = soup.find(attrs={"data-total": True})
    total = int(el["data-total"]) if el else 0
    n_pages = (total + 9) // 10
    cap = int(os.environ.get("OIL_OLD_PAGES", "0")) or n_pages
    n_pages = min(n_pages, cap)
    print(f"old-tender total={total} pages={n_pages} resuming at page {start}",
          flush=True)

    rows, written = [], 0
    seen_no = set()
    empty = 0
    # If old_tenders.csv already exists (a resumed run) seed the seen-set so we
    # do not append rows we already have.
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            seen_no = {r["tender_no"] for r in csv.DictReader(f)}
        print(f"  {len(seen_no)} tender_no already on disk", flush=True)

    stale_streak = 0
    for p in range(start, n_pages):
        url = B + "/old-tender" + (f"?page={p}&op=" if p else "")
        r = get(url)
        if r is None:
            print(f"  stopping at page {p} (fetch failed)", flush=True)
            break
        got = parse_old_table(r.text)
        if not got:
            # A single blank page is a transient portal glitch, not the end of
            # the result set (verified: page 378 is empty but 379..1311 have
            # data), so only give up after several consecutive blanks.
            empty += 1
            if empty >= 5:
                print(f"  stopping at page {p}: {empty} consecutive empty pages",
                      flush=True)
                break
            print(f"  page {p} empty (transient), continuing", flush=True)
            time.sleep(0.5)
            continue
        empty = 0
        # pager loop guard. On a resumed run the early pages are legitimately
        # all duplicates, so a long streak is tolerated; only a very long run
        # of no-new-rows pages is treated as the pager looping.
        fresh = [g for g in got if g["tender_no"] not in seen_no]
        if not fresh:
            stale_streak += 1
            if stale_streak >= 60:
                print(f"  stopping at page {p}: {stale_streak} consecutive pages "
                      f"with no new tender_no (pager looping)", flush=True)
                break
            continue
        stale_streak = 0
        seen_no.update(g["tender_no"] for g in got)
        for g in got:
            g["list_page"] = p
            g["source_url"] = url
        rows.extend(fresh)
        if len(rows) >= 200:
            append_csv(path, rows, OLD_COLS)
            written += len(rows)
            rows = []
            ck["old_page"] = p + 1
            save_ckpt(ck)
        if p % 100 == 0:
            print(f"  ...page {p}/{n_pages} written={written}", flush=True)
        time.sleep(0.1)
    if rows:
        append_csv(path, rows, OLD_COLS)
        written += len(rows)
        ck["old_page"] = n_pages
        save_ckpt(ck)
    print(f"DONE old-tender rows written this run = {written}", flush=True)


# ------------------------------------------------------------ stage: details --
DETAIL_HDR = ["tender_no", "tender_title", "source_section", "category",
              "location_office", "published", "pre_bid_date_if_any",
              "bid_closing_date_time", "bid_opening_date_time", "tender_doc",
              "nit_doc_url", "nit_doc_label", "nit_content_type",
              "nit_local_path", "nit_bytes",
              "detail_url"]


def fetch_detail(row):
    url = row.get("detail_url")
    if not url:
        return None
    r = get(url, timeout=80)
    if r is None:
        return None
    soup = BeautifulSoup(r.text, "lxml")
    rec = {"tender_no": row.get("tender_no", ""),
           "tender_title": row.get("tender_title", ""),
           "source_section": row.get("source_section", ""),
           "category": row.get("category", ""),
           "detail_url": url}
    txt = _clean(soup.get_text(" ", strip=True))
    m = re.search(r"Tender No\s*:\s*(\S+)", txt)
    if m:
        rec["tender_no"] = m.group(1)
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if len(trs) < 2:
            continue
        hdr = [_clean(c.get_text(" ", strip=True)) for c in trs[0].find_all(["th", "td"])]
        if "Title" in hdr and "Tender Doc" in hdr:
            vals = [_clean(c.get_text(" ", strip=True)) for c in trs[1].find_all("td")]
            for i, h in enumerate(hdr):
                if i < len(vals):
                    rec[re.sub(r"[^a-z0-9]+", "_", h.lower()).strip("_")] = vals[i]
            for a in trs[1].find_all("a", href=True):
                href = a["href"]
                if href.startswith("/"):
                    href = B + href
                # NIT links are served by a download route with no file
                # extension, e.g. /download-tender-document?ten_detail=N2xy...
                if re.search(r"\.(pdf|doc|docx|xls|xlsx|zip|rar)$", href, re.I) \
                        or "/files/" in href \
                        or "download-tender-document" in href \
                        or "download" in a.get_text(" ", strip=True).lower() \
                        or "NIT" in a.get_text(" ", strip=True):
                    rec["nit_doc_url"] = href
                    rec["nit_doc_label"] = _clean(a.get_text(" ", strip=True))
                    break
            break
    raw = os.path.join(TDIR, "detail_pages")
    os.makedirs(raw, exist_ok=True)
    key = re.sub(r"[^\w\.\-]+", "_", rec.get("tender_no") or "x")[:60]
    with open(os.path.join(raw, f"{key}.html"), "w", encoding="utf-8",
              errors="ignore") as f:
        f.write(r.text)
    return rec


EXT_BY_CTYPE = {
    "application/pdf": ".pdf",
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/x-rar-compressed": ".rar",
    "application/octet-stream": ".bin",
}


def download_nit(rec):
    """Download the NIT document.

    The URL is a download route with no extension, so the file type is taken
    from the response Content-Type rather than guessed from the URL.
    """
    url = rec.get("nit_doc_url")
    if not url:
        return rec
    import urllib.parse
    key = re.sub(r"[^\w\.\-]+", "_", rec.get("tender_no") or "x")[:60]
    os.makedirs(DDIR, exist_ok=True)

    existing = [p for p in os.listdir(DDIR) if p.startswith(key + ".")]
    if existing:
        path = os.path.join(DDIR, existing[0])
        if os.path.getsize(path) > 0:
            rec["nit_local_path"], rec["nit_bytes"] = path, os.path.getsize(path)
            return rec

    r = get(url, timeout=150)
    if r is None or not r.content:
        return rec
    ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    ext = EXT_BY_CTYPE.get(ctype)
    if not ext:
        head = r.content[:5]
        if head.startswith(b"%PDF"):
            ext = ".pdf"
        elif head.startswith(b"PK"):
            ext = ".zip"
        elif head.startswith(b"Rar!"):
            ext = ".rar"
        elif head.startswith(b"\xd0\xcf\x11\xe0"):
            ext = ".doc"
        else:
            ext = os.path.splitext(urllib.parse.urlparse(url).path)[1] or ".bin"
    rec["nit_content_type"] = ctype
    path = os.path.join(DDIR, f"{key}{ext}")
    with open(path, "wb") as f:
        f.write(r.content)
    rec["nit_local_path"], rec["nit_bytes"] = path, len(r.content)
    return rec


def cmd_details():
    import csv as _csv
    rows = []
    for fn in ("live_tenders.csv", "archive_tenders.csv"):
        p = os.path.join(TDIR, fn)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                rows += [r for r in _csv.DictReader(f) if r.get("detail_url")]
    uniq = {}
    for r in rows:
        uniq[r["detail_url"]] = r
    todo = list(uniq.values())
    print(f"detail pages to fetch = {len(todo)}", flush=True)

    out = os.path.join(TDIR, "tender_details.csv")
    done, n = [], 0
    for r in todo:
        rec = fetch_detail(r)
        if rec:
            download_nit(rec)
            done.append(rec)
        n += 1
        if n % 25 == 0:
            print(f"  ...{n}/{len(todo)} ok={len(done)}", flush=True)
        time.sleep(0.08)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=DETAIL_HDR, extrasaction="ignore")
        w.writeheader()
        w.writerows(done)
    print(f"DONE details={len(done)} nits={sum(1 for d in done if d.get('nit_local_path'))}",
          flush=True)


def cmd_rest():
    """Archive categories after the first, plus corrigenda and EoI sections.

    `live` already covered the live listings and archive:National; this resumes
    the remainder without re-fetching (or re-looping) what is already on disk.
    """
    os.makedirs(TDIR, exist_ok=True)
    arch_path = os.path.join(TDIR, "archive_tenders.csv")
    corr_path = os.path.join(TDIR, "corrigenda.csv")
    gen_path = os.path.join(TDIR, "eoi_and_meetings.csv")
    for p in (corr_path, gen_path):
        if os.path.exists(p):
            os.remove(p)

    done_cats = set()
    if os.path.exists(arch_path):
        with open(arch_path, encoding="utf-8") as f:
            done_cats = {r["category"] for r in csv.DictReader(f)}
    print(f"archive categories already on disk: {sorted(done_cats)}", flush=True)

    for cid, label in CATEGORIES.items():
        if cid in done_cats:
            print(f"  skipping archive:{label} (already collected)", flush=True)
            continue
        page, n, seen_no = 0, 0, set()
        while True:
            url = f"{B}/archive-tender-data/{cid}" + (f"?page={page}&op=" if page else "")
            r = get(url)
            if r is None:
                break
            got = parse_tender_table(r.text)
            if not got:
                break
            for g in got:
                g.update({"source_section": f"archive:{label}", "category": cid,
                          "list_page": page, "source_url": url})
            append_csv(arch_path, got, LIVE_COLS)
            n += len(got)
            fresh = [g for g in got if g["tender_no"] not in seen_no]
            if not fresh:
                print(f"  archive:{label} page {page} no new tender_no -> stopping",
                      flush=True)
                break
            seen_no.update(g["tender_no"] for g in got)
            page += 1
            if page > 3000:
                break
            time.sleep(0.12)
        print(f"  archive:{label} = {n}", flush=True)

    print("STAGE corrigenda", flush=True)
    for cid, label in CATEGORIES.items():
        n = 0
        for page in range(0, 40):
            url = f"{B}/corrigendum-tender/{cid}" + (f"?page={page}&op=" if page else "")
            r = get(url)
            if r is None:
                break
            got = parse_corrigendum(r.text)
            if not got:
                break
            for g in got:
                g.update({"source_section": f"corrigendum:{label}", "category": cid})
            append_csv(corr_path, got, CORR_COLS)
            n += len(got)
            time.sleep(0.1)
        print(f"  corrigendum:{label} = {n}", flush=True)

    print("STAGE eoi / pre-bid meetings", flush=True)
    for path, label in [("/expressions-interest-list", "eoi"),
                        ("/pretender-meeting-list", "pretender_meeting")]:
        for page in range(0, 40):
            url = B + path + (f"?page={page}&op=" if page else "")
            r = get(url)
            if r is None:
                break
            got = parse_generic(r.text, label, url)
            if not got:
                break
            append_csv(gen_path, got, GEN_COLS)
            time.sleep(0.1)
    print("DONE rest", flush=True)


if __name__ == "__main__":
    os.makedirs(TDIR, exist_ok=True)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "live"
    {"live": cmd_live, "old": cmd_old, "details": cmd_details,
     "rest": cmd_rest}[cmd]()
