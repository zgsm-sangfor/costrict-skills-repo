import { useI18n } from '../hooks/useI18n'
import type { CatalogItem, RiskLevel } from '../types'

const RISK_STYLES: Record<RiskLevel, { emoji: string; container: string; label: string; body: string }> = {
  clean: {
    emoji: '🛡️',
    container: 'bg-emerald-100 dark:bg-emerald-900/40',
    label: 'text-emerald-800 dark:text-emerald-200',
    body: 'text-emerald-900/70 dark:text-emerald-100/70',
  },
  low: {
    emoji: '✅',
    container: 'bg-sky-100 dark:bg-sky-900/40',
    label: 'text-sky-800 dark:text-sky-200',
    body: 'text-sky-900/70 dark:text-sky-100/70',
  },
  medium: {
    emoji: '⚠️',
    container: 'bg-amber-100 dark:bg-amber-900/40',
    label: 'text-amber-800 dark:text-amber-200',
    body: 'text-amber-900/70 dark:text-amber-100/70',
  },
  high: {
    emoji: '🛑',
    container: 'bg-rose-100 dark:bg-rose-900/40',
    label: 'text-rose-800 dark:text-rose-200',
    body: 'text-rose-900/70 dark:text-rose-100/70',
  },
  extreme: {
    emoji: '☠️',
    container: 'bg-red-200 dark:bg-red-900/60',
    label: 'text-red-900 dark:text-red-100',
    body: 'text-red-900/80 dark:text-red-100/80',
  },
}

interface Props {
  item: CatalogItem
}

/**
 * Renders the per-entry security audit produced by ai-resource-eval's
 * security_scan task. Layout mirrors McpInstallabilityBanner so the Detail
 * page keeps a consistent visual rhythm. Skips rendering when no security
 * block is present — that's the "not yet evaluated" state (spec D7).
 */
export default function SecurityBanner({ item }: Props) {
  const { t } = useI18n()
  const security = item.security
  if (!security) return null

  const styles = RISK_STYLES[security.risk_level] ?? RISK_STYLES.low
  const { red_flags, permissions, recommendations, summary, verdict } = security
  const hasPermissions =
    permissions &&
    ((permissions.files?.length ?? 0) > 0 ||
      (permissions.network?.length ?? 0) > 0 ||
      (permissions.commands?.length ?? 0) > 0)

  return (
    <div className={`rounded-xl px-4 py-3 mb-4 ${styles.container}`}>
      <div className={`flex items-center justify-between gap-2 font-semibold text-sm ${styles.label}`}>
        <div className="flex items-center gap-2">
          <span aria-hidden>{styles.emoji}</span>
          <span>{t('security.title')}</span>
          <span className="opacity-70 font-normal">·</span>
          <span>{t(`security.risk.${security.risk_level}`)}</span>
        </div>
        <span className={`text-[10px] font-mono uppercase tracking-wide px-2 py-0.5 rounded-full bg-white/40 dark:bg-black/20 ${styles.body}`}>
          {t(`security.verdict.${verdict}`)}
        </span>
      </div>

      {summary && (
        <p className={`mt-1.5 text-xs leading-relaxed ${styles.body}`}>{summary}</p>
      )}

      {red_flags && red_flags.length > 0 && (
        <div className="mt-2">
          <div className={`text-[11px] font-medium mb-1 ${styles.label}`}>{t('security.redFlags')}</div>
          <ul className={`text-xs leading-relaxed list-disc list-inside space-y-0.5 ${styles.body}`}>
            {red_flags.map((flag, i) => (
              <li key={i}>{flag}</li>
            ))}
          </ul>
        </div>
      )}

      {hasPermissions && (
        <details className="mt-2 text-xs">
          <summary className={`cursor-pointer ${styles.body} hover:opacity-80 select-none`}>
            {t('security.permissions')}
          </summary>
          <div className="mt-2 space-y-1">
            {permissions.files?.length > 0 && (
              <PermissionsRow label={t('security.permissions.files')} items={permissions.files} styles={styles} />
            )}
            {permissions.network?.length > 0 && (
              <PermissionsRow label={t('security.permissions.network')} items={permissions.network} styles={styles} />
            )}
            {permissions.commands?.length > 0 && (
              <PermissionsRow label={t('security.permissions.commands')} items={permissions.commands} styles={styles} />
            )}
          </div>
        </details>
      )}

      {recommendations && recommendations.length > 0 && (
        <details className="mt-2 text-xs">
          <summary className={`cursor-pointer ${styles.body} hover:opacity-80 select-none`}>
            {t('security.recommendations')}
          </summary>
          <ul className={`mt-1 list-disc list-inside space-y-0.5 ${styles.body}`}>
            {recommendations.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </details>
      )}

      {security.scan_model && (
        <div className={`mt-2 text-[10px] font-mono opacity-60 ${styles.body}`}>
          {t('security.scanModel')}: {security.scan_model}
          {security.scanned_at && ` · ${new Date(security.scanned_at).toLocaleDateString()}`}
        </div>
      )}
    </div>
  )
}

interface PermissionsRowProps {
  label: string
  items: string[]
  styles: { body: string; label: string }
}

function PermissionsRow({ label, items, styles }: PermissionsRowProps) {
  return (
    <div className="flex gap-2">
      <div className={`shrink-0 w-16 text-[11px] font-medium ${styles.label}`}>{label}</div>
      <div className="flex flex-wrap gap-1">
        {items.map((value, i) => (
          <span
            key={i}
            className={`px-2 py-0.5 rounded-full font-mono text-[10px] bg-white/40 dark:bg-black/20 ${styles.body}`}
          >
            {value}
          </span>
        ))}
      </div>
    </div>
  )
}
