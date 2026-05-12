import { useI18n } from '../hooks/useI18n'
import type { CatalogItem } from '../types'

type InstallState = NonNullable<CatalogItem['mcp_install_state']>

const STATE_STYLES: Record<InstallState, { emoji: string; container: string; label: string; reason: string }> = {
  ready: {
    emoji: '✅',
    container: 'bg-emerald-100 dark:bg-emerald-900/40',
    label: 'text-emerald-800 dark:text-emerald-200',
    reason: 'text-emerald-900/70 dark:text-emerald-100/70',
  },
  needs_config: {
    emoji: '⚙️',
    container: 'bg-amber-100 dark:bg-amber-900/40',
    label: 'text-amber-800 dark:text-amber-200',
    reason: 'text-amber-900/70 dark:text-amber-100/70',
  },
  manual: {
    emoji: '📖',
    container: 'bg-sky-100 dark:bg-sky-900/40',
    label: 'text-sky-800 dark:text-sky-200',
    reason: 'text-sky-900/70 dark:text-sky-100/70',
  },
  invalid: {
    emoji: '❌',
    container: 'bg-rose-100 dark:bg-rose-900/40',
    label: 'text-rose-800 dark:text-rose-200',
    reason: 'text-rose-900/70 dark:text-rose-100/70',
  },
  unknown: {
    emoji: '❓',
    container: 'bg-gray-100 dark:bg-gray-700',
    label: 'text-gray-700 dark:text-gray-300',
    reason: 'text-gray-600/80 dark:text-gray-400/80',
  },
}

interface Props {
  item: CatalogItem
}

export default function McpInstallabilityBanner({ item }: Props) {
  const { t } = useI18n()

  // Skip rendering entirely when no installability signal is present —
  // keeps non-mcp types and pre-evaluation entries clean.
  if (!item.mcp_install_state) return null

  const state = item.mcp_install_state
  const styles = STATE_STYLES[state] ?? STATE_STYLES.unknown
  const tags = item.mcp_validation_tags ?? []
  const hasDiagnostics = tags.length > 0 || item.mcp_schema_valid !== undefined

  return (
    <div className={`rounded-xl px-4 py-3 mb-4 ${styles.container}`}>
      <div className={`flex items-center gap-2 font-semibold text-sm ${styles.label}`}>
        <span aria-hidden>{styles.emoji}</span>
        <span>{t(`mcp.installability.state.${state}`)}</span>
      </div>
      {item.mcp_installability_reason && (
        <p className={`mt-1.5 text-xs leading-relaxed ${styles.reason}`}>
          {item.mcp_installability_reason}
        </p>
      )}
      {hasDiagnostics && (
        <details className="mt-2 text-xs">
          <summary className={`cursor-pointer ${styles.reason} hover:opacity-80 select-none`}>
            {t('mcp.installability.diagnostics')}
            {item.mcp_schema_valid !== undefined && (
              <span className="ml-2 opacity-70">
                · {t(item.mcp_schema_valid ? 'mcp.installability.schemaValid' : 'mcp.installability.schemaInvalid')}
              </span>
            )}
          </summary>
          {tags.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {tags.map(tag => (
                <span
                  key={tag}
                  className={`px-2 py-0.5 rounded-full font-mono text-[10px] bg-white/40 dark:bg-black/20 ${styles.reason}`}
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </details>
      )}
    </div>
  )
}
