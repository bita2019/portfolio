## Personal Portfolio

![Portfolio Website](https://i.ibb.co/WgPMpts/image.png)

## Certificate ingestion (MongoDB Atlas vector search)

`scripts/certificates/` extracts metadata from certificate PDFs (ISO 9001 style) and stores it with an embedding in MongoDB Atlas.

```
pip install -r scripts/certificates/requirements.txt
export MONGODB_URI=...            # Atlas connection string (vector search needs Atlas)
# embeddings run locally (sentence-transformers, no API key); set EMBEDDING_MODEL to use another model
python scripts/certificates/ingest.py path/to/certs-or-file.pdf [--dry-run | --json-dir out/]
python scripts/certificates/search.py "iron foundry certified to ISO 9001"
```

Ingest is idempotent (keyed on the file's SHA-256) and creates the `certificates_vector` index on first run.

### Extraction service (URL in, validated metadata out)

```
pip install -r scripts/certificates/requirements.txt
cd scripts/certificates && ALLOWED_HOSTS=georgfischer.com python service.py     # http://127.0.0.1:8000

curl -X POST localhost:8000/extract -H 'content-type: application/json' \
     -d '{"url": "https://www.georgfischer.com/.../sustainability-statement-2024-en.pdf?utm_source=chatgpt.com"}'
```

Returns `source` (canonical URL with tracking parameters removed, year / language / type read from the URL, HTTP headers),
`kind` (`certificate` or `document`), the extracted `certificate` or `document` metadata (a document includes `title` and `company` with its source and confidence), and a `validation` block
(certificates: organization / standard / dates found and valid, expired or not yet valid; documents: title and reporting year found).

The service downloads caller-supplied URLs, so it only follows http(s) on ports 80/443, re-checks every redirect, refuses hosts that
resolve to private addresses, and caps the download size (`MAX_PDF_MB`, default 100). Set `ALLOWED_HOSTS` to restrict it to known hosts
and `SERVICE_API_KEY` to require an `X-API-Key` header. Run `pytest scripts/certificates` for the tests.
