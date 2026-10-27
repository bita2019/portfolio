#!/usr/bin/env node
// Usage: node scripts/certificates/search.mjs "iron foundry ISO 9001 in Germany" [limit]
import { MongoClient } from 'mongodb'
import { embed } from './embed.mjs'

const [query, limit = '5'] = process.argv.slice(2)
if (!query) {
  console.error('Usage: search.mjs "<query>" [limit]')
  process.exit(1)
}

const [vector] = await embed([query])
const client = new MongoClient(process.env.MONGODB_URI)
try {
  const results = await client
    .db(process.env.MONGODB_DB ?? 'portfolio')
    .collection(process.env.MONGODB_COLLECTION ?? 'certificates')
    .aggregate([
      {
        $vectorSearch: {
          index: 'certificates_vector',
          path: 'embedding',
          queryVector: vector,
          numCandidates: Number(limit) * 20,
          limit: Number(limit),
        },
      },
      {
        $project: {
          _id: 0,
          fileName: 1,
          'organization.name': 1,
          standard: 1,
          validUntil: 1,
          score: { $meta: 'vectorSearchScore' },
        },
      },
    ])
    .toArray()
  console.log(JSON.stringify(results, null, 2))
} finally {
  await client.close()
}
