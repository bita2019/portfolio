#!/usr/bin/env python3
"""Usage: python scripts/certificates/ingest.py <file-or-dir>... [--dry-run]"""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient
from pymongo.operations import SearchIndexModel

from embed import DIMENSIONS, MODEL, embed
from extract import embedding_text, extract_certificate

INDEX = "certificates_vector"


def find_pdfs(targets):
    for t in map(Path, targets):
        yield from sorted(t.glob("*.pdf")) if t.is_dir() else [t]


def ensure_index(col):
    if list(col.list_search_indexes(INDEX)):
        return
    col.create_search_index(
        SearchIndexModel(
            name=INDEX,
            type="vectorSearch",
            definition={
                "fields": [
                    {"type": "vector", "path": "embedding", "numDimensions": DIMENSIONS, "similarity": "cosine"},
                    {"type": "filter", "path": "standard"},
                    {"type": "filter", "path": "organization.country"},
                    {"type": "filter", "path": "validUntil"},
                ]
            },
        )
    )
    print(f'Created vector index "{INDEX}" (builds asynchronously in Atlas)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="+")
    ap.add_argument("--dry-run", action="store_true", help="print extracted metadata only")
    args = ap.parse_args()

    certs = [extract_certificate(f) for f in find_pdfs(args.targets)]

    if args.dry_run:
        for c in certs:
            print(json.dumps({k: v for k, v in c.items() if k != "text"}, indent=2, default=str, ensure_ascii=False))
        return

    embeddings = embed([embedding_text(c) for c in certs])
    with MongoClient(os.environ["MONGODB_URI"]) as client:
        col = client[os.getenv("MONGODB_DB", "portfolio")][os.getenv("MONGODB_COLLECTION", "certificates")]
        col.create_index("sha256", unique=True)
        ensure_index(col)
        for c, vec in zip(certs, embeddings):
            # Keyed on file hash so re-running on the same PDF updates instead of duplicating.
            col.update_one(
                {"sha256": c["sha256"]},
                {"$set": {**c, "embedding": vec, "embeddingModel": MODEL, "updatedAt": datetime.now(timezone.utc)}},
                upsert=True,
            )
            print(f"Stored {c['fileName']} ({c['organization']['name']})")


if __name__ == "__main__":
    main()
