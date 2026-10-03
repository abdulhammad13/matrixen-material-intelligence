#!/usr/bin/env python3
"""
Extract item rows from IOCL's published Future Procurement Plan (FY 2025-26).

The 104-page PDF is organised by IOCL business unit (Refineries, Pipelines,
Marketing, Projects, R&D, ...). Each section is a table:
   Sl.No | Description of item | Broad specification | Parameters |
   Quantity | Unit | Estimated Value of procurement in Rs/Crores

Output: data/processed/extracted_items/iocl_procurement_plan_items.csv
"""
import csv
import os
import re

import pdfplumber

SRC = "data/raw/iocl/tenders/Future_Procurement_Plan25-26.pdf"
OUT = "data/processed/extracted_items/iocl_procurement_plan_items.csv"

UNIT_RE = re.compile(
    r"^(nos?\.?|sets?\.?|lots?\.?|mt|kg|km|mtr|cum|sqm|litres?|ltr|each|"
    r"ea|pair|pairs|rolls?|packages?|spools?|lengths?|numbers?|assort\w*)\.?$",
    re.IGNORECASE)
NUM_RE = re.compile(r"^[\d,]+(?:\.\d+)?$")

HEADER_HINTS = ("sl", "description of item", "broad specification", "quantity",
                "unit", "estimated", "parameters")


def is_item_row(cells):
    if not cells:
        return False
    first = (cells[0] or "").strip()
    if not re.fullmatch(r"\d{1,3}\.?", first):
        return False
    joined = " ".join((c or "") for c in cells).strip()
    return len(joined) > 8


def looks_like_header(cells):
    j = " ".join((c or "").lower() for c in cells)
    return sum(h in j for h in HEADER_HINTS) >= 3


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    rows = []
    with pdfplumber.open(SRC) as pdf:
        print(f"pages: {len(pdf.pages)}", flush=True)
        for pno, page in enumerate(pdf.pages, 1):
            # business-unit banner: printed as a lone short line above the table
            section = ""
            for line in (page.extract_text() or "").splitlines():
                ls = re.sub(r"\s+", " ", line).strip()
                if len(ls) < 60 and re.fullmatch(
                        r"Refineries|Pipelines?|Marketing|Projects?|"
                        r"R\s*&\s*D|Research and Development|Corporate Office|"
                        r"Engineering|Construction|Exploration|Liaison|"
                        r"Capex Procurement Projected|Opex Procurement Projected",
                        ls, re.IGNORECASE):
                    section = ls
                    break

            for table in (page.extract_tables() or []):
                for cells in table:
                    cells = [re.sub(r"\s+", " ", (c or "")).strip() for c in cells]
                    if looks_like_header(cells) or not is_item_row(cells):
                        continue
                    body = [c for c in cells[1:] if c]
                    if not body:
                        continue
                    # The description is the first non-numeric, non-unit cell.
                    # Picking the longest cell is wrong: "Pumps | 275 | Nos. |
                    # 138.08" would yield "138.08" as the description.
                    # Some pages carry a stray "MTs" unit cell before the real
                    # description, so require a description-like length rather
                    # than just "not a number".
                    desc = ""
                    for c in body:
                        cu = c.strip()
                        if NUM_RE.match(cu) or UNIT_RE.match(cu):
                            continue
                        if len(cu) < 6:
                            continue
                        desc = cu
                        break
                    if not desc:
                        cands = [c.strip() for c in body
                                 if not NUM_RE.match(c.strip())
                                 and not UNIT_RE.match(c.strip())]
                        desc = max(cands, key=len) if cands else ""
                    if len(desc) < 6:
                        continue
                    unit = qty = value = ""
                    nums = []
                    for c in body:
                        cu = c.strip()
                        if not unit and UNIT_RE.match(cu):
                            unit = cu
                        elif NUM_RE.match(cu):
                            nums.append(cu)
                    if nums:
                        qty = nums[0]
                        if len(nums) > 1:
                            value = nums[-1]
                    rows.append({
                        "page": pno,
                        "section": section,
                        "sl_no": cells[0].strip(),
                        "item_description": desc,
                        "quantity": qty,
                        "unit": unit,
                        "estimated_value_rs_crores": value,
                        "row_raw": " | ".join(body),
                        "source_pdf": os.path.basename(SRC),
                    })

    seen, uniq = set(), []
    for r in rows:
        k = (r["page"], r["sl_no"], r["item_description"], r["row_raw"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["page", "section", "sl_no",
                                          "item_description", "quantity", "unit",
                                          "estimated_value_rs_crores", "row_raw",
                                          "source_pdf"])
        w.writeheader()
        w.writerows(uniq)
    print(f"item rows extracted : {len(uniq)}")
    print(f"sections            : "
          f"{sorted(set(r['section'] for r in uniq if r['section']))}")
    print(f"units               : "
          f"{sorted(set(r['unit'] for r in uniq if r['unit']))[:20]}")
    print(f"rows with a quantity: "
          f"{sum(1 for r in uniq if r['quantity'])}")


if __name__ == "__main__":
    main()
