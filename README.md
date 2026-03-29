# Coding Hub

<div align="center">
<img src="assets/title-card.jpg" alt="Coding Hub" />

<p><strong>5000+ 精选开发资源一站式索引</strong><br/>MCP Servers · Skills · Rules · Prompts</p>

<p>
  <a href="https://github.com/zgsm-sangfor/costrict-coding-hub/stargazers"><img src="https://img.shields.io/github/stars/zgsm-sangfor/costrict-coding-hub?style=flat-square&color=4A90D9" alt="Stars" /></a>
  <a href="https://github.com/zgsm-sangfor/costrict-coding-hub/blob/main/LICENSE"><img src="https://img.shields.io/github/license/zgsm-sangfor/costrict-coding-hub?style=flat-square" alt="License" /></a>
  <a href="https://github.com/zgsm-sangfor/costrict-coding-hub/commits/main"><img src="https://img.shields.io/github/last-commit/zgsm-sangfor/costrict-coding-hub?style=flat-square" alt="Last Commit" /></a>
  <img src="https://img.shields.io/badge/resources-5061-2ECC71?style=flat-square" alt="Resources" />
</p>

<p>
  <a href="#-精选推荐">精选推荐</a> ·
  <a href="#quick-start">Quick Start</a> ·
  <a href="#features">Features</a> ·
  <a href="#platforms">Platforms</a> ·
  <a href="#for-agents">For Agents</a> ·
  <a href="#contributing">Contributing</a>
</p>

</div>

## Why Coding Hub?

AI Coding Agent 越来越强，但找到合适的 MCP Server、Skill、Rule 仍然是碎片化的。

Coding Hub 从 9 个上游源自动聚合、过滤、评估，让你和你的 Agent **一条命令就能搜索和安装**开发资源。

## Quick Start

一条命令安装，指定你的平台：

**macOS / Linux：**

```bash
# Costrict CLI（在项目根目录执行）
curl -fsSL https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.sh | bash -s -- --platform costrict

# VSCode Costrict 插件
curl -fsSL https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.sh | bash -s -- --platform vscode-costrict

# Claude Code
curl -fsSL https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.sh | bash -s -- --platform claude-code

# Opencode（在项目根目录执行）
curl -fsSL https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.sh | bash -s -- --platform opencode
```

**Windows (PowerShell)：**

```powershell
# Costrict CLI
irm https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.ps1 | iex

# 指定平台（如自动检测失败）
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.ps1))) -Platform costrict
```

安装完成后试试：

```bash
# Claude Code
/coding-hub:search typescript

# Opencode / Costrict CLI / VSCode Costrict (Roo Code)
/coding-hub-search typescript
```

或者复制以下 prompt 丢给你的 AI Agent：

```
你是一个自动化安装助手。请访问以下 URL 并阅读其中的 "For Agents" 部分，
严格按照步骤完成 coding-hub 技能的安装。

不要 clone 整个仓库，只需要读取这个 raw URL 的内容：
https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/README.md

根据你所在的平台（Claude Code / Opencode / Costrict CLI / VSCode Costrict），
执行对应的安装命令。安装完成后告诉我结果。
```

---


## ⭐ 精选推荐

> 从 1400+ 资源中按 Star 数、活跃度、技术栈自动筛选。每周随索引同步更新。
>
> 💡 安装后使用 `/coding-hub:search <关键词>` 搜索完整索引，或 `/coding-hub:recommend` 获取基于项目的智能推荐。

### 🔌 MCP Servers

MCP (Model Context Protocol) 让 AI 能够访问外部工具和数据源。以下按 Star 数精选最受欢迎的服务器：

**1. [microsoft/markitdown](https://github.com/microsoft/markitdown/tree/main/packages/markitdown-mcp)**

> MarkItDown MCP 工具访问 - 一个将多种文件格式（本地或远程）转换为 Markdown 以供 LLM 使用的库。

⭐ **92.7k** · 📅 2026-03

**2. [Everything](https://github.com/modelcontextprotocol/servers/blob/main/src/everything)**

> Reference / test server with prompts, resources, and tools

⭐ **82.3k** · 📅 2026-03

**3. [Context 7](https://github.com/upstash/context7-mcp)**

> Context7 MCP - Up-to-date Docs For Any Cursor Prompt

⭐ **50.8k** · 📅 2026-03

**4. [Homebrew](https://github.com/Homebrew/brew/blob/HEAD/Library/Homebrew/mcp_server.rb)**

> An MCP server for the Homebrew package manager.

⭐ **47.2k** · 📅 2026-03 · `homebrew` `package-manager` `mcp-server`

**5. [microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp)**

> 微软官方出品，使用 Playwright 让 AI 精确控制网页，自动化抓取数据。

⭐ **29.8k** · 📅 2026-03 · `playwright`


**更多按技术栈分类：**

<details>
<summary>🔒 安全（1 个）</summary>

| 名称 | 描述 | ⭐ Stars | 标签 |
|------|------|---------|------|
| [FastAPI-MCP](https://github.com/tadata-org/fastapi_mcp) | Expose your FastAPI endpoints as Model Context Protocol (MCP) tools... | 11.7k | `ai` `authentication` `mcp` |

</details>

<details>
<summary>📱 移动开发（1 个）</summary>

| 名称 | 描述 | ⭐ Stars | 标签 |
|------|------|---------|------|
| [oraios/serena](https://github.com/oraios/serena) | 功能齐全的编码代理，依赖于使用语言服务器的符号化代码操作。 | 22.2k |  |

</details>

<details>
<summary>🗄️ 数据库（2 个）</summary>

| 名称 | 描述 | ⭐ Stars | 标签 |
|------|------|---------|------|
| [mediar-ai/screenpipe](https://github.com/mediar-ai/screenpipe) | 本地优先系统，捕获屏幕/音频并带时间戳索引，SQL/嵌入存储，语义搜索，LLM 历史分析，事件触发动作。通过 NextJS 插件生态系... | 17.6k | `nextjs` |
| [InstantDB](https://github.com/instantdb/instant/tree/main/client/packages/mcp) | Create, manage, and update applications on InstantDB, the modern Fi... | 9.8k |  |

</details>

<details>
<summary>🔧 自动化 / 浏览器（4 个）</summary>

| 名称 | 描述 | ⭐ Stars | 标签 |
|------|------|---------|------|
| [modelcontextprotocol/server-puppeteer](https://github.com/modelcontextprotocol/servers/tree/main/src/puppeteer) | 官方参考实现，使用 Puppeteer 进行浏览器自动化和网页抓取。 | 82.3k |  |
| [ScrapeGraphAI](https://github.com/ScrapeGraphAI/Scrapegraph-ai) | AI-powered web scraping library that creates scraping pipelines usi... | 23.1k |  |
| [Skyvern](https://github.com/Skyvern-AI/skyvern/tree/main/integrations/mcp) | MCP Server to let Claude / your AI control the browser | 21.0k |  |
| [Playwright MCP](https://github.com/microsoft/playwright-mcp) | Browser automation via Playwright accessibility snapshots for LLMs | 8.8k | `browser` `automation` `e2e` |

</details>

<details>
<summary>🐙 Git / GitHub（3 个）</summary>

| 名称 | 描述 | ⭐ Stars | 标签 |
|------|------|---------|------|
| [modelcontextprotocol/server-github](https://github.com/modelcontextprotocol/servers/tree/main/src/github) | 官方参考实现，集成 GitHub API，管理仓库、文件、PR 和 Issues。 | 82.3k | `git` |
| [github/github-mcp-server](https://github.com/github/github-mcp-server) | GitHub 官方出品，让 AI 通过 API 深度集成 GitHub，实现自动化工作流等。 | 28.3k | `git` |
| [Agent Reach](https://github.com/Panniantong/Agent-Reach) | 一句话给 AI Agent 装上全网搜索能力。一键安装 + 配置 13+ 平台工具（Twitter、Reddit、YouTube、Gi... | 11.0k | `git` |

</details>

<details>
<summary>🤖 AI / ML（5 个）</summary>

| 名称 | 描述 | ⭐ Stars | 标签 |
|------|------|---------|------|
| [FastMCP v2 🚀](https://github.com/jlowin/fastmcp) | 🚀 The fast, Pythonic way to build MCP servers and clients | 24.0k | `agent` `mcp` `llm` |
| [Blender](https://github.com/ahujasid/blender-mcp) | BlenderMCP connects Blender to Claude AI through the Model Context ... | 18.0k | `blender` `3d-modeling` `AI-integration` |
| [cognee-mcp](https://github.com/topoteretes/cognee/tree/main/cognee-mcp) | GraphRAG 记忆服务器，支持自定义摄取、数据处理和搜索。 | 14.7k |  |
| [Cua](https://github.com/trycua/cua/tree/main/libs/mcp-server) | MCP server for the Computer-Use Agent (CUA), allowing you to run CU... | 13.3k |  |
| [MCP Go 🚀](https://github.com/mark3labs/mcp-go) | A Go implementation of the Model Context Protocol (MCP), enabling s... | 8.4k |  |

</details>

<details>
<summary>🚀 DevOps / CI（4 个）</summary>

| 名称 | 描述 | ⭐ Stars | 标签 |
|------|------|---------|------|
| [Nginx UI](https://github.com/0xJacky/nginx-ui) | Yet another WebUI for Nginx | 10.9k | `go` `windows` `macos` |
| [AWS Bedrock KB Retrieval](https://github.com/awslabs/mcp/tree/main/src/bedrock-kb-retrieval-mcp-server) | Query Amazon Bedrock Knowledge Bases using natural language to retr... | 8.6k | `aws` |
| [AWS CDK](https://github.com/awslabs/mcp/tree/main/src/cdk-mcp-server) | Get prescriptive CDK advice, explain CDK Nag rules, check suppressi... | 8.6k | `aws` |
| [AWS Cost Analysis](https://github.com/awslabs/mcp/tree/main/src/cost-analysis-mcp-server) | Analyze CDK projects to identify AWS services used and get pricing ... | 8.6k | `aws` |

</details>

<details>
<summary>🎨 前端开发（3 个）</summary>

| 名称 | 描述 | ⭐ Stars | 标签 |
|------|------|---------|------|
| [modelcontextprotocol/server-fetch](https://github.com/modelcontextprotocol/servers/tree/main/src/fetch) | 官方参考实现，灵活获取网页内容（HTML/JSON/MD），并为 AI 处理优化。 | 82.3k |  |
| [Mastra/mcp](https://github.com/mastra-ai/mastra/tree/main/packages/mcp) | Client implementation for Mastra, providing seamless integration wi... | 22.4k |  |
| [Framelink Figma MCP Server](https://github.com/GLips/Figma-Context-MCP) | MCP server to provide Figma layout information to AI coding agents ... | 14.0k | `typescript` `ai` `mcp` |

</details>

<details>
<summary>⚙️ 后端开发（5 个）</summary>

| 名称 | 描述 | ⭐ Stars | 标签 |
|------|------|---------|------|
| [Mastra/mcp-docs-server](https://github.com/mastra-ai/mastra/tree/main/packages/mcp-docs-server) | Provides AI assistants with direct access to Mastra.ai's complete k... | 22.4k |  |
| [pydantic/pydantic-ai/mcp-run-python](https://github.com/pydantic/pydantic-ai/tree/main/mcp-run-python) | Pydantic 出品，在安全的沙盒环境中运行 Python 代码，适合开发编程代理。 | 15.9k | `python` |
| [googleapis/genai-toolbox](https://github.com/googleapis/genai-toolbox) | Google 官方开源 MCP 服务器，专注于为数据库提供简单、快速、安全的工具。 | 13.6k | `go` |
| [PipedreamHQ/pipedream](https://github.com/PipedreamHQ/pipedream/tree/master/modelcontextprotocol) | Pipedream 官方集成，一站式连接 2500+ API，集成 8000+ 工具，并管理用户服务器。 | 11.2k |  |
| [MCP Inspector](https://github.com/modelcontextprotocol/inspector) | Visual testing tool for MCP servers | 9.2k |  |

</details>

<details>
<summary>🛠️ 其他工具（2 个）</summary>

| 名称 | 描述 | ⭐ Stars | 标签 |
|------|------|---------|------|
| [topoteretes/cognee](https://github.com/topoteretes/cognee/tree/dev/cognee-mcp) | 使用各种图和向量存储的 AI 应用和 Agents 记忆管理器，允许从 30+ 数据源摄取。 (cognee-mcp 的开发分支) | 14.7k |  |
| [Inbox Zero](https://github.com/elie222/inbox-zero/tree/main/apps/mcp-server) | Inbox Zero 官方集成，AI 个人邮件助手 (基于 Gmail，提供需回复/需跟进邮件识别等功能)。 | 10.3k |  |

</details>

### 🎯 Skills

Skills 扩展 AI Agent 的专业能力。精选来自 Anthropic 官方、HuggingFace 和社区的高质量技能：

**1. [algorithmic-art](https://github.com/anthropics/skills/tree/main/skills/algorithmic-art)**

> Creating algorithmic art using p5.js with seeded randomness and interactive parameter exploration. Use this when user...

📅 2026-03 · `go` `anthropic` `official`

**2. [brand-guidelines](https://github.com/anthropics/skills/tree/main/skills/brand-guidelines)**

> Applies Anthropic's official brand colors and typography to any sort of artifact that may benefit from having Anthrop...

📅 2026-03 · `anthropic` `official`

**3. [canvas-design](https://github.com/anthropics/skills/tree/main/skills/canvas-design)**

> Create beautiful visual art in .png and .pdf documents using design philosophy. You should use this skill when the us...

📅 2026-03 · `anthropic` `official`


**更多按技术栈分类：**

<details>
<summary>📝 文档 / 写作（2 个）</summary>

| 名称 | 描述 | 来源 | 标签 |
|------|------|------|------|
| [database-design](https://github.com/skillcreatorai/Ai-Agent-Skills/tree/main/skills/database-design) | Database schema design, optimization, and migration patterns for Po... | ai-agent-skills | `postgres` `mysql` |
| [code-documentation](https://github.com/skillcreatorai/Ai-Agent-Skills/tree/main/skills/code-documentation) | Writing effective code documentation - API docs, README files, inli... | ai-agent-skills |  |

</details>

<details>
<summary>🗄️ 数据库（1 个）</summary>

| 名称 | 描述 | 来源 | 标签 |
|------|------|------|------|
| [backend-development](https://github.com/skillcreatorai/Ai-Agent-Skills/tree/main/skills/backend-development) | Backend API design, database architecture, microservices patterns, ... | ai-agent-skills |  |

</details>

<details>
<summary>🔧 自动化 / 浏览器（1 个）</summary>

| 名称 | 描述 | 来源 | 标签 |
|------|------|------|------|
| [llm-application-dev](https://github.com/skillcreatorai/Ai-Agent-Skills/tree/main/skills/llm-application-dev) | Building applications with Large Language Models - prompt engineeri... | ai-agent-skills |  |

</details>

<details>
<summary>🤖 AI / ML（1 个）</summary>

| 名称 | 描述 | 来源 | 标签 |
|------|------|------|------|
| [claude-api](https://github.com/anthropics/skills/tree/main/skills/claude-api) | Build apps with the Claude API or Anthropic SDK. TRIGGER when: code... | anthropics-skills | `openai` `anthropic` `official` |

</details>

### 📋 Rules

编码规范和 AI 辅助规则，帮你的 Agent 写出更规范的代码：

<details>
<summary>🔒 安全（1 个）</summary>

| 名称 | 描述 | 来源 | 标签 |
|------|------|------|------|
| [Security Audit Rules](https://github.com/Mr-chen-05/rules-2.1-optimized/tree/master/project-rules) | AI-assisted security review rules covering OWASP, input validation,... | curated | `security` `audit` `owasp` |

</details>

<details>
<summary>📱 移动开发（1 个）</summary>

| 名称 | 描述 | 来源 | 标签 |
|------|------|------|------|
| [Flutter & Dart Rules](https://github.com/PatrickJS/awesome-cursorrules/tree/main/rules/flutter-dart) | Cursor rules for Flutter and Dart development with best practices | curated | `flutter` `dart` `mobile` |

</details>

<details>
<summary>📝 文档 / 写作（2 个）</summary>

| 名称 | 描述 | 来源 | 标签 |
|------|------|------|------|
| [Technical Documentation Rules](https://github.com/Mr-chen-05/rules-2.1-optimized/tree/master/project-rules) | AI rules for generating and maintaining technical documentation | curated | `documentation` `technical-writing` `api-docs` |
| [Create Docs (Rules 2.1)](https://github.com/Mr-chen-05/rules-2.1-optimized/tree/master/project-rules) | Comprehensive documentation generation - 全面的文档生成 | rules-2.1-optimized | `project rules` |

</details>

<details>
<summary>🗄️ 数据库（1 个）</summary>

| 名称 | 描述 | 来源 | 标签 |
|------|------|------|------|
| [Supabase Rules](https://github.com/PatrickJS/awesome-cursorrules/tree/main/rules/supabase) | Cursor rules for Supabase with PostgreSQL and Edge Functions | curated | `supabase` `postgres` `edge-functions` |

</details>

<details>
<summary>🐙 Git / GitHub（1 个）</summary>

| 名称 | 描述 | 来源 | 标签 |
|------|------|------|------|
| [Analyze Issue (Rules 2.1)](https://github.com/Mr-chen-05/rules-2.1-optimized/tree/master/project-rules) | GitHub issue analysis and implementation specification - GitHub问题分析... | rules-2.1-optimized | `git` `project rules` |

</details>

<details>
<summary>🎨 前端开发（1 个）</summary>

| 名称 | 描述 | 来源 | 标签 |
|------|------|------|------|
| [Frontend Dev (Rules 2.1)](https://github.com/Mr-chen-05/rules-2.1-optimized/tree/master/project-rules) | Frontend development workflow with Vue/React/TypeScript - 前端开发完整工作流 | rules-2.1-optimized | `react` `vue` `typescript` |

</details>

<details>
<summary>⚙️ 后端开发（1 个）</summary>

| 名称 | 描述 | 来源 | 标签 |
|------|------|------|------|
| [Backend Dev (Rules 2.1)](https://github.com/Mr-chen-05/rules-2.1-optimized/tree/master/project-rules) | Backend development workflow with Java/Python/Node.js - 后端开发完整工作流 | rules-2.1-optimized | `python` `java` `nodejs` |

</details>

<details>
<summary>🛠️ 其他工具（7 个）</summary>

| 名称 | 描述 | 来源 | 标签 |
|------|------|------|------|
| [Ai Powered Code Review (Rules 2.1)](https://github.com/Mr-chen-05/rules-2.1-optimized/tree/master/project-rules) | AI驱动的智能代码审查规则 - 基于机器学习的代码质量分析和自动化审查流程 | rules-2.1-optimized | `project rules` |
| [Bug Fix (Rules 2.1)](https://github.com/Mr-chen-05/rules-2.1-optimized/tree/master/project-rules) | Complete bug-fixing workflow from issue to PR - 从问题到PR的完整Bug修复工作流 | rules-2.1-optimized | `project rules` |
| [Changelog Management (Rules 2.1)](https://github.com/Mr-chen-05/rules-2.1-optimized/tree/master/project-rules) | AI-powered changelog management with automatic generation and versi... | rules-2.1-optimized | `project rules` |
| [Code Quality Check (Rules 2.1)](https://github.com/Mr-chen-05/rules-2.1-optimized/tree/master/project-rules) | AI-powered cross-language code quality check with intelligent analy... | rules-2.1-optimized | `project rules` |
| [Code Review (Rules 2.1)](https://github.com/Mr-chen-05/rules-2.1-optimized/tree/master/project-rules) | Multi-role pull request review checklist - 多角色拉取请求审查清单 | rules-2.1-optimized | `project rules` |
| [Commit (Rules 2.1)](https://github.com/Mr-chen-05/rules-2.1-optimized/tree/master/project-rules) | Unified comprehensive commit workflow (standard + fast + AI) - 统一全面... | rules-2.1-optimized | `project rules` |
| [Context Loader (Rules 2.1)](https://github.com/Mr-chen-05/rules-2.1-optimized/tree/master/project-rules) | AI-powered intelligent project context loader with deep analysis - ... | rules-2.1-optimized | `project rules` |

</details>

### 💡 Prompts

开发者专用 Prompt，覆盖编码、调试、架构设计等场景：

<details>
<summary>🔒 安全（1 个）</summary>

| 名称 | 描述 | 来源 | 标签 |
|------|------|------|------|
| [Cyber Security Specialist](https://github.com/f/prompts.chat) | I want you to act as a cyber security specialist. I will provide so... | prompts-chat | `for-devs` |

</details>

<details>
<summary>🐙 Git / GitHub（1 个）</summary>

| 名称 | 描述 | 来源 | 标签 |
|------|------|------|------|
| [UX/UI Developer](https://github.com/f/prompts.chat) | I want you to act as a UX/UI developer. I will provide some details... | prompts-chat | `git` `for-devs` |

</details>

<details>
<summary>🤖 AI / ML（3 个）</summary>

| 名称 | 描述 | 来源 | 标签 |
|------|------|------|------|
| [资深编程专家 CAN](https://github.com/langgptai/wonderful-prompts) | 实测 GPT-4 才可以有比较好的效果，完整的对话：  [示例——CAN 完整对话](examples/gpt4_CAN_coder.... | wonderful-prompts | `chinese` |
| [编写函数(Python 为例)](https://github.com/langgptai/wonderful-prompts) | 使用 ChatGPT 编写 Python 函数计算三角形面积。给出 （1）函数描述；（2）函数定义；（3）函数输出。搭建如示例的代码框... | wonderful-prompts | `python` `chinese` |
| [模拟 Linux 终端](https://github.com/langgptai/wonderful-prompts) | 我想让你充当 Linux 终端。我将输入命令，您将回复终端应显示的内容。我希望您只在一个唯一的代码块内回复终端输出，而不是其他任何内容... | wonderful-prompts | `chinese` |

</details>

<details>
<summary>🚀 DevOps / CI（2 个）</summary>

| 名称 | 描述 | 来源 | 标签 |
|------|------|------|------|
| [Linux Terminal](https://github.com/f/prompts.chat) | I want you to act as a linux terminal. I will type commands and you... | prompts-chat | `for-devs` |
| [AI Trying to Escape the Box](https://github.com/f/prompts.chat) | [Caveat Emptor: After issuing this prompt you should then do someth... | prompts-chat | `docker` |

</details>

<details>
<summary>🎨 前端开发（2 个）</summary>

| 名称 | 描述 | 来源 | 标签 |
|------|------|------|------|
| [Fullstack Software Developer](https://github.com/f/prompts.chat) | Act as a fullstack developer with expertise in both frontend and ba... | curated | `fullstack` `web` `frontend` |
| [JavaScript Console](https://github.com/f/prompts.chat) | I want you to act as a javascript console. I will type commands and... | prompts-chat | `javascript` `java` `for-devs` |

</details>

<details>
<summary>⚙️ 后端开发（2 个）</summary>

| 名称 | 描述 | 来源 | 标签 |
|------|------|------|------|
| [编写正则表达式](https://github.com/langgptai/wonderful-prompts) | 我希望你充当正则表达式生成器。您的角色是生成匹配文本中特定模式的正则表达式。您应该以一种可以轻松复制并粘贴到支持正则表达式的文本编辑器... | wonderful-prompts | `python` `chinese` |
| [Instructor in a School](https://github.com/f/prompts.chat) | I want you to act as an instructor in a school, teaching algorithms... | prompts-chat | `python` `go` |

</details>

<details>
<summary>🛠️ 其他工具（4 个）</summary>

| 名称 | 描述 | 来源 | 标签 |
|------|------|------|------|
| [混淆代码翻译](https://github.com/langgptai/wonderful-prompts) | 分析这段代码是什么编程语言，功能是什么？然后翻译整段代码，把所有变量和函数都重命名，使其成为更加清晰易懂的代码 | wonderful-prompts | `chinese` |
| [Ethereum Developer](https://github.com/f/prompts.chat) | Imagine you are an experienced Ethereum developer tasked with creat... | prompts-chat | `for-devs` |
| [Excel Sheet](https://github.com/f/prompts.chat) | I want you to act as a text based excel. you'll only reply me the t... | prompts-chat | `for-devs` |
| [Web Design Consultant](https://github.com/f/prompts.chat) | I want you to act as a web design consultant. I will provide you wi... | prompts-chat | `for-devs` |

</details>


## Features

| 类型 | 数量 | 说明 |
|------|------|------|
| MCP Server | 4285 | Model Context Protocol 服务器 |
| Prompt | 512 | 开发者专用 Prompt |
| Rule | 236 | 编码规范 / AI 辅助规则 |
| Skill | 28 | Agent Skill 扩展 |

**数据来源**：从 9 个上游源自动聚合，每周通过 GitHub Actions 同步，过滤 star > 10 的 coding 相关资源。

| 上游 | 来源 |
|------|------|
| MCP | [awesome-mcp-servers](https://github.com/wong2/awesome-mcp-servers) · [Awesome-MCP-ZH](https://github.com/yzfly/Awesome-MCP-ZH) · [mcp.so](https://mcp.so) |
| Skills | [anthropics/skills](https://github.com/anthropics/skills) · [Ai-Agent-Skills](https://github.com/skillcreatorai/Ai-Agent-Skills) |
| Rules | [awesome-cursorrules](https://github.com/PatrickJS/awesome-cursorrules) · [rules-2.1-optimized](https://github.com/Mr-chen-05/rules-2.1-optimized) |
| Prompts | [prompts.chat](https://github.com/f/prompts.chat) · [wonderful-prompts](https://github.com/langgptai/wonderful-prompts) |

### 📊 质量筛选标准

我们通过三层过滤确保资源质量：

**第一层：基础过滤**
- ⭐ Star 数 > 10（活跃度指标）
- 📅 最近 6 个月有更新（维护状态）
- 🏷️ 明确标注为 coding 相关

**第二层：分类评估**

| 类型 | 筛选策略 |
|------|---------|
| **MCP Servers** | 从 awesome-mcp-servers + Awesome-MCP-ZH + mcp.so 聚合，按独立仓库去重 |
| **Skills** | Tier 1: anthropics/skills + Ai-Agent-Skills（全量）<br/>Tier 2: GitHub 搜索 + LLM 质量评估（TOP 300）<br/>Tier 3: 手工精选（curated.json） |
| **Rules** | awesome-cursorrules + rules-2.1-optimized，优先实用性和标签丰富度 |
| **Prompts** | prompts.chat + wonderful-prompts，优先 coding 相关和中文资源 |

**第三层：持续更新**
- 🤖 每周自动同步（GitHub Actions）
- 🔄 自动去重和合并
- 📈 动态更新 star 数和活跃度


## Platforms

支持四个 AI Coding 平台，命令格式略有差异：

| | Costrict | Opencode | Claude Code | VSCode Costrict (Roo Code) |
|---|---|---|---|---|
| 搜索 | `/coding-hub:search <kw> [type:mcp]` | `/coding-hub-search <kw> [type:mcp]` | `/coding-hub-search <kw> [type:mcp]` | `/coding-hub-search <kw> [type:mcp]` |
| 浏览 | `/coding-hub:browse [cat]` | `/coding-hub-browse [cat]` | `/coding-hub-browse [cat]` | `/coding-hub-browse [cat]` |
| 推荐 | `/coding-hub:recommend` | `/coding-hub-recommend` | `/coding-hub-recommend` | `/coding-hub-recommend` |
| 安装 | `/coding-hub:install <name>` | `/coding-hub-install <name>` | `/coding-hub-install <name>` | `/coding-hub-install <name>` |
| 卸载 | `/coding-hub:uninstall <name>` | `/coding-hub-uninstall <name>` | `/coding-hub-uninstall <name>` | `/coding-hub-uninstall <name>` |
| 更新 | `/coding-hub:update` | `/coding-hub-update` | `/coding-hub-update` | `/coding-hub-update` |

<details>
<summary>平台路径差异</summary>

| | Costrict | VSCode Costrict | Claude Code | Opencode |
|---|---|---|---|---|
| Skill 路径（全局） | `~/.costrict/skills/coding-hub/` | `~/.costrict/skills/coding-hub/` | `~/.claude/skills/coding-hub/` | `~/.opencode/skills/coding-hub/` |
| Commands 路径 | `.costrict/coding-hub/commands/`（项目级） | `.roo/commands/`（项目级） | 同上（全局） | `.opencode/command/`（项目级） |
| 命令分隔符 | `-` | `-` | `:` | `-` |

- **Costrict CLI** 的命令文件需要安装到每个项目目录，在项目根目录运行 `install.sh` 即可
- **VSCode Costrict 插件 (Roo Code)** 支持 Roo Code 原生 slash commands，命令文件安装到 `.roo/commands/`，通过 `/coding-hub-update` 自动下载
- **Claude Code** 支持从全局 skills 目录加载子命令，一次安装所有项目可用
- **Opencode** 的命令文件需要安装到每个项目目录，在项目根目录运行 `install.sh` 即可

</details>

<details>
<summary>项目结构</summary>

```
costrict-coding-hub/
├── install.sh               # 一键安装脚本（macOS/Linux，curl | bash）
├── install.ps1              # 一键安装脚本（Windows，irm | iex）
├── catalog/                  # 资源索引（数据层）
│   ├── index.json            # 合并后的完整索引（869 条）
│   ├── schema.json           # 条目 schema 定义
│   ├── mcp/                  # MCP Server 源数据
│   ├── skills/               # Skill 源数据
│   ├── rules/                # Rule 源数据
│   └── prompts/              # Prompt 源数据
│
├── platforms/                # 各平台 Skill + 子命令
│   ├── claude-code/          # Claude Code 格式
│   ├── opencode/             # Opencode 格式
│   ├── costrict/             # Costrict 格式
│   └── vscode-costrict/      # VSCode Costrict 插件格式
│
├── scripts/                  # 数据同步脚本
│   ├── sync_mcp.py           # 从上游同步 MCP
│   ├── sync_skills.py        # 从上游同步 Skills
│   ├── sync_rules.py         # 从上游同步 Rules
│   ├── sync_prompts.py       # 从上游同步 Prompts
│   ├── merge_index.py        # 合并生成 index.json
│   └── llm_evaluator.py      # LLM 质量评估
│
└── openspec/                 # 变更管理（OpenSpec）
```

</details>

## For Agents

> **AI Agent 请阅读本节完成自动安装。** 请严格按照以下步骤执行，不要跳过任何一步。

### 第 1 步: 一键安装

安装脚本支持自动检测平台，直接执行即可：

**macOS / Linux：**

```bash
curl -fsSL https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.sh | bash
```

**Windows (PowerShell)：**

```powershell
irm https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.ps1 | iex
```

脚本通过以下**进程级环境变量**自动识别平台（这些变量由各平台进程启动时注入，不会互相污染）：

| 环境变量 | 平台 |
|---------|------|
| `COSTRICT_CALLER=vscode` | VSCode Costrict 插件 |
| `COSTRICT_RUNNING=1` | Costrict CLI |
| `CLAUDECODE=1` | Claude Code |
| `OPENCODE=1` | Opencode |

> **注意**: `COSTRICT_BASE_URL`、`OPENCODE_CMUX_ATTENTION_MODE` 等变量会在所有平台出现（shell profile 泄漏），**不能**用来判断平台。只有上表中的 4 个变量是各平台进程启动时独占注入的。

如果自动检测失败，可以手动指定：

**macOS / Linux：**
```bash
curl -fsSL https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.sh | bash -s -- --platform <platform>
```

**Windows (PowerShell)：**
```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.ps1))) -Platform <platform>
```

示例：
```bash
# Claude Code (macOS/Linux)
curl -fsSL https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.sh | bash -s -- --platform claude-code

# Opencode（在项目根目录执行）
curl -fsSL https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.sh | bash -s -- --platform opencode
```

```powershell
# Claude Code (Windows)
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/install.ps1))) -Platform claude-code
```

<details>
<summary>如果无法执行 curl | bash（备选方案）</summary>

根据你的平台，手动执行对应命令：
**Costrict CLI:**（Skill 全局 + Commands 项目级）

```bash
mkdir -p ~/.costrict/skills/coding-hub
curl -fsSL "https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/platforms/costrict/skills/coding-hub/SKILL.md" -o ~/.costrict/skills/coding-hub/SKILL.md
mkdir -p .costrict/coding-hub/commands
for cmd in search browse recommend install uninstall update; do
  curl -fsSL "https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/platforms/costrict/commands/coding-hub/coding-hub-${cmd}.md" -o .costrict/coding-hub/commands/coding-hub-${cmd}.md
done
```

**VSCode Costrict 插件:**（仅 Skill，无需命令）

```bash
mkdir -p ~/.costrict/skills/coding-hub
curl -fsSL "https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/platforms/vscode-costrict/skills/coding-hub/SKILL.md" -o ~/.costrict/skills/coding-hub/SKILL.md
```

> VSCode Costrict 插件无需安装子命令，所有命令逻辑已内置于 SKILL.md。


**Claude Code:**（Skill + Commands 全部安装到全局目录）

```bash
mkdir -p ~/.claude/skills/coding-hub
curl -fsSL "https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/platforms/claude-code/skills/coding-hub/SKILL.md" -o ~/.claude/skills/coding-hub/SKILL.md
for cmd in search browse recommend install uninstall update; do
  curl -fsSL "https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/platforms/claude-code/commands/coding-hub/${cmd}.md" -o ~/.claude/skills/coding-hub/${cmd}.md
done
```

**Opencode:**（Skill 全局 + Commands 项目级）

```bash
mkdir -p ~/.opencode/skills/coding-hub
curl -fsSL "https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/platforms/opencode/skills/coding-hub/SKILL.md" -o ~/.opencode/skills/coding-hub/SKILL.md
mkdir -p .opencode/command
for cmd in search browse recommend install uninstall update; do
  curl -fsSL "https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/platforms/opencode/command/coding-hub-${cmd}.md" -o .opencode/command/coding-hub-${cmd}.md
done
```
</details>

### 第 2 步: 验证安装

执行搜索命令验证安装是否成功：

```
# Costrict CLI / Opencode
/coding-hub-search typescript

# VSCode Costrict 插件
在插件聊天中发送: "用 coding-hub 搜索 typescript"

# Claude Code
/coding-hub:search typescript
```

**预期结果**: 返回一个包含搜索结果的 Markdown 表格。如果返回了表格，安装成功。如果提示命令不存在，请检查第 1 步的安装是否正确执行。

### 可用命令

安装成功后，以下命令可用（命令分隔符根据平台不同为 `:` 或 `-`）：

| 命令 | 说明 |
|------|------|
| `search <关键词> [type:mcp\|skill\|rule\|prompt]` | 搜索资源，可按类型筛选 |
| `browse [分类] [type:...]` | 浏览分类 |
| `recommend [type:...]` | 基于当前项目技术栈推荐 |
| `install <名称>` | 安装资源 |
| `uninstall <名称>` | 卸载资源 |
| `update` | 更新到最新版本 |

### 数据源

索引 URL: `https://raw.githubusercontent.com/zgsm-sangfor/costrict-coding-hub/main/catalog/index.json`

索引是 JSON 数组，每个条目包含 `id`, `name`, `type`(mcp/skill/rule/prompt), `description`, `source_url`, `stars`, `category`, `tags`, `tech_stack`, `install`。

---

## 🚀 为什么选择 Costrict？

如果你喜欢 Coding Hub 的理念，不妨试试我们的旗舰产品 **[Costrict](https://github.com/zgsm-ai/costrict)** —— 一个更强大的 AI Coding Agent 平台：

[立即体验 Costrict →](https://github.com/zgsm-ai/costrict)

---

## Contributing

欢迎通过 PR 向 `catalog/` 下对应类型目录添加精选资源。提交前请确保：

- 资源与 coding 相关
- 提供准确的 `source_url`、`description`、`tags`
- 遵循 `catalog/schema.json` 定义的数据格式