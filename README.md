## Personal Portfolio

![Portfolio Website](https://i.ibb.co/WgPMpts/image.png)

## Certificate ingestion (MongoDB Atlas vector search)

`scripts/certificates/` extracts metadata from certificate PDFs (ISO 9001 style) and stores it with an embedding in MongoDB Atlas.

```
pip install -r scripts/certificates/requirements.txt
export MONGODB_URI=...            # Atlas connection string (vector search needs Atlas)
export EMBEDDING_API_KEY=...      # OpenAI-compatible; override EMBEDDING_BASE_URL / EMBEDDING_MODEL / EMBEDDING_DIMENSIONS
python scripts/certificates/ingest.py path/to/certs-or-file.pdf [--dry-run]
python scripts/certificates/search.py "iron foundry certified to ISO 9001"
```

Ingest is idempotent (keyed on the file's SHA-256) and creates the `certificates_vector` index on first run.
