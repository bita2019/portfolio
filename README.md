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

### Extract metadata from many PDFs on your own machine

```
pip install -r scripts/certificates/requirements-extract.txt
cd scripts/certificates

python extract_metadata.py path/to/pdf_folder -o results/metadata        # every PDF in the folder
python extract_metadata.py path/to/pdf_folder -r                        # ... including sub-folders
python extract_metadata.py --urls urls.txt                              # URLs, one per line
python extract_metadata.py pdf_folder --urls urls.txt -o results/metadata   # both at once
```

Writes `results/metadata.json`, `.xlsx` and `.md`: one row per PDF with company name, country, city, author or issuer, title of report,
reporting period, start date and end date, plus notes. A PDF that cannot be read is listed as "not read" with the reason and does not stop
the run. For local files without a URL the company name is found from the report text alone; the notes column flags lower-confidence names.

### Extraction service (URL in, validated metadata out)

```
pip install -r scripts/certificates/requirements.txt
cd scripts/certificates && ALLOWED_HOSTS=georgfischer.com python service.py     # http://127.0.0.1:8000

curl -X POST localhost:8000/extract -H 'content-type: application/json' \
     -d '{"url": "https://www.georgfischer.com/.../sustainability-statement-2024-en.pdf?utm_source=chatgpt.com"}'
```

By default it returns a short record: `companyName`, `country`, `city`, `authorOrIssuer` (+ `authorOrIssuerRole`: author or issuer),
`reportTitle`, `reportingPeriod` (as written in the report), `startDate`, `endDate` and `notes` (anything uncertain or missing). Add `?detail=full` for everything the
extractor found (frameworks, outline, scope statement, company candidates, validation, ...).

Nothing is inferred: `startDate` and `endDate` are filled only when the report states its period (a full range, or just a year end, in which
case only `endDate` is set and `notes` says so). `reportingPeriod` is the period text as written, for example `April 1, 2024 - March 31, 2025`.
For a certificate the fields are the holder, its address, the certification body, the standard and the validity dates.

The service downloads caller-supplied URLs, so it only follows http(s) on ports 80/443, re-checks every redirect, refuses hosts that
resolve to private addresses, and caps the download size (`MAX_PDF_MB`, default 100). Set `ALLOWED_HOSTS` to restrict it to known hosts
and `SERVICE_API_KEY` to require an `X-API-Key` header. Run `pytest scripts/certificates` for the tests.
