import { useI18n } from '../hooks/useI18n'

const SOURCES = [
  { name: 'awesome-mcp-zh', url: 'https://github.com/punkpeye/awesome-mcp-servers' },
  { name: 'mcp.so', url: 'https://mcp.so' },
  { name: 'Anthropic Skills', url: 'https://github.com/anthropics/skills' },
  { name: 'Ai-Agent-Skills', url: 'https://github.com/skillcreatorai/Ai-Agent-Skills' },
  { name: 'awesome-cursorrules', url: 'https://github.com/PatrickJS/awesome-cursorrules' },
  { name: 'Rules 2.1', url: 'https://github.com/Mr-chen-05/rules-2.1-optimized' },
  { name: 'prompts.chat', url: 'https://github.com/f/prompts.chat' },
  { name: 'wonderful-prompts', url: 'https://github.com/langgptai/wonderful-prompts' },
  { name: 'GitHub Search', url: 'https://github.com/search' },
]

export default function About() {
  const { t } = useI18n()

  return (
    <div className="max-w-2xl mx-auto space-y-8">
      <h1 className="text-3xl font-bold text-gray-900 dark:text-white">{t('about.title')}</h1>
      <p className="text-gray-600 dark:text-gray-300 leading-relaxed">{t('about.description')}</p>

      <div className="glass rounded-2xl p-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">{t('about.sources')}</h2>
        <ul className="space-y-2">
          {SOURCES.map(s => (
            <li key={s.name}>
              <a href={s.url} target="_blank" rel="noreferrer"
                className="text-apple-blue hover:underline text-sm">
                {s.name}
              </a>
            </li>
          ))}
        </ul>
      </div>

      <div className="glass rounded-2xl p-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">{t('about.github')}</h2>
        <a href="https://github.com/anthropics/coding-hub" target="_blank" rel="noreferrer"
          className="text-apple-blue hover:underline">
          github.com/anthropics/coding-hub
        </a>
      </div>
    </div>
  )
}
