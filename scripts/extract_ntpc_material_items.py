#!/usr/bin/env python3
"""
Pull structured material/item lines out of the NTPC NIT text corpus.

The NIT PDFs (many of them GeM-sourced) contain three high-value patterns that
are real, machine-readable material descriptions:

  1. "Item Category" rows        e.g. CABLE, PWR, 240MM2, 1C, STRANDED, AL, 11KV
  2. GeMARPTS "Searched Strings"  the exact GeM catalogue strings the buyer used
  3. GeMARPTS "Searched Result"   the GeM product titles returned
  4. "Schedule N | item | qty"    BOQ-style lines with quantities
  5. comma-delimited spec strings e.g. PIPE:BLK, CORTEN,A423GR1,ERW,2

Output: data/processed/extracted_items/ntpc_material_items.csv
"""
import csv
import glob
import os
import re
import sys

SRC = "data/processed/extracted_items/ntpc_text"
OUT = "data/processed/extracted_items/ntpc_material_items.csv"

CID = re.compile(r"\(cid:\d+\)")

LABEL_PATTERNS = [
    # Only keep "Item Category" rows that actually name a material, otherwise the
    # pattern also catches vendor-enlistment boilerplate.
    ("item_category", re.compile(r"Item Category\s*/?\s*Item Category\s*:?\s*(.{5,400})", re.I)),
    ("gem_search_string", re.compile(
        r"(?:Searched Strings? used in GeMARPTS|GeMARPTS\s*Searched Strings?)\s*:?\s*(.{5,400})",
        re.I)),
    ("gem_search_result", re.compile(
        r"(?:Searched Result generated in GeMARPTS|GeMARPTS\s*Searched Result)\s*:?\s*(.{5,400})",
        re.I)),
    ("gem_category", re.compile(
        r"(?:Relevant Categories selected for notification|GeMARPTS\s*Relevant Categories)\s*:?\s*(.{3,300})",
        re.I)),
    ("primary_product_category", re.compile(
        r"Primary product category\s*/?\s*Primary product category\s*:?\s*(.{5,400})", re.I)),
    ("brief_description", re.compile(r"Brief NIT Description\s*:?\s*(.{5,400})", re.I)),
    ("tender_title", re.compile(r"Tender Title\s*:?\s*(.{5,400})", re.I)),
]

SCHEDULE = re.compile(
    r"^\s*(?:Schedule|Item|BoQ|BOQ|Sl\.?\s*No\.?)\s*[-:]?\s*(\d{1,3})\s*[|\t]\s*"
    r"(.{4,200}?)\s*[|\t]\s*([\d,]+(?:\.\d+)?)\s*(?:[|\t]\s*([A-Za-z]{2,12})\s*)?$")

# a comma-delimited engineering spec string, e.g. CABLE,PWR,240MM2,1C,STRANDED,AL,11KV
SPEC = re.compile(r"\b[A-Z0-9/]{2,}\s*(?:,\s*[A-Z0-9/\.\-]{1,20}\s*){3,}")

MATERIAL_NOUN = re.compile(
    r"\b(valve|pump|pipe|flange|bearing|gasket|compressor|motor|cable|gauge|"
    r"sensor|transmitter|thermocouple|bolt|fitting|elbow|tee|reducer|strainer|"
    r"filter|exchanger|boiler|turbine|blower|fan|vessel|tank|drum|column|"
    r"reactor|actuator|orifice|meter|analyser|analyzer|switchgear|breaker|relay|"
    r"battery|transformer|conveyor|belt|insulator|arrester|coupling|gearbox|"
    r"impeller|seal|stud|nut|washer|electrode|refractory|heater|ejector|"
    r"separator|chimney|crane|hoist|generator|panel|starter|contactor)\b", re.I)


def clean(s):
    s = CID.sub(" ", s or "")
    s = re.sub(r"[\u0900-\u097f]+", " ", s)          # strip Devanagari fragments
    s = s.replace("\u2019", "'").replace("\u2018", "'")
    s = re.sub(r"\s+", " ", s)
    return s.strip(" \t|:-")


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    files = sorted(glob.glob(os.path.join(SRC, "*.txt")))
    print(f"text files: {len(files)}", flush=True)

    rows = []
    seen = set()

    def add(nit_id, doc, kind, value, extra=None):
        v = clean(value)
        if len(v) < 4 or len(v) > 500:
            return
        k = (nit_id, kind, v.lower())
        if k in seen:
            return
        seen.add(k)
        rows.append({"nit_id": nit_id, "doc_name": doc, "pattern": kind,
                     "item_text": v, "quantity": (extra or {}).get("quantity", ""),
                     "unit": (extra or {}).get("unit", ""),
                     "line_no": (extra or {}).get("line_no", "")})

    for path in files:
        base = os.path.basename(path)
        m = re.match(r"^(\d+)_", base)
        nit_id = m.group(1) if m else ""
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                lines = f.read().splitlines()
        except Exception:
            continue

        for i, line in enumerate(lines):
            raw = clean(line)
            if not raw:
                continue
            for kind, rx in LABEL_PATTERNS:
                mm = rx.search(raw)
                if not mm:
                    continue
                val = mm.group(1)
                if kind in ("item_category", "gem_category",
                            "primary_product_category", "gem_search_result") \
                        and not MATERIAL_NOUN.search(val):
                    continue
                add(nit_id, base, kind, val, {"line_no": i + 1})
            sm = SCHEDULE.match(raw)
            if sm:
                add(nit_id, base, "boq_schedule_line", sm.group(2),
                    {"quantity": sm.group(3), "unit": sm.group(4) or "",
                     "line_no": i + 1})
            for sp in SPEC.findall(raw):
                if MATERIAL_NOUN.search(sp):
                    add(nit_id, base, "spec_string", sp, {"line_no": i + 1})
            # plain sentence containing a material noun + a size token
            if MATERIAL_NOUN.search(raw) and len(raw) > 18 and re.search(
                    r"\b\d{1,4}\s*(?:mm|MM|inch|INCH|\"|kv|KV|MW|kg|KG|mt|MT|"
                    r"bar|BAR|HP|hp|TPD|TPH)\b", raw) and len(raw) < 300:
                add(nit_id, base, "spec_sentence", raw, {"line_no": i + 1})

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["nit_id", "doc_name", "pattern",
                                          "item_text", "quantity", "unit",
                                          "line_no"])
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    c = Counter(r["pattern"] for r in rows)
    print(f"rows written: {len(rows)}")
    for k, v in c.most_common():
        print(f"  {k:26s} {v}")
    print(f"distinct NITs: {len(set(r['nit_id'] for r in rows))}")


if __name__ == "__main__":
    main()
