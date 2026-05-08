import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import { buildInstallGuidance } from './installGuidance'
import type { CatalogItem } from '../types'

function makeItem(overrides: Partial<CatalogItem>): CatalogItem {
  return {
    id: 'test-skill',
    name: 'Test Skill',
    type: 'skill',
    description: 'Test description',
    source_url: 'https://github.com/example/repo',
    stars: null,
    category: 'tooling',
    tags: [],
    tech_stack: [],
    source: 'test',
    last_synced: '2026-04-13',
    final_score: 0,
    decision: 'review',
    ...overrides,
  }
}

describe('buildInstallGuidance', () => {
  it('prefers files[] over generic git clone for extraction-based skill installs', () => {
    const item = makeItem({
      install: {
        method: 'git_clone',
        repo: 'https://github.com/sickn33/antigravity-awesome-skills.git',
        files: ['skills/blockrun/'],
      },
    })

    const guidance = buildInstallGuidance(item, 'en')

    expect(guidance.kind).toBe('skill_extract')
    if (guidance.kind !== 'skill_extract') {
      throw new Error(`Expected skill_extract guidance, got ${guidance.kind}`)
    }
    expect(guidance.repo).toBe('https://github.com/sickn33/antigravity-awesome-skills.git')
    expect(guidance.paths).toEqual(['skills/blockrun/'])
    expect(guidance.sourceUrl).toBe('https://github.com/example/repo')
    expect(guidance.copyText).toBeNull()
  })

  it('supports legacy branch + path skill installs', () => {
    const item = makeItem({
      id: 'claude-opus-4-5-migration-skill',
      install: {
        method: 'git_clone',
        repo: 'anthropics/claude-code',
        branch: 'main',
        path: 'plugins/claude-opus-4-5-migration/skills/claude-opus-4-5-migration',
      },
    })

    const guidance = buildInstallGuidance(item, 'zh')

    expect(guidance.kind).toBe('skill_extract')
    if (guidance.kind !== 'skill_extract') {
      throw new Error(`Expected skill_extract guidance, got ${guidance.kind}`)
    }
    expect(guidance.repo).toBe('anthropics/claude-code')
    expect(guidance.branch).toBe('main')
    expect(guidance.paths).toEqual(['plugins/claude-opus-4-5-migration/skills/claude-opus-4-5-migration'])
    expect(guidance.sourceUrl).toBe('https://github.com/example/repo')
    expect(guidance.copyText).toBeNull()
  })

  it('falls back to full clone only when repo is the only selector', () => {
    const item = makeItem({
      install: {
        method: 'git_clone',
        repo: 'https://github.com/example/repo.git',
      },
    })

    const guidance = buildInstallGuidance(item, 'en')

    expect(guidance.kind).toBe('git_clone')
    if (guidance.kind !== 'git_clone') {
      throw new Error(`Expected git_clone guidance, got ${guidance.kind}`)
    }
    expect(guidance.copyText).toBe('git clone https://github.com/example/repo.git')
  })

  it('builds plugin_marketplace guidance with two slash commands', () => {
    const item = makeItem({
      id: 'anthropic-superpowers',
      type: 'plugin',
      install: {
        method: 'plugin_marketplace',
        marketplace: 'anthropics/claude-plugins-official',
        plugin_name: 'superpowers',
      },
    })

    const guidance = buildInstallGuidance(item, 'en')

    expect(guidance.kind).toBe('plugin_marketplace')
    if (guidance.kind !== 'plugin_marketplace') {
      throw new Error(`Expected plugin_marketplace guidance, got ${guidance.kind}`)
    }
    expect(guidance.addCommand).toBe('/plugin marketplace add anthropics/claude-plugins-official')
    expect(guidance.installCommand).toBe('/plugin install superpowers@anthropics/claude-plugins-official')
    expect(guidance.copyText).toBe(
      '/plugin marketplace add anthropics/claude-plugins-official\n/plugin install superpowers@anthropics/claude-plugins-official',
    )
    expect(guidance.marketplace).toBe('anthropics/claude-plugins-official')
    expect(guidance.pluginName).toBe('superpowers')
  })

  it('falls back to unsupported when plugin_marketplace lacks marketplace or plugin_name', () => {
    const item = makeItem({
      type: 'plugin',
      install: { method: 'plugin_marketplace', marketplace: '' },
    })
    expect(buildInstallGuidance(item, 'en').kind).toBe('unsupported')
  })

  it('keeps download_file guidance intact', () => {
    const item = makeItem({
      type: 'rule',
      install: {
        method: 'download_file',
        files: ['https://example.com/rule.md'],
      },
    })

    const guidance = buildInstallGuidance(item, 'zh')

    expect(guidance.kind).toBe('download_file')
    if (guidance.kind !== 'download_file') {
      throw new Error(`Expected download_file guidance, got ${guidance.kind}`)
    }
    expect(guidance.copyText).toContain('curl -sL')
    expect(guidance.targetFile).toBe('.claude/rules/test-skill.md')
  })

  it('matches the real repo + files[] sample from catalog', () => {
    const catalog = JSON.parse(
      readFileSync(resolve(__dirname, '../../../catalog/index.json'), 'utf-8'),
    ) as CatalogItem[]
    const item = catalog.find(entry => entry.id === 'blockrun-agskill')

    expect(item).toBeTruthy()

    const guidance = buildInstallGuidance(item!, 'en')

    expect(guidance.kind).toBe('skill_extract')
    if (guidance.kind !== 'skill_extract') {
      throw new Error(`Expected skill_extract guidance, got ${guidance.kind}`)
    }
    expect(guidance.repo).toBe('https://github.com/sickn33/antigravity-awesome-skills.git')
    expect(guidance.paths).toEqual(['skills/blockrun/'])
    expect(guidance.sourceUrl).toBe('https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/blockrun')
  })

  it('matches the real legacy repo + branch + path sample from catalog', () => {
    const catalog = JSON.parse(
      readFileSync(resolve(__dirname, '../../../catalog/index.json'), 'utf-8'),
    ) as CatalogItem[]
    const item = catalog.find(entry => entry.id === 'claude-opus-4-5-migration-skill')

    expect(item).toBeTruthy()

    const guidance = buildInstallGuidance(item!, 'zh')

    expect(guidance.kind).toBe('skill_extract')
    if (guidance.kind !== 'skill_extract') {
      throw new Error(`Expected skill_extract guidance, got ${guidance.kind}`)
    }
    expect(guidance.repo).toBe('anthropics/claude-code')
    expect(guidance.branch).toBe('main')
    expect(guidance.paths).toEqual(['plugins/claude-opus-4-5-migration/skills/claude-opus-4-5-migration'])
    expect(guidance.sourceUrl).toBe('https://github.com/anthropics/claude-code/tree/main/plugins/claude-opus-4-5-migration/skills/claude-opus-4-5-migration')
  })
})
