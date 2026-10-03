#!/usr/bin/env python3
"""
Consolidate every harvested material/item description into ONE corpus table,
which is the working dataset for the SIH 26099 material-code harmonisation
problem.

One row = one real, publicly published material/item description, tagged with
the CPSE/organisation that published it and where it came from.

Inputs (all produced by the harvesters)
  data/raw/ntpc/tenders/nit_details.csv
  data/raw/ntpc/tenders/listing_rows.csv
  data/raw/iocl/tenders/tender_details.csv
  data/raw/iocl/tenders/search_rows.csv
  data/raw/oil_india/tenders/{live,archive,old}_tenders.csv
  data/raw/oil_india/tenders/tender_details.csv
  data/raw/oil_india/tenders/corrigenda.csv
  data/processed/extracted_items/iocl_procurement_plan_items.csv
  data/processed/extracted_items/ntpc_material_items.csv
  data/reference/unspsc/unspsc_master.csv

Output
  data/processed/extracted_items/material_description_corpus.csv
"""
import csv
import os
import re
import sys

import pandas as pd

OUT = "data/processed/extracted_items/material_description_corpus.csv"

COLS = ["organization", "source_system", "source_section",
        "tender_reference", "tender_id", "description", "description_kind",
        "item_type_hint", "quantity", "unit", "location", "product_category",
        "document_url", "source_url"]

# vocabulary used to give each description a coarse item-type hint
TYPE_PATTERNS = [
    ("ball valve", r"\bball\s+(?:vl|vlv|valve)"),
    ("gate valve", r"\bgate\s+(?:vl|vlv|valve)"),
    ("globe valve", r"\bglob(?:e|e)\s+(?:vl|vlv|valve)"),
    ("butterfly valve", r"\b(?:butterfly|b/?fly)\s+(?:vl|vlv|valve)"),
    ("check valve", r"\b(?:check\s+(?:vl|vlv|valve)|non[- ]return valve|nrv)"),
    ("control valve", r"\b(?:control|ctrl)\s+(?:vl|vlv|valve)"),
    ("safety valve", r"\b(?:safety|relief|psv|prv)\b"),
    ("valve", r"\b(?:vlv|vl|valve)"),
    ("pump", r"\bpump"),
    ("compressor", r"\bcompressor|\bcmpr\b"),
    ("heat exchanger", r"\bheat exchanger|\bhx\b|air cooler|fin fan"),
    ("boiler", r"\bboiler"),
    ("turbine", r"\bturbine"),
    ("motor", r"\bmotor"),
    ("transformer", r"\btransformer|\bxmer\b|\btrf\b"),
    ("cable", r"\bcable"),
    ("switchgear", r"\bswitch\s?gear|\bvcb\b|\bmccb\b|\bacb\b|\bbreaker\b"),
    ("pipe", r"\bpipe"),
    ("flange", r"\bflange|\bflg\b"),
    ("pipe fitting", r"\bfitting|\belbow\b|\btee\b|\breducer\b|\bstub end\b"),
    ("gasket", r"\bgasket|\bswg\b"),
    ("bearing", r"\bbearing|\bbrg\b"),
    ("mechanical seal", r"\bmechanical seal"),
    ("gearbox", r"\bgear\s?box|\bgbx\b"),
    ("coupling", r"\bcoupling"),
    ("instrument", r"\binstrument|\btransmitter|\bthermocouple|\brtd\b|"
                   r"\bpressure gauge|\bflow meter|\banaly[sz]er\b|\bplc\b|\bdcs\b"),
    ("tank", r"\btank|\bdrum\b|\bvessel\b|\bbullet\b"),
    ("filter", r"\bfilter|\bstrainer\b"),
    ("crane", r"\bcrane|\bhoist\b"),
    ("conveyor", r"\bconveyor"),
    ("chimney", r"\bchimney|\bstack\b"),
    ("steel", r"\bsteel\b|\bplate\b|\bstructural\b"),
    ("chemical", r"\bchemical|\bcatalyst|\blube\b|\bgrease\b|\bpaint\b"),
    ("spares", r"\bspare"),
]


def hint(desc):
    d = (desc or "").lower()
    for name, rx in TYPE_PATTERNS:
        if re.search(rx, d):
            return name
    return ""


def load(path):
    if not os.path.exists(path):
        print(f"  (missing, skipped) {path}", file=sys.stderr)
        return pd.DataFrame()
    try:
        return pd.read_csv(path, dtype=str).fillna("")
    except Exception as e:
        print(f"  (unreadable {path}: {e})", file=sys.stderr)
        return pd.DataFrame()


def clean_desc(s):
    s = re.sub(r"\s+", " ", (s or "")).strip()
    s = s.strip(" \t|:-")
    # Drupal renders "truncated... full title"; keep the full half
    m = re.match(r"^.*?\.{3}\s*(.{10,})$", s)
    if m:
        s = m.group(1).strip()
    # Some cells contain the same title twice back to back, e.g.
    # "(1) TRANSPORE 5 CM (1) TRANSPORE 5 CM". Try each split point and, if the
    # two halves match apart from stray whitespace/punctuation, keep one copy.
    norm = lambda x: re.sub(r"[\s\.,\-\(\)]+", "", x).lower()
    if len(s) >= 20:
        for h in range(len(s) // 2 - 2, len(s) // 2 + 3):
            if 8 < h < len(s) and norm(s[:h]) and norm(s[:h]) == norm(s[h:]):
                s = s[:h].strip()
                break
    s = s.strip(" \t|:.-")
    return s


def main():
    rows = []

    def add(**kw):
        d = clean_desc(kw.get("description", ""))
        if len(d) < 8 or len(d) > 1200:
            return
        rows.append({
            "organization": kw.get("organization", ""),
            "source_system": kw.get("source_system", ""),
            "source_section": kw.get("source_section", ""),
            "tender_reference": kw.get("tender_reference", ""),
            "tender_id": kw.get("tender_id", ""),
            "description": d,
            "description_kind": kw.get("description_kind", ""),
            "item_type_hint": hint(d),
            "quantity": kw.get("quantity", ""),
            "unit": kw.get("unit", ""),
            "location": kw.get("location", ""),
            "product_category": kw.get("product_category", ""),
            "document_url": kw.get("document_url", ""),
            "source_url": kw.get("source_url", ""),
        })

    # ------------------------------------------------------------- NTPC ----
    d = load("data/raw/ntpc/tenders/nit_details.csv")
    if len(d):
        for _, r in d.iterrows():
            add(organization="NTPC Limited", source_system="ntpctender.ntpc.co.in",
                source_section="NIT detail", tender_reference=r.get("nit_no", ""),
                tender_id=r.get("nit_id", ""),
                description=r.get("brief_description", ""),
                description_kind="nit_brief_description",
                location=f"{r.get('state','')} / {r.get('region','')}".strip(" /"),
                product_category=r.get("contract_classification", ""),
                source_url=r.get("detail_url", ""))
    d = load("data/raw/ntpc/tenders/listing_rows.csv")
    if len(d):
        for _, r in d.iterrows():
            add(organization="NTPC Limited", source_system="ntpctender.ntpc.co.in",
                source_section=f"listing ({r.get('found_via','')})",
                tender_reference=r.get("tender_reference", ""),
                tender_id=r.get("nit_id", ""),
                description=r.get("tender_title", ""),
                description_kind="tender_title",
                source_url=r.get("detail_url", ""))

    # -------------------------------------------------------------- IOCL ---
    d = load("data/raw/iocl/tenders/tender_details.csv")
    if len(d):
        for _, r in d.iterrows():
            add(organization="Indian Oil Corporation Limited",
                source_system="iocletenders.nic.in",
                source_section="tender detail",
                tender_reference=r.get("tender_reference", ""),
                tender_id=r.get("tender_id", ""),
                description=r.get("title", "") or r.get("work_description", ""),
                description_kind="tender_title",
                location=r.get("location", ""),
                product_category=r.get("product_category", ""),
                source_url=r.get("detail_url", ""))
            wd = r.get("work_description", "")
            if wd and wd != r.get("title", ""):
                add(organization="Indian Oil Corporation Limited",
                    source_system="iocletenders.nic.in",
                    source_section="tender detail",
                    tender_reference=r.get("tender_reference", ""),
                    tender_id=r.get("tender_id", ""),
                    description=wd, description_kind="work_description",
                    location=r.get("location", ""),
                    product_category=r.get("product_category", ""),
                    source_url=r.get("detail_url", ""))
    d = load("data/raw/iocl/tenders/search_rows.csv")
    if len(d):
        for _, r in d.iterrows():
            add(organization="Indian Oil Corporation Limited",
                source_system="iocletenders.nic.in",
                source_section=f"listing (keyword={r.get('keyword','')})",
                tender_reference=r.get("tender_reference", ""),
                tender_id=r.get("tender_id", ""),
                description=r.get("tender_title", ""),
                description_kind="tender_title",
                product_category="", source_url=r.get("detail_url", ""))

    d = load("data/processed/extracted_items/iocl_procurement_plan_items.csv")
    if len(d):
        for _, r in d.iterrows():
            add(organization="Indian Oil Corporation Limited",
                source_system="iocl.com", source_section="Future Procurement Plan FY2025-26",
                description=r.get("item_description", ""),
                description_kind="procurement_plan_item",
                quantity=r.get("quantity", ""), unit=r.get("unit", ""),
                product_category=r.get("section", ""),
                document_url="data/raw/iocl/tenders/Future_Procurement_Plan25-26.pdf")

    # ---------------------------------------------------------- OIL India --
    for fn, kind in [("live_tenders.csv", "live_tender"),
                     ("archive_tenders.csv", "archived_tender")]:
        d = load(f"data/raw/oil_india/tenders/{fn}")
        if len(d):
            for _, r in d.iterrows():
                add(organization="Oil India Limited",
                    source_system="oil-india.com",
                    source_section=r.get("source_section", kind),
                    tender_reference=r.get("tender_no", ""),
                    description=r.get("tender_title", ""),
                    description_kind=kind,
                    location=r.get("location", ""),
                    source_url=r.get("detail_url", ""))
    d = load("data/raw/oil_india/tenders/old_tenders.csv")
    if len(d):
        for _, r in d.iterrows():
            add(organization="Oil India Limited",
                source_system="oil-india.com", source_section="historical tenders",
                tender_reference=r.get("tender_no", ""),
                description=r.get("tender_title", ""),
                description_kind="historical_tender",
                product_category=r.get("tender_category", ""),
                document_url=r.get("document_url", ""),
                source_url=r.get("source_url", ""))
    d = load("data/raw/oil_india/tenders/corrigenda.csv")
    if len(d):
        for _, r in d.iterrows():
            add(organization="Oil India Limited",
                source_system="oil-india.com",
                source_section=r.get("source_section", "corrigendum"),
                tender_reference=r.get("tender_no", ""),
                description=r.get("tender_title", ""),
                description_kind="corrigendum",
                document_url=r.get("document_url", ""))
    d = load("data/raw/oil_india/tenders/tender_details.csv")
    if len(d):
        for _, r in d.iterrows():
            add(organization="Oil India Limited",
                source_system="oil-india.com", source_section="tender detail",
                tender_reference=r.get("tender_no", ""),
                description=r.get("tender_title", ""),
                description_kind="tender_detail",
                location=r.get("location_office", ""),
                document_url=r.get("nit_doc_url", ""),
                source_url=r.get("detail_url", ""))

    # ------------------------------------------------- NTPC document items --
    d = load("data/processed/extracted_items/ntpc_material_items.csv")
    if len(d):
        for _, r in d.iterrows():
            add(organization="NTPC Limited",
                source_system="ntpctender.ntpc.co.in",
                source_section=f"NIT document ({r.get('doc_name','')})",
                tender_id=r.get("nit_id", ""),
                description=r.get("item_text", ""),
                description_kind=f"doc_{r.get('pattern','')}",
                quantity=r.get("quantity", ""), unit=r.get("unit", ""))

    df = pd.DataFrame(rows, columns=COLS)
    # exact-duplicate descriptions within the same organisation are collapsed,
    # but cross-organisation repeats are KEPT - they are the variation the
    # harmonisation model has to resolve.
    before = len(df)
    df = df.drop_duplicates(subset=["organization", "description",
                                    "description_kind"])
    df = df.sort_values(["organization", "description_kind", "description"])
    df.insert(0, "corpus_id", [f"M{ i:06d}" for i in range(1, len(df) + 1)])

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    df.to_csv(OUT, index=False, encoding="utf-8")
    print(f"rows in  : {before}")
    print(f"rows out : {len(df)}  -> {OUT}")
    print()
    print("by organization:")
    print(df["organization"].value_counts().to_string())
    print()
    print("by description_kind:")
    print(df["description_kind"].value_counts().to_string())
    print()
    print("top item_type_hint:")
    print(df[df.item_type_hint != ""]["item_type_hint"].value_counts().head(25).to_string())


if __name__ == "__main__":
    main()
