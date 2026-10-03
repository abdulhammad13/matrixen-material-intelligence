#!/usr/bin/env python3
"""
NTPC e-tender portal harvester (https://ntpctender.ntpc.co.in)

Collects, for the SIH 26099 material-code harmonisation problem:
  * tender/NIT listing rows (ref no, title, source of NIT, closing date)
  * full NIT detail metadata (state, region, contract classification, EMD, dates, contacts)
  * corrigendum document inventory via the portal's own JSON API (/NITDetails/BindCor)
  * the actual NIT / BOQ PDF documents

Everything is written under data/raw/ntpc/. Raw HTML/JSON/PDF is stored untouched.
"""
import concurrent.futures as cf
import csv
import json
import os
import re
import sys
import threading
import time

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
except Exception:  # pragma: no cover
    from requests.packages.urllib3.util.retry import Retry

import urllib3

urllib3.disable_warnings()

BASE = "https://ntpctender.ntpc.co.in"
OUT = "data/raw/ntpc"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

# Material-heavy keywords from the SIH playbook, extended with industrial synonyms.
KEYWORDS = [
    # valves
    "valve", "ball valve", "gate valve", "globe valve", "butterfly valve",
    "check valve", "needle valve", "safety valve", "relief valve",
    "pressure relief valve", "control valve", "plug valve", "diaphragm valve",
    "actuated valve", "valve spares", "valve trim", "valve seat",
    # pipes / fittings / flanges
    "pipe", "pipes", "seamless pipe", "erw pipe", "ms pipe", "cs pipe",
    "ss pipe", "pipe fitting", "pipe fittings", "flange", "flanges",
    "blind flange", "weldolet", "elbow", "tee", "reducer", "stub end",
    "butt weld fitting", "forged fitting", "coupling", "nipple",
    "gasket", "spiral wound gasket", "stud bolt",
    # rotating / static equipment
    "pump", "pumps", "centrifugal pump", "gear pump", "screw pump",
    "diaphragm pump", "dosing pump", "submersible pump", "booster pump",
    "pump spares", "impeller", "mechanical seal", "bearing", "bearings",
    "ball bearing", "roller bearing", "compressor", "compressor spares",
    "blower", "fan", "gearbox", "gear box", "coupling", "shaft",
    "heat exchanger", "condenser", "boiler", "boiler spares", "tube",
    "turbine", "ejector", "strainer", "filter", "filter element",
    # electrical
    "motor", "electric motor", "induction motor", "transformer", "cable",
    "cables", "power cable", "control cable", "switchgear", "breaker",
    "circuit breaker", "relay", "contactor", "battery", "charger",
    "vfd", "starter", "insulator", "lightning arrester", "capacitor",
    # instrumentation
    "instrument", "instruments", "instrumentation", "pressure gauge",
    "pressure transmitter", "temperature sensor", "thermocouple",
    "rtd", "flow meter", "level transmitter", "analyzer", "transmitter",
    "control system", "plc", "dcs", "gauge", "sensor", "orifice",
    # materials / consumables
    "carbon steel", "stainless steel", "alloy steel", "steel plate",
    "structural steel", "electrode", "welding", "paint", "lubricant",
    "oil", "grease", "chemical", "refractory", "insulation", "belt",
    "conveyor", "conveyor belt", "idler", "crusher", "screen",
    # generic spares
    "spares", "spare parts", "mechanical spares", "electrical spares",
    "miscellaneous spares", "consumables", "tools", "o-ring", "seal kit",
]

SESSION_LOCK = threading.Lock()
_local = threading.local()


def session():
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        s.verify = False
        s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
                          "Referer": BASE + "/"})
        retry = Retry(total=4, backoff_factor=1.2,
                      status_forcelist=[429, 500, 502, 503, 504],
                      allowed_methods=frozenset(["GET", "POST"]))
        ad = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
        s.mount("https://", ad)
        s.mount("http://", ad)
        _local.s = s
    return s


def get(url, timeout=60, tries=4, **kw):
    last = None
    for i in range(tries):
        try:
            r = session().get(url, timeout=timeout, **kw)
            if r.status_code == 200 and r.content:
                return r
            last = f"HTTP {r.status_code}"
        except Exception as e:
            last = repr(e)
        time.sleep(1.5 * (i + 1))
    print(f"  ! GET failed {url} :: {last}", file=sys.stderr)
    return None


def post(url, data=None, timeout=60, tries=4):
    last = None
    for i in range(tries):
        try:
            r = session().post(url, data=data, timeout=timeout)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
        except Exception as e:
            last = repr(e)
        time.sleep(1.5 * (i + 1))
    print(f"  ! POST failed {url} :: {last}", file=sys.stderr)
    return None


# ---------------------------------------------------------------- listing ---
def parse_listing(html):
    """Return list of dicts parsed out of the tender listing table."""
    soup = BeautifulSoup(html, "lxml")
    out, seen = [], set()
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if len(trs) < 2:
            continue
        header = [c.get_text(" ", strip=True) for c in trs[0].find_all(["th", "td"])]
        if not any("Tender" in h or "NIT" in h for h in header):
            continue
        for tr in trs[1:]:
            cells = tr.find_all("td")
            if len(cells) < 4:
                continue
            txt = [c.get_text(" ", strip=True) for c in cells]
            link = None
            a = tr.find("a", href=re.compile(r"/NITDetails/NITs/(\d+)"))
            if a:
                link = a["href"]
            nit_id = None
            m = re.search(r"/NITDetails/NITs/(\d+)", link or "")
            if m:
                nit_id = m.group(1)
            key = (txt[1], txt[3])
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "nit_id": nit_id,
                "tender_reference": txt[1],
                "tender_title": txt[3],
                "source_of_nit": txt[4] if len(txt) > 4 else "",
                "closing_date": txt[5] if len(txt) > 5 else "",
                "detail_url": (BASE + link) if link else "",
            })
    return out


def sweep_listing(types, keywords):
    """Sweep listing pages across Type values and Keyword values."""
    records, nit_ids = {}, set()

    def handle(tag, html):
        rows = parse_listing(html)
        new = 0
        for r in rows:
            r["found_via"] = tag
            nid = r["nit_id"]
            k = r["tender_reference"] or r["tender_title"]
            if k not in records:
                records[k] = r
                new += 1
            if nid:
                nit_ids.add(nid)
        return len(rows), new

    # 1. plain listing types (no keyword)
    for t in types:
        url = BASE + "/Index/Search?Type=" + requests.utils.quote(t)
        r = get(url)
        if r is None:
            continue
        tot, new = handle(f"type={t}", r.text)
        print(f"[listing] type={t:36s} rows={tot:4d} new={new}")
        time.sleep(0.4)

    # 2. keyword sweep
    for kw in keywords:
        url = BASE + "/Index/Search?Keyword=" + requests.utils.quote(kw) + "&Type=Live%20Tenders"
        r = get(url)
        if r is None:
            continue
        tot, new = handle(f"keyword={kw}", r.text)
        if tot:
            print(f"[listing] keyword={kw:26s} rows={tot:4d} new={new}")
        time.sleep(0.3)

    return records, nit_ids


# ----------------------------------------------------------------- detail ---
FIELD_MAP = [
    ("Source of NIT", "source_of_nit"),
    ("State", "state"),
    ("Region", "region"),
    ("NIT No.", "nit_no"),
    ("Brief NIT Description", "brief_description"),
    ("Contracts Classification", "contract_classification"),
    ("EMD Cost", "emd_cost"),
    ("Tender Cost", "tender_cost"),
    ("Estimated Fee", "estimated_fee"),
    ("Date Of Issue of NIT", "nit_issue_date"),
    ("Document Sale Start Date", "doc_sale_start"),
    ("Closing Date", "closing_date"),
    ("Bid Submission End Date", "bid_submission_end"),
    ("Bid Opening Date", "bid_opening_date"),
    ("Contact Person", "contact_person"),
    ("Contact Information", "contact_information"),
]


def parse_detail(html, nit_id):
    soup = BeautifulSoup(html, "lxml")
    rec = {"nit_id": nit_id}
    ths = soup.find_all("th")
    for th in ths:
        label = th.get_text(" ", strip=True).rstrip(":").strip()
        for pretty, field in FIELD_MAP:
            if label.lower() == pretty.lower():
                td = th.find_next_sibling("td")
                rec[field] = td.get_text(" ", strip=True) if td else ""
                break
    # documents
    docs = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"\.(pdf|xls|xlsx|doc|docx|zip|rar)$", href, re.I) or "/Uploads/" in href:
            docs.append({
                "nit_id": nit_id,
                "doc_name": a.get_text(" ", strip=True) or os.path.basename(href),
                "doc_url": href if href.startswith("http") else BASE + href,
                "doc_type": "nit_document",
            })
    return rec, docs


def bind_cor(nit_id):
    """Corrigendum docs via the portal's own AJAX JSON endpoint."""
    r = post(BASE + "/NITDetails/BindCor", data={"id": nit_id})
    if r is None:
        return []
    try:
        payload = r.json()
    except Exception:
        try:
            payload = json.loads(r.text)
        except Exception:
            return []
    docs = []
    for d in payload if isinstance(payload, list) else []:
        fp = d.get("File_Path1")
        if not fp:
            fp = f"/Uploads/cor_{d.get('NIT_id')}.html"
        docs.append({
            "nit_id": nit_id,
            "cor_number": d.get("Cor_Number"),
            "doc_name": d.get("FileName"),
            "doc_url": fp if str(fp).startswith("http") else BASE + str(fp),
            "doc_type": "corrigendum",
            "cor_pub_date": d.get("cor_pub_date"),
        })
    return docs


def fetch_detail(nit_id):
    r = get(f"{BASE}/NITDetails/NITs/{nit_id}", timeout=70)
    if r is None:
        return None
    rec, docs = parse_detail(r.text, nit_id)
    if not rec.get("nit_no") and not rec.get("brief_description"):
        return None
    rec["detail_url"] = f"{BASE}/NITDetails/NITs/{nit_id}"
    docs.extend(bind_cor(nit_id))
    raw = os.path.join(OUT, "tenders", f"nit_{nit_id}.html")
    with open(raw, "w", encoding="utf-8", errors="ignore") as f:
        f.write(r.text)
    return rec, docs


# ---------------------------------------------------------------- download --
def download_doc(doc):
    url = doc["doc_url"]
    name = re.sub(r"[^\w\.\-]+", "_", (doc.get("doc_name") or os.path.basename(url)))[:90]
    ext = os.path.splitext(url.split("?")[0])[1] or ".bin"
    if not name.lower().endswith(ext.lower()):
        name += ext
    path = os.path.join(OUT, "documents", f"{doc['nit_id']}_{name}")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    r = get(url, timeout=120)
    if r is None:
        return None
    with open(path, "wb") as f:
        f.write(r.content)
    doc["local_path"] = path
    doc["bytes"] = len(r.content)
    return path


# --------------------------------------------------------------------- main --
def main():
    os.makedirs(os.path.join(OUT, "tenders"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "documents"), exist_ok=True)

    print("=" * 70)
    print("STAGE 1  listing sweep (types + keywords)")
    records, nit_ids = sweep_listing(["Live Tenders", "Corrigendum", "Future NIT",
                                      "Award Details", "Archives"], KEYWORDS)
    print(f"  distinct listing rows : {len(records)}")
    print(f"  distinct NIT ids      : {len(nit_ids)}")

    with open(os.path.join(OUT, "tenders", "listing_rows.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["nit_id", "tender_reference", "tender_title",
                                          "source_of_nit", "closing_date",
                                          "detail_url", "found_via"])
        w.writeheader()
        w.writerows(records.values())

    print("=" * 70)
    print("STAGE 2  NIT detail metadata + corrigendum JSON")
    details, docs = {}, []
    ids = sorted(nit_ids, key=lambda x: int(x))
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for i, res in enumerate(ex.map(fetch_detail, ids), 1):
            if res:
                rec, d = res
                details[rec["nit_id"]] = rec
                docs.extend(d)
            if i % 25 == 0:
                print(f"  ...{i}/{len(ids)} details  (ok={len(details)}, docs={len(docs)})")
    print(f"  details ok : {len(details)} / {len(ids)}")
    print(f"  documents  : {len(docs)}")

    if details:
        cols = ["nit_id", "nit_no", "brief_description", "source_of_nit", "state",
                "region", "contract_classification", "emd_cost", "tender_cost",
                "estimated_fee", "nit_issue_date", "doc_sale_start", "closing_date",
                "bid_submission_end", "bid_opening_date", "contact_person",
                "contact_information", "detail_url"]
        with open(os.path.join(OUT, "tenders", "nit_details.csv"), "w", newline="",
                  encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(details.values())

    if docs:
        with open(os.path.join(OUT, "tenders", "documents_index.csv"), "w", newline="",
                  encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["nit_id", "doc_type", "doc_name",
                                              "doc_url", "cor_number", "cor_pub_date",
                                              "local_path", "bytes"], extrasaction="ignore")
            w.writeheader()
            w.writerows(docs)

    # id-range crawl to pick up archived/closed NITs the listing no longer shows
    print("=" * 70)
    print("STAGE 3  NIT id-range crawl (archived NITs)")
    if ids:
        lo, hi = int(ids[0]), int(ids[-1])
    else:
        lo, hi = 29000, 30300
    lo = max(1, lo - 900)
    hi = hi + 60
    print(f"  range {lo}..{hi}")
    todo = [str(x) for x in range(lo, hi + 1) if str(x) not in details]
    extra = 0
    with cf.ThreadPoolExecutor(max_workers=10) as ex:
        for i, res in enumerate(ex.map(fetch_detail, todo), 1):
            if res:
                rec, d = res
                details[rec["nit_id"]] = rec
                docs.extend(d)
                extra += 1
            if i % 200 == 0:
                print(f"  ...{i}/{len(todo)} probed  (extra={extra})")
    print(f"  extra NITs recovered : {extra}  (total {len(details)})")

    cols = ["nit_id", "nit_no", "brief_description", "source_of_nit", "state",
            "region", "contract_classification", "emd_cost", "tender_cost",
            "estimated_fee", "nit_issue_date", "doc_sale_start", "closing_date",
            "bid_submission_end", "bid_opening_date", "contact_person",
            "contact_information", "detail_url"]
    with open(os.path.join(OUT, "tenders", "nit_details.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(details.values(), key=lambda r: int(r["nit_id"])))
    with open(os.path.join(OUT, "tenders", "documents_index.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["nit_id", "doc_type", "doc_name", "doc_url",
                                          "cor_number", "cor_pub_date", "local_path",
                                          "bytes"], extrasaction="ignore")
        w.writeheader()
        w.writerows(docs)

    print("=" * 70)
    print("STAGE 4  document download (NIT / BOQ / corrigendum PDFs)")
    uniq = {}
    for d in docs:
        uniq[d["doc_url"]] = d
    todo = list(uniq.values())
    print(f"  unique documents to fetch : {len(todo)}")
    ok = 0
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for i, path in enumerate(ex.map(download_doc, todo), 1):
            if path:
                ok += 1
            if i % 100 == 0:
                print(f"  ...{i}/{len(todo)} downloaded={ok}")
    print(f"  documents downloaded : {ok}/{len(todo)}")
    with open(os.path.join(OUT, "tenders", "documents_index.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["nit_id", "doc_type", "doc_name", "doc_url",
                                          "cor_number", "cor_pub_date", "local_path",
                                          "bytes"], extrasaction="ignore")
        w.writeheader()
        w.writerows(docs)

    print("=" * 70)
    print(f"DONE  NITs={len(details)}  docs_indexed={len(docs)}  docs_downloaded={ok}")


if __name__ == "__main__":
    main()
