#!/usr/bin/env python3
"""Usage: python scripts/certificates/search.py "iron foundry ISO 9001 in Germany" [-n 5]"""
import argparse
import json
import os

from pymongo import MongoClient

from embed import embed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("-n", "--limit", type=int, default=5)
    args = ap.parse_args()

    [vector] = embed([args.query])
    with MongoClient(os.environ["MONGODB_URI"]) as client:
        col = client[os.getenv("MONGODB_DB", "portfolio")][os.getenv("MONGODB_COLLECTION", "certificates")]
        results = col.aggregate(
            [
                {
                    "$vectorSearch": {
                        "index": "certificates_vector",
                        "path": "embedding",
                        "queryVector": vector,
                        "numCandidates": args.limit * 20,
                        "limit": args.limit,
                    }
                },
                {
                    "$project": {
                        "_id": 0,
                        "fileName": 1,
                        "organization.name": 1,
                        "standard": 1,
                        "validUntil": 1,
                        "score": {"$meta": "vectorSearchScore"},
                    }
                },
            ]
        )
        print(json.dumps(list(results), indent=2, default=str, ensure_ascii=False))


if __name__ == "__main__":
    main()
