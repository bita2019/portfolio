import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { basename } from 'node:path'
import pdfParse from 'pdf-parse/lib/pdf-parse.js'

const ISO_DATE = /\d{4}-\d{2}-\d{2}/
const STANDARD = /(?:DIN\s+)?(?:EN\s+)?(?:ISO(?:\/\w+)?|IATF)\s*\d{3,5}(?::\d{4})?/i

const section = (text, start, end) => {
  const m = text.match(new RegExp(`${start}\\s*([\\s\\S]*?)\\s*(?:${end})`, 'i'))
  return m ? m[1].trim() : null
}

const lines = (s) =>
  (s ?? '').split('\n').map((l) => l.trim()).filter(Boolean)

const pdfDate = (d) => {
  const m = /^D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(?:([+-])(\d{2})'?(\d{2})?)?/.exec(d ?? '')
  if (!m) return null
  const offsetMin = m[7] ? (m[7] === '-' ? -1 : 1) * (+m[8] * 60 + +(m[9] ?? 0)) : 0
  return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]) - offsetMin * 60000)
}

export async function extractCertificate(path) {
  const buffer = await readFile(path)
  const { text, numpages, info } = await pdfParse(buffer)
  const clean = text.replace(/\r/g, '').replace(/[ \t]+/g, ' ')

  const holder = lines(section(clean, 'certifies that the organization', 'for the scope'))
  const country = holder.at(-1)
  const cityLine = holder.at(-2)
  const street = holder.slice(1, -2)
  const city = /^(\d{4,5})\s+(.+)$/.exec(cityLine ?? '')
  const name = holder[0] ?? null

  const validity = clean.match(
    new RegExp(`valid from (${ISO_DATE.source}) until (${ISO_DATE.source})`, 'i'),
  )
  const issued = clean.match(new RegExp(`([A-Za-zÀ-ÿ .-]+),\\s*(${ISO_DATE.source})\\s*$`, 'm'))
  const signatory = lines(section(clean, 'Head of Certification Body\\s*', '$'))[0]
  const signedBy = clean.match(/^(.+)\nHead of Certification Body/m)?.[1]?.trim() ?? signatory ?? null

  return {
    fileName: basename(path),
    sha256: createHash('sha256').update(buffer).digest('hex'),
    registrationNo: clean.match(/Registration No\.?:\s*([^/\n]+?)\s*(?:\/|\n)/i)?.[1] ?? null,
    orderNo: clean.match(/Order No\.?:\s*(\S+)/i)?.[1] ?? null,
    certificationBody: clean.match(/Certification Body\s+of\s+([^\n]+)/i)?.[1]?.trim() ?? null,
    organization: {
      name,
      street: street.join(', ') || null,
      postalCode: city?.[1] ?? null,
      city: city?.[2] ?? null,
      country: country ?? null,
    },
    scope: section(clean, 'for the scope', 'has established')?.replace(/\s*\n\s*/g, ' ') ?? null,
    standard: clean.match(STANDARD)?.[0].replace(/\s+/g, ' ') ?? null,
    validFrom: validity ? new Date(validity[1]) : null,
    validUntil: validity ? new Date(validity[2]) : null,
    issuedPlace: issued?.[1].trim() ?? null,
    issuedDate: issued ? new Date(issued[2]) : null,
    signedBy,
    pdf: {
      pages: numpages,
      author: info?.Author || null,
      creator: info?.Creator || null,
      createdAt: pdfDate(info?.CreationDate),
    },
    text: clean.trim(),
  }
}

// Text that gets embedded: the fields people actually search by.
export const embeddingText = (c) =>
  [
    c.organization.name,
    [c.organization.street, c.organization.postalCode, c.organization.city, c.organization.country]
      .filter(Boolean)
      .join(', '),
    c.standard && `Standard: ${c.standard}`,
    c.scope && `Scope: ${c.scope}`,
    c.certificationBody && `Certified by ${c.certificationBody}`,
  ]
    .filter(Boolean)
    .join('\n')
