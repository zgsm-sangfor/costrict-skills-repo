import { useState, useEffect, useRef, useCallback } from 'react'
import MiniSearch from 'minisearch'
import type { CatalogItem, SearchIndexItem } from '../types'

let cachedIndex: MiniSearch | null = null
let cachedItems: Map<string, SearchIndexItem> | null = null

const TOKEN_RE = /[\p{L}\p{N}]+/gu

function normalizeText(value: string | undefined) {
  return (value ?? '').toLowerCase().trim()
}

function extractTokens(query: string) {
  const normalized = normalizeText(query)
  const tokenMatches = normalized.match(TOKEN_RE) ?? []
  const tokens = tokenMatches.filter(token => token.length >= 2)
  return tokens.length > 0 ? Array.from(new Set(tokens)) : [normalized].filter(Boolean)
}

function countCoveredTokens(text: string, tokens: string[]) {
  return tokens.reduce((count, token) => count + (text.includes(token) ? 1 : 0), 0)
}

function rerankResult(item: SearchIndexItem, query: string, baseScore: number) {
  const normalizedQuery = normalizeText(query)
  const tokens = extractTokens(query)
  const anchorToken = tokens.reduce((longest, token) => (
    token.length > longest.length ? token : longest
  ), '')
  const nameText = normalizeText(item.name)
  const descriptionText = normalizeText([item.description, item.description_zh].filter(Boolean).join(' '))
  const metaText = normalizeText([...(item.tags ?? []), ...(item.tech_stack ?? [])].join(' '))
  const searchText = normalizeText(item.search_text)

  const nameCoverage = countCoveredTokens(nameText, tokens)
  const descriptionCoverage = countCoveredTokens(descriptionText, tokens)
  const metaCoverage = countCoveredTokens(metaText, tokens)
  const directCoverage = Math.max(nameCoverage, descriptionCoverage, metaCoverage)
  const expandedCoverage = countCoveredTokens(searchText, tokens)

  let score = baseScore

  if (nameText.includes(normalizedQuery)) score += 140
  if (descriptionText.includes(normalizedQuery)) score += 90
  if (metaText.includes(normalizedQuery)) score += 50

  score += nameCoverage * 36
  score += descriptionCoverage * 20
  score += metaCoverage * 12
  score += expandedCoverage * 4

  if (tokens.length > 1) {
    if (nameCoverage === tokens.length) score += 80
    if (descriptionCoverage === tokens.length) score += 50
    if (metaCoverage === tokens.length) score += 25
    if (expandedCoverage === tokens.length) score += 10

    const anchorInDirectField = [nameText, descriptionText, metaText].some(text => text.includes(anchorToken))
    if (anchorToken) {
      if (anchorInDirectField) score += 24
      else if (searchText.includes(anchorToken)) score -= 12
      else score -= 28
    }
  }

  // Keep search_text as recall expansion, but avoid letting expansion-only hits dominate.
  if (directCoverage === 0 && expandedCoverage > 0) {
    score -= 40
  }

  return score
}

export function useSearch(query: string) {
  const [results, setResults] = useState<CatalogItem[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [searchReady, setSearchReady] = useState(!!cachedIndex)
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined)

  // Load and build index on first call with a query
  const ensureIndex = useCallback(async () => {
    if (cachedIndex) return cachedIndex

    setSearching(true)
    const resp = await fetch('./api/search-index.json')
    const rawItems: SearchIndexItem[] = await resp.json()
    const items = rawItems.map(item => ({
      ...item,
      search_text: item.search_text ?? [
        item.name,
        item.description,
        item.description_zh,
        item.tags.join(' '),
        item.tech_stack.join(' '),
      ].filter(Boolean).join(' '),
    }))

    const ms = new MiniSearch<SearchIndexItem>({
      fields: ['name', 'description', 'description_zh', 'search_text'],
      storeFields: ['id'],
      searchOptions: {
        boost: { name: 3, description: 1, description_zh: 1, search_text: 0.8 },
        prefix: true,
        fuzzy: 0.2,
      },
    })
    ms.addAll(items)

    cachedItems = new Map(items.map(i => [i.id, i]))
    cachedIndex = ms
    setSearchReady(true)
    setSearching(false)
    return ms
  }, [])

  useEffect(() => {
    if (!query.trim()) {
      setResults(null)
      return
    }

    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(async () => {
      const ms = await ensureIndex()
      const hits = ms.search(query).slice(0, 200)
      const ranked = hits
        .map(hit => {
          const item = cachedItems?.get(hit.id)
          if (!item) return null
          return {
            item: item as unknown as CatalogItem,
            score: rerankResult(item, query, hit.score),
          }
        })
        .filter((result): result is { item: CatalogItem, score: number } => result !== null)
        .sort((a, b) => b.score - a.score)
        .map(result => result.item)
      setResults(ranked)
    }, 200)

    return () => clearTimeout(timerRef.current)
  }, [query, ensureIndex])

  return { results, searching, searchReady }
}
