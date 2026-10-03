#!/usr/bin/env python3
"""
IOCL e-tender portal harvester (https://iocletenders.nic.in/nicgep/app)

The portal's Home-page "tenderSearch" form is NOT captcha-gated, so it can be
swept by keyword. Every hit yields a detail page carrying full tender metadata
(organisation chain, tender ref, tender ID, product category, location, pincode,
form of contract, tender value, BOQ / cover documents).

Outputs under data/raw/iocl/ :
  tenders/search_rows.csv     - one row per (keyword, tender) listing hit
  tenders/tender_details.csv  - one row per tender, full detail-page metadata
  tenders/documents_index.csv - BOQ / NIT / cover documents per tender
  tenders/tender_<id>.html    - raw detail page (untouched)
  documents/                  - downloaded BOQ xls / NIT rar / pdf
"""
import concurrent.futures as cf
import csv
import html as htmllib
import os
import re
import sys
import threading
import time
import urllib.parse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3

urllib3.disable_warnings()

BASE = "https://iocletenders.nic.in/nicgep/app"
HOST = "https://iocletenders.nic.in"
OUT = "data/raw/iocl"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

KEYWORDS = [
    "valve", "valves", "ball valve", "gate valve", "globe valve",
    "butterfly valve", "check valve", "control valve", "safety valve",
    "relief valve", "needle valve", "plug valve", "diaphragm valve",
    "on-off valve", "rotary valve", "valve spares", "valve actuator",
    "pipe", "pipes", "seamless pipe", "pipe fitting", "pipe fittings",
    "flange", "flanges", "elbow", "tee", "reducer", "stub end",
    "butt weld", "forged fitting", "gasket", "stud bolt", "fastener",
    "pump", "pumps", "centrifugal pump", "gear pump", "screw pump",
    "dosing pump", "submersible pump", "reciprocating pump", "pump spares",
    "impeller", "mechanical seal", "bearing", "bearings", "ball bearing",
    "roller bearing", "compressor", "compressor spares", "blower", "fan",
    "gearbox", "coupling", "heat exchanger", "air cooler", "condenser",
    "boiler", "boiler spares", "tube", "tubes", "turbine", "ejector",
    "strainer", "filter", "filter element", "separator", "reactor",
    "column", "vessel", "drum", "tank", "heater", "stack",
    "motor", "motors", "electric motor", "transformer", "cable", "cables",
    "power cable", "control cable", "switchgear", "breaker",
    "circuit breaker", "relay", "contactor", "battery", "charger",
    "vfd", "starter", "insulator", "lightning arrester", "capacitor",
    "switchboard", "panel", "genset", "hoist",
    "instrument", "instruments", "instrumentation", "pressure gauge",
    "transmitter", "pressure transmitter", "temperature sensor",
    "thermocouple", "rtd", "flow meter", "flowmeter", "level transmitter",
    "analyser", "analyzer", "dcs", "plc", "sensor", "orifice",
    "carbon steel", "stainless steel", "alloy steel", "steel plate",
    "structural steel", "electrode", "welding", "paint", "lubricant",
    "grease", "chemical", "catalyst", "refractory", "insulation",
    "conveyor", "belt", "crusher", "screen", "screw conveyor",
    "spares", "spare", "spare parts", "capital spares", "mechanical spares",
    "electrical spares", "consumables", "tools", "o-ring", "seal kit",
    "marine loading arm", "pig launcher", "desalter", "mixer", "agitator",
    "drier", "sample cooler", "mounded bullet", "fire", "safety",
]


# Second pass: high-frequency generic terms. The portal caps each search at 20
# hits (most recent first), so broad terms surface tenders that no single
# material keyword matches.
GENERIC_KEYWORDS = [
    "supply", "supply of", "procurement", "procurement of", "refinery",
    "project", "2026", "2025", "the", "for", "and", "of", "at",
    "erection", "commissioning", "services", "service", "material",
    "materials", "equipment", "package", "make", "lot", "lot-1", "lot-2",
    "lot-3", "spares", "capital", "repair", "overhaul", "maintenance",
    "installation", "testing", "calibration", "upgradation", "revamp",
    "shutdown", "turnaround", "insurance", "critical", "imported",
    "indigenous", "oem", "authorised", "authorized", "agency", "rate",
    "contract", "agreement", "works", "civil", "mechanical", "electrical",
    "instrumentation", "chemical", "catalyst", "polymer", "lube",
    "digboi", "paradip", "panipat", "mathura", "barauni", "guwahati",
    "haldia", "koyali", "bongaigaon", "numaligarh", "bathinda", "chandigarh",
    "refineries hq", "marketing", "pipeline", "rnd", "construction",
]

_local = threading.local()


def session():
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        s.verify = False
        s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
        retry = Retry(total=3, backoff_factor=1.5,
                      status_forcelist=[429, 500, 502, 503, 504],
                      allowed_methods=frozenset(["GET", "POST"]))
        ad = HTTPAdapter(max_retries=retry, pool_connections=6, pool_maxsize=6)
        s.mount("https://", ad)
        s.mount("http://", ad)
        _local.s = s
    return s


def get(url, timeout=90, tries=3, **kw):
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
    print(f"  ! GET failed {url[:110]} :: {last}", file=sys.stderr)
    return None


# ------------------------------------------------------------- keyword sweep --
def search_keyword(kw):
    """POST the captcha-free Home tenderSearch form. Returns listing rows."""
    r = get(BASE + "?page=Home&service=page", timeout=60)
    if r is None:
        return []
    soup = BeautifulSoup(r.text, "lxml")
    form = soup.find("form", id="tenderSearch")
    if form is None:
        return []
    data = {i.get("name"): (i.get("value") or "")
            for i in form.find_all("input") if i.get("name")}
    data["SearchDescription"] = kw
    data["Go"] = "Go"
    try:
        r2 = session().post(BASE, data=data, timeout=150,
                            headers={"Referer": BASE + "?page=Home&service=page"})
    except Exception as e:
        print(f"  ! search failed {kw} :: {e}", file=sys.stderr)
        return []
    if r2.status_code != 200:
        return []
    rows = []
    s2 = BeautifulSoup(r2.text, "lxml")
    for tr in s2.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        if not re.match(r"^\d+\.?$", tds[0].get_text(strip=True)):
            continue
        cells = [c.get_text(" ", strip=True) for c in tds]
        a = tr.find("a", href=True)
        link = htmllib.unescape(a["href"]) if a else ""
        title = a.get_text(" ", strip=True) if a else ""
        # title cell looks like: [Title][TenderRef][TenderID]
        bracket = re.findall(r"\[([^\]]*)\]", cells[4] if len(cells) > 4 else "")
        rows.append({
            "keyword": kw,
            "epublished_date": cells[1] if len(cells) > 1 else "",
            "closing_date": cells[2] if len(cells) > 2 else "",
            "opening_date": cells[3] if len(cells) > 3 else "",
            "title_raw": title or (cells[4] if len(cells) > 4 else ""),
            "tender_title": bracket[0] if len(bracket) > 0 else "",
            "tender_reference": bracket[1] if len(bracket) > 1 else "",
            "tender_id": bracket[2] if len(bracket) > 2 else "",
            "organisation_chain": cells[5] if len(cells) > 5 else "",
            "detail_url": (HOST + link) if link.startswith("/") else link,
        })
    return rows


# ------------------------------------------------------------------ detail ---
DETAIL_FIELDS = [
    ("Organisation Chain", "organisation_chain"),
    ("Tender Reference Number", "tender_reference"),
    ("Tender ID", "tender_id"),
    ("Tender Type", "tender_type"),
    ("Form Of Contract", "form_of_contract"),
    ("Tender Category", "tender_category"),
    ("No. of Covers", "no_of_covers"),
    ("Payment Mode", "payment_mode"),
    ("EMD Amount in ₹", "emd_amount"),
    ("EMD Fee Type", "emd_fee_type"),
    ("Title", "title"),
    ("Work Description", "work_description"),
    ("NDA/Pre Qualification", "nda_prequalification"),
    ("Tender Value in ₹", "tender_value"),
    ("Product Category", "product_category"),
    ("Sub category", "sub_category"),
    ("Contract Type", "contract_type"),
    ("Bid Validity(Days)", "bid_validity_days"),
    ("Period Of Work(Days)", "period_of_work_days"),
    ("Location", "location"),
    ("Pincode", "pincode"),
    ("Pre Bid Meeting Date", "pre_bid_meeting_date"),
    ("Bid Opening Date", "bid_opening_date"),
    ("Tender Closing Date", "tender_closing_date"),
    ("Tender Publication Date", "tender_publication_date"),
    ("Document Download Start Date", "doc_download_start"),
    ("Document Download End Date", "doc_download_end"),
    ("Tender Fee in ₹", "tender_fee"),
    ("Tender Fee Type", "tender_fee_type"),
    ("Tender Document Fee Exempted", "tender_doc_fee_exempted"),
]


def _norm(s):
    return re.sub(r"[\s\u20b9]+", " ", s or "").replace("\u20b9", "").strip()


def parse_detail(html, kw=None):
    """Detail pages use <td class="td_caption">label</td><td class="td_field">value</td>."""
    soup = BeautifulSoup(html, "lxml")
    rec = {}
    lookup = {p.lower().replace("₹", "").strip(): f for p, f in DETAIL_FIELDS}

    caps = soup.find_all("td", class_="td_caption")
    for cap in caps:
        label = _norm(cap.get_text(" ", strip=True)).rstrip(":").lower()
        field = lookup.get(label)
        if not field:
            continue
        nxt = cap.find_next_sibling("td")
        # skip over non-value cells
        guard = 0
        while nxt is not None and "td_field" not in (nxt.get("class") or []) and guard < 3:
            nxt = nxt.find_next_sibling("td")
            guard += 1
        if nxt is None:
            nxt = cap.find_next("td", class_="td_field")
        rec[field] = _norm(nxt.get_text(" ", strip=True)) if nxt else ""
    docs = []
    for a in soup.find_all("a", href=True):
        href = htmllib.unescape(a["href"])
        nm = a.get_text(" ", strip=True)
        if re.search(r"\.(pdf|xls|xlsx|doc|docx|zip|rar|txt)$", href, re.I):
            docs.append({"doc_name": nm or os.path.basename(href),
                         "doc_url": href if href.startswith("http") else HOST + href,
                         "doc_type": "attachment"})

    # Bid-cover inventory: Cover No | Cover Type | Description | Document Type.
    # The files themselves sit behind bidder login, but the inventory is public
    # and records that a BOQ / technical annexure exists for the tender.
    covers = []
    for tbl in soup.find_all("table", id="packetTableView"):
        for tr in tbl.find_all("tr"):
            cells = [_norm(c.get_text(" ", strip=True)) for c in tr.find_all("td")]
            if len(cells) >= 4 and cells != ["Cover No", "Cover Type", "Description",
                                             "Document Type"]:
                covers.append({"cover_no": cells[0], "cover_type": cells[1],
                               "cover_description": cells[2],
                               "cover_document_type": cells[3]})
    if covers:
        rec["covers"] = " ;; ".join(
            f"[{c['cover_no']}] {c['cover_type']} | {c['cover_description']} "
            f"({c['cover_document_type']})" for c in covers)
        rec["n_covers_listed"] = str(len(covers))
    return rec, docs, covers


def fetch_detail(row):
    if not row.get("detail_url"):
        return None
    r = get(row["detail_url"], timeout=120)
    if r is None:
        return None
    rec, docs, covers = parse_detail(r.text)
    if not rec.get("tender_id") and not rec.get("title"):
        return None
    rec.setdefault("tender_id", row.get("tender_id", ""))
    rec.setdefault("tender_reference", row.get("tender_reference", ""))
    rec.setdefault("organisation_chain", row.get("organisation_chain", ""))
    rec["found_via_keyword"] = row.get("keyword", "")
    rec["detail_url"] = row["detail_url"]
    tid = rec["tender_id"] or rec.get("tender_reference") or "unknown"
    rec["safe_id"] = re.sub(r"[^\w\.\-]+", "_", tid)[:70]
    for d in docs:
        d["tender_id"] = rec["tender_id"]
        d["tender_reference"] = rec["tender_reference"]
    for c in covers:
        c["tender_id"] = rec["tender_id"]
        c["tender_reference"] = rec["tender_reference"]
        c["tender_title"] = rec.get("title", "")
        c["organisation_chain"] = rec.get("organisation_chain", "")
    path = os.path.join(OUT, "tenders", f"tender_{rec['safe_id']}.html")
    try:
        with open(path, "w", encoding="utf-8", errors="ignore") as f:
            f.write(r.text)
    except Exception:
        pass
    return rec, docs, covers


def download_doc(doc):
    url = doc["doc_url"]
    name = re.sub(r"[^\w\.\-]+", "_", doc.get("doc_name") or os.path.basename(url))[:80]
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1] or ".bin"
    if not name.lower().endswith(ext.lower()):
        name += ext
    tid = re.sub(r"[^\w\.\-]+", "_", doc.get("tender_id") or "x")[:40]
    path = os.path.join(OUT, "documents", f"{tid}_{name}")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        doc["local_path"], doc["bytes"] = path, os.path.getsize(path)
        return path
    r = get(url, timeout=180)
    if r is None:
        return None
    with open(path, "wb") as f:
        f.write(r.content)
    doc["local_path"], doc["bytes"] = path, len(r.content)
    return path


# --------------------------------------------------------------------- main --
DETAIL_COLS = ["tender_id", "tender_reference", "title", "work_description",
               "organisation_chain", "product_category", "sub_category",
               "tender_category", "tender_type", "form_of_contract",
               "contract_type", "tender_value", "tender_fee", "emd_amount",
               "location", "pincode", "bid_validity_days", "period_of_work_days",
               "tender_publication_date", "tender_closing_date",
               "bid_opening_date", "doc_download_start", "doc_download_end",
               "no_of_covers", "n_covers_listed", "covers", "payment_mode",
               "nda_prequalification", "found_via_keyword", "detail_url"]


def harvest_shard(kws):
    """Search each keyword AND pull its detail pages inside ONE session.

    The detail URL carries a session-bound `sp=` token, so it is only valid for
    the session that produced it -- and that session must have been warmed by a
    GET of the Home page. Doing search -> detail in the same session is the only
    reliable ordering.
    """
    rows, details, docs, covers = [], [], [], []
    for kw in kws:
        got = search_keyword(kw)
        rows.extend(got)
        if not got:
            continue
        print(f"  kw={kw:24s} hits={len(got):3d}", file=sys.stderr)
        for r in got:
            res = fetch_detail(r)
            if res:
                rec, d, cv = res
                details.append(rec)
                docs.extend(d)
                covers.extend(cv)
        time.sleep(0.2)
    return rows, details, docs, covers


def main():
    os.makedirs(os.path.join(OUT, "tenders"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "documents"), exist_ok=True)

    all_kw = KEYWORDS
    if os.environ.get("IOCL_GENERIC"):
        all_kw = KEYWORDS + GENERIC_KEYWORDS
    n_workers = int(os.environ.get("IOCL_WORKERS", "4"))
    print("=" * 70)
    print(f"STAGE 1+2  keyword sweep + detail fetch "
          f"({n_workers} sessions, {len(all_kw)} keywords)")
    shards = [all_kw[i::n_workers] for i in range(n_workers)]
    rows, details, docs, covers = [], [], [], []
    seen = set()
    with cf.ThreadPoolExecutor(max_workers=n_workers) as ex:
        for sh_rows, sh_det, sh_docs, sh_cov in ex.map(harvest_shard, shards):
            rows.extend(sh_rows)
            for rec in sh_det:
                k = rec.get("tender_id") or rec.get("tender_reference")
                if k and k not in seen:
                    seen.add(k)
                    details.append(rec)
            docs.extend(sh_docs)
            covers.extend(sh_cov)
    print(f"  listing rows total : {len(rows)}")

    with open(os.path.join(OUT, "tenders", "search_rows.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["keyword", "epublished_date", "closing_date",
                                          "opening_date", "tender_title",
                                          "tender_reference", "tender_id",
                                          "organisation_chain", "detail_url",
                                          "title_raw"])
        w.writeheader()
        w.writerows(rows)
    print(f"  listing rows total : {len(rows)}")

    with open(os.path.join(OUT, "tenders", "tender_details.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=DETAIL_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(details)
    if docs:
        with open(os.path.join(OUT, "tenders", "documents_index.csv"), "w", newline="",
                  encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["tender_id", "tender_reference",
                                              "doc_name", "doc_type", "doc_url",
                                              "local_path", "bytes"],
                               extrasaction="ignore")
            w.writeheader()
            w.writerows(docs)

    if covers:
        with open(os.path.join(OUT, "tenders", "bid_covers.csv"), "w", newline="",
                  encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["tender_id", "tender_reference",
                                              "tender_title", "organisation_chain",
                                              "cover_no", "cover_type",
                                              "cover_description",
                                              "cover_document_type"],
                               extrasaction="ignore")
            w.writeheader()
            w.writerows(covers)

    print("=" * 70)
    print("STAGE 3  download tender documents (BOQ / NIT / annexures)")
    uq = {d["doc_url"]: d for d in docs}
    todo = list(uq.values())
    print(f"  unique documents : {len(todo)}")
    ok = 0
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for i, p in enumerate(ex.map(download_doc, todo), 1):
            if p:
                ok += 1
            if i % 25 == 0:
                print(f"  ...{i}/{len(todo)} downloaded={ok}")
    print(f"  downloaded : {ok}/{len(todo)}")

    with open(os.path.join(OUT, "tenders", "documents_index.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["tender_id", "tender_reference", "doc_name",
                                          "doc_type", "doc_url", "local_path", "bytes"],
                           extrasaction="ignore")
        w.writeheader()
        w.writerows(docs)
    print("=" * 70)
    print(f"DONE  tenders={len(details)}  docs={len(docs)}  covers={len(covers)}  downloaded={ok}")


if __name__ == "__main__":
    main()
