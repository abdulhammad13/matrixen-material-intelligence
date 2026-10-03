#!/usr/bin/env python3
"""
Upload the collected SIH 26099 dataset to a Hugging Face Hub repo.

Usage
    python3 scripts/upload_to_hf.py --repo <user>/<name> [--private] [--zip]

The token is read from the HF_TOKEN environment variable so it never appears in
this file, in a command line, or in the process list.

What gets uploaded
    DATASET_README.md            -> README.md  (renders on the repo front page)
    PRUNED.txt                   -> PRUNED.txt
    data/                        -> data/
    scripts/                     -> scripts/
    MANIFEST.csv                 -> generated file-by-file inventory

Nothing is deleted locally; this is a straight copy to the Hub.
"""
import argparse
import csv
import hashlib
import os
import sys

from huggingface_hub import HfApi, create_repo, upload_file, upload_folder

ROOTS = ["data", "scripts"]
EXTRA_FILES = ["PRUNED.txt"]


def sha256(path, limit=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(limit))
    return h.hexdigest()[:16]


def row_count(path):
    if not path.endswith(".csv"):
        return ""
    try:
        import pandas as pd
        return str(len(pd.read_csv(path, dtype=str, usecols=[0])))
    except Exception:
        return ""


def build_manifest(dest):
    rows = []
    for root in ROOTS:
        for dp, _, fns in os.walk(root):
            for fn in sorted(fns):
                p = os.path.join(dp, fn)
                rows.append({"path": p, "bytes": os.path.getsize(p),
                             "sha256_16": sha256(p), "csv_rows": row_count(p)})
    for f in EXTRA_FILES:
        if os.path.exists(f):
            rows.append({"path": f, "bytes": os.path.getsize(f),
                         "sha256_16": sha256(f), "csv_rows": ""})
    rows.sort(key=lambda r: r["path"])
    with open(dest, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["path", "bytes", "sha256_16", "csv_rows"])
        w.writeheader()
        w.writerows(rows)
    return rows


def make_zip(dest="sih26099_dataset.zip"):
    import zipfile
    n = 0
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for root in ROOTS:
            for dp, _, fns in os.walk(root):
                for fn in sorted(fns):
                    p = os.path.join(dp, fn)
                    z.write(p, p)
                    n += 1
        for f in EXTRA_FILES + ["DATASET_README.md", "MANIFEST.csv"]:
            if os.path.exists(f):
                z.write(f, f)
                n += 1
    return dest, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="e.g. yourname/sih26099-cpse-materials")
    ap.add_argument("--private", action="store_true")
    ap.add_argument("--zip", action="store_true",
                    help="also upload a single zip of the whole tree")
    ap.add_argument("--dry-run", action="store_true",
                    help="build the manifest and report, upload nothing")
    args = ap.parse_args()

    token = os.environ.get("HF_TOKEN")
    if not token and not args.dry_run:
        sys.exit("HF_TOKEN is not set. Export it first: "
                 "export HF_TOKEN=hf_xxx   (do not paste it into a file)")

    rows = build_manifest("MANIFEST.csv")
    total = sum(r["bytes"] for r in rows)
    print(f"manifest      : {len(rows)} files, {total / 1e6:.1f} MB -> MANIFEST.csv")
    csvs = [r for r in rows if r["csv_rows"]]
    print(f"csv inventories: {len(csvs)} files, "
          f"{sum(int(r['csv_rows']) for r in csvs):,} data rows")

    if args.dry_run:
        print("\n[dry-run] nothing uploaded")
        return

    api = HfApi(token=token)
    who = api.whoami()
    print(f"authenticated : {who['name']}")

    create_repo(args.repo, repo_type="dataset", private=args.private,
                exist_ok=True, token=token)
    print(f"repo ready    : https://huggingface.co/datasets/{args.repo}")

    upload_file(path_or_fileobj="DATASET_README.md", path_in_repo="README.md",
                repo_id=args.repo, repo_type="dataset", token=token)
    print("uploaded      : README.md")
    upload_file(path_or_fileobj="MANIFEST.csv", path_in_repo="MANIFEST.csv",
                repo_id=args.repo, repo_type="dataset", token=token)
    print("uploaded      : MANIFEST.csv")

    for root in ROOTS:
        upload_folder(folder_path=root, path_in_repo=root, repo_id=args.repo,
                      repo_type="dataset", token=token)
        print(f"uploaded      : {root}/")
    for f in EXTRA_FILES:
        if os.path.exists(f):
            upload_file(path_or_fileobj=f, path_in_repo=f, repo_id=args.repo,
                        repo_type="dataset", token=token)
            print(f"uploaded      : {f}")

    if args.zip:
        zp, n = make_zip()
        print(f"zipping       : {n} files -> {zp} "
              f"({os.path.getsize(zp) / 1e6:.1f} MB)")
        upload_file(path_or_fileobj=zp, path_in_repo=zp, repo_id=args.repo,
                    repo_type="dataset", token=token)
        print(f"uploaded      : {zp}")

    print(f"\nDONE  https://huggingface.co/datasets/{args.repo}")


if __name__ == "__main__":
    main()
