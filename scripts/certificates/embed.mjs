// Any OpenAI-compatible /embeddings endpoint works (OpenAI, Voyage, Azure, local servers).
const BASE = process.env.EMBEDDING_BASE_URL ?? 'https://api.openai.com/v1'
export const MODEL = process.env.EMBEDDING_MODEL ?? 'text-embedding-3-small'
export const DIMENSIONS = Number(process.env.EMBEDDING_DIMENSIONS ?? 1536)

export async function embed(inputs) {
  const res = await fetch(`${BASE}/embeddings`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      authorization: `Bearer ${process.env.EMBEDDING_API_KEY}`,
    },
    body: JSON.stringify({ model: MODEL, input: inputs, dimensions: DIMENSIONS }),
  })
  if (!res.ok) throw new Error(`Embedding request failed: ${res.status} ${await res.text()}`)
  const { data } = await res.json()
  return data.sort((a, b) => a.index - b.index).map((d) => d.embedding)
}
