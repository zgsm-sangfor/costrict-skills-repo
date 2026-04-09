import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'

type Lang = 'en' | 'zh'

interface I18nContextValue {
  lang: Lang
  setLang: (lang: Lang) => void
  t: (key: string) => string
}

const translations: Record<string, Record<Lang, string>> = {
  'nav.home': { en: 'Home', zh: '首页' },
  'nav.browse': { en: 'Browse', zh: '浏览' },
  'nav.about': { en: 'About', zh: '关于' },
  'hero.title': { en: 'Coding Hub', zh: 'Coding Hub' },
  'hero.subtitle': { en: 'Discover 4000+ curated dev resources', zh: '发现 4000+ 精选开发资源' },
  'hero.search': { en: 'Search resources...', zh: '搜索资源...' },
  'stats.mcp': { en: 'MCP Servers', zh: 'MCP 服务' },
  'stats.skill': { en: 'Skills', zh: '技能' },
  'stats.rule': { en: 'Rules', zh: '规则' },
  'stats.prompt': { en: 'Prompts', zh: '提示词' },
  'featured.title': { en: 'Featured Picks', zh: '精选推荐' },
  'trending.title': { en: 'Trending', zh: '热门趋势' },
  'browse.all': { en: 'All', zh: '全部' },
  'browse.sort.score': { en: 'Score', zh: '评分' },
  'browse.sort.stars': { en: 'Stars', zh: 'Stars' },
  'browse.category': { en: 'Category', zh: '分类' },
  'browse.category.all': { en: 'All Categories', zh: '全部分类' },
  'search.loading': { en: 'Loading search index...', zh: '加载搜索索引...' },
  'search.placeholder': { en: 'Search by name or description...', zh: '按名称或描述搜索...' },
  'search.results': { en: 'results', zh: '个结果' },
  'search.noResults': { en: 'No results found', zh: '未找到结果' },
  'detail.health': { en: 'Health', zh: '健康度' },
  'detail.evaluation': { en: 'Evaluation', zh: '评估详情' },
  'detail.install': { en: 'Installation', zh: '安装指引' },
  'detail.install.copy': { en: 'Copy', zh: '复制' },
  'detail.install.copied': { en: 'Copied!', zh: '已复制!' },
  'detail.install.manual': { en: 'Follow the README for installation instructions', zh: '请参照 README 安装' },
  'detail.tags': { en: 'Tags', zh: '标签' },
  'detail.techStack': { en: 'Tech Stack', zh: '技术栈' },
  'detail.source': { en: 'Source', zh: '来源' },
  'detail.github': { en: 'View on GitHub', zh: '在 GitHub 查看' },
  'detail.lastCommit': { en: 'Last commit', zh: '最近提交' },
  'about.title': { en: 'About Coding Hub', zh: '关于 Coding Hub' },
  'about.description': { en: 'Coding Hub aggregates 4000+ curated MCP Servers, Skills, Rules, and Prompts from 9 upstream sources, updated weekly via CI.', zh: 'Coding Hub 聚合了来自 9 个上游源的 4000+ 精选 MCP 服务、技能、规则和提示词，每周通过 CI 自动更新。' },
  'about.sources': { en: 'Data Sources', zh: '数据源' },
  'about.github': { en: 'GitHub Repository', zh: 'GitHub 仓库' },
  'loading': { en: 'Loading...', zh: '加载中...' },
  'error': { en: 'Failed to load data', zh: '数据加载失败' },
  // Health radar chart labels
  'health.popularity': { en: 'Popularity', zh: '流行度' },
  'health.freshness': { en: 'Freshness', zh: '活跃度' },
  'health.quality': { en: 'Quality', zh: '质量' },
  'health.installability': { en: 'Installability', zh: '可安装性' },
  // Evaluation dimension labels
  'eval.coding_relevance': { en: 'Coding Relevance', zh: '编程相关性' },
  'eval.content_quality': { en: 'Content Quality', zh: '内容质量' },
  'eval.specificity': { en: 'Specificity', zh: '专业度' },
  'eval.source_trust': { en: 'Source Trust', zh: '来源可信度' },
  'eval.confidence': { en: 'Confidence', zh: '置信度' },
  'eval.evaluator': { en: 'Evaluator', zh: '评估模型' },
  // Category labels
  'cat.tooling': { en: 'Tooling', zh: '工具' },
  'cat.ai-ml': { en: 'AI & ML', zh: 'AI & 机器学习' },
  'cat.backend': { en: 'Backend', zh: '后端' },
  'cat.frontend': { en: 'Frontend', zh: '前端' },
  'cat.devops': { en: 'DevOps', zh: 'DevOps' },
  'cat.security': { en: 'Security', zh: '安全' },
  'cat.documentation': { en: 'Documentation', zh: '文档' },
  'cat.testing': { en: 'Testing', zh: '测试' },
  'cat.database': { en: 'Database', zh: '数据库' },
  'cat.mobile': { en: 'Mobile', zh: '移动端' },
  'cat.fullstack': { en: 'Full Stack', zh: '全栈' },
  // Featured section titles (Chinese mapping)
  'featured.Browser & Automation': { en: 'Browser & Automation', zh: '浏览器 & 自动化' },
  'featured.Git & Collaboration': { en: 'Git & Collaboration', zh: 'Git & 协作' },
  'featured.DevOps & Security': { en: 'DevOps & Security', zh: 'DevOps & 安全' },
  'featured.Documentation & Knowledge': { en: 'Documentation & Knowledge', zh: '文档 & 知识管理' },
  'featured.Frontend & Design': { en: 'Frontend & Design', zh: '前端 & 设计' },
  'featured.Backend & Databases': { en: 'Backend & Databases', zh: '后端 & 数据库' },
  'featured.AI & MCP Development': { en: 'AI & MCP Development', zh: 'AI & MCP 开发' },
}

const I18nContext = createContext<I18nContextValue | null>(null)

function detectLang(): Lang {
  const saved = localStorage.getItem('lang')
  if (saved === 'en' || saved === 'zh') return saved
  return navigator.language.startsWith('zh') ? 'zh' : 'en'
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(detectLang)

  const setLang = (l: Lang) => {
    setLangState(l)
    localStorage.setItem('lang', l)
  }

  useEffect(() => {
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en'
  }, [lang])

  const t = (key: string) => translations[key]?.[lang] ?? key

  return (
    <I18nContext.Provider value={{ lang, setLang, t }}>
      {children}
    </I18nContext.Provider>
  )
}

export function useI18n() {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error('useI18n must be used within I18nProvider')
  return ctx
}
