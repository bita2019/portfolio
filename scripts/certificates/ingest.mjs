#!/usr/bin/env node
// Usage: node scripts/certificates/ingest.mjs <file-or-dir.pdf>... [--dry-run]
import { readdir, stat } from 'node:fs/promises'
import { join } from 'node:path'
import { MongoClient } from 'mongodb'
import { extractCertificate, embeddingText } from './extract.mjs'
import { embed, DIMENSIONS, MODEL } from './embed.mjs'

const DB = process.env.MONGODB_DB ?? 'portfolio'
const COLLECTION = process.env.MONGODB_COLLECTION ?? 'certificates'
export const INDEX = 'certificates_vector'

const args = process.argv.slice(2)
const dryRun = args.includes('--dry-run')
const targets = args.filter((a) => !a.startsWith('--'))

async function* pdfs(p) {
  if ((await stat(p)).isDirectory()) {
    for (const f of await readdir(p)) if (f.toLowerCase().endsWith('.pdf')) yield join(p, f)
  } else yield p
}

async function ensureIndex(col) {
  const existing = await col.listSearchIndexes(INDEX).toArray()
  if (existing.length) return
  await col.createSearchIndex({
    name: INDEX,
    type: 'vectorSearch',
    definition: {
      fields: [
        { type: 'vector', path: 'embedding', numDimensions: DIMENSIONS, similarity: 'cosine' },
        { type: 'filter', path: 'standard' },
        { type: 'filter', path: 'organization.country' },
        { type: 'filter', path: 'validUntil' },
      ],
    },
  })
  console.log(`Created vector index "${INDEX}" (builds asynchronously in Atlas)`)
}

if (!targets.length) {
  console.error('Usage: ingest.mjs <file-or-dir>... [--dry-run]')
  process.exit(1)
}

const certs = []
for (const t of targets) for await (const f of pdfs(t)) certs.push(await extractCertificate(f))

if (dryRun) {
  for (const { text, ...c } of certs) console.log(JSON.stringify(c, null, 2))
  process.exit(0)
}

const embeddings = await embed(certs.map(embeddingText))
const client = new MongoClient(process.env.MONGODB_URI)
try {
  const col = client.db(DB).collection(COLLECTION)
  await col.createIndex({ sha256: 1 }, { unique: true })
  await ensureIndex(col)
  for (const [i, c] of certs.entries()) {
    // Keyed on file hash so re-running on the same PDF updates instead of duplicating.
    await col.updateOne(
      { sha256: c.sha256 },
      { $set: { ...c, embedding: embeddings[i], embeddingModel: MODEL, updatedAt: new Date() } },
      { upsert: true },
    )
    console.log(`Stored ${c.fileName} (${c.organization.name})`)
  }
} finally {
  await client.close()
}
