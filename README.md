# 我的站点 —— 纯静态构建

一个**零依赖**的纯静态个人内容站。文章用 Markdown 写，配置集中在 `site.config.json`，一条 `node build.js` 生成所有页面与索引文件。

## 目录结构

```
├── site.config.json       ← 集中配置（站点名、域名、栏目、导航）
├── build.js               ← 零依赖构建脚本（Node.js 内置 fs/path）
├── style.css               ← 全局响应式样式
├── robots.txt              ← 爬虫规则（可直接修改）
├── index.html              ← 自动生成（不要手动改）
├── about.html              ← 自动生成
├── sitemap.xml             ← 自动生成
├── rss.xml                 ← 自动生成
├── feed.json               ← 自动生成
├── llms.txt                ← 自动生成
├── content/
│   └── posts/
│       ├── hello-world.md
│       ├── static-site.md
│       └── weekend-notes.md
├── posts/                  ← 自动生成的文章详情页
│   ├── hello-world.html
│   ├── static-site.html
│   └── weekend-notes.html
└── category/               ← 自动生成的栏目页
    ├── tech.html
    └── life.html
```

**自动生成的文件**：`index.html`、`about.html`、`posts/*.html`、`category/*.html`、`sitemap.xml`、`rss.xml`、`feed.json`、`llms.txt`。**不要手动编辑它们**，改源文件后重新构建即可。

## 如何本地预览

确保已安装 **Node.js 18+**（无需任何 npm 包）。

```bash
cd /workspace
node build.js          # 首次构建 / 每次修改后重新生成
python3 -m http.server 8080   # 或 node -e "...简单 http 服务..."
# 浏览器打开 http://localhost:8080
```

构建脚本遇到**缺少必填字段、无效栏目名、slug 重复**会明确报错并退出，不会静默生成坏页面。

## 如何修改站点配置

打开 `site.config.json`，所有站点信息都在里面：

| 字段 | 含义 | 是否必填 |
|------|------|----------|
| `site.name` | 站点名，会出现在 header、footer、JSON-LD、RSS | ✅ |
| `site.url` | 站点完整域名，**必须以 / 结尾**（构建时会自动规范化） | ✅ |
| `site.description` | 站点描述，出现在首页副标题、meta description、Open Graph | ✅ |
| `site.author` | 作者名，出现在 JSON-LD 与 About 页 | ✅ |
| `site.language` | `lang` 属性，默认 `zh-CN` | 建议 |
| `site.copyright` | footer 版权行 | 建议 |
| `site.favicon` | favicon 路径 | 建议 |
| `nav` | 主导航数组：`{label, href}` | 建议 |
| `categories` | 栏目数组：`{slug, name, description}` | ✅（至少 1 个）|
| `feed` | RSS / JSON Feed / LLMs.txt 的路径 | 可选 |

修改配置后**重新运行 `node build.js`** 即可。

## 如何新增栏目

1. 打开 `site.config.json`，在 `categories` 数组追加一项：
   ```json
   { "slug": "notes", "name": "笔记", "description": "课堂/会议笔记归档。" }
   ```
2. 重新运行 `node build.js`，会自动生成 `category/notes.html`。
3. （可选）在 `nav` 里加上 `{ "label": "笔记", "href": "/category/notes.html" }`。

**注意**：新增栏目后，已有的文章如果引用这个新 `slug`，构建时才会通过校验。删除栏目前请先把引用它的文章改掉或删除。

## 如何新增 / 编辑文章

1. 在 `content/posts/` 下新建一个 `.md` 文件，文件名建议和 slug 保持一致（例如 `my-new-post.md`）。
2. 在文件开头写 front matter，用 `---` 包裹：

```markdown
---
title: 文章标题
date: 2026-10-27
category: tech
tags: [标签1, 标签2]
summary: 一两句话摘要，会出现在首页列表与 RSS 里。
slug: my-new-post
---

正文开始…支持标准 Markdown：标题、列表、代码块、引用、链接、图片、加粗、斜体。
```

### Front matter 字段规范

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `title` | 字符串 | ✅ | 文章标题 |
| `date` | `YYYY-MM-DD` | ✅ | 发布日期，会渲染成 `<time datetime>` |
| `category` | 字符串 | ✅ | 必须与 `site.config.json` 里某个 `categories[].slug` 完全一致 |
| `tags` | 数组（方括号 + 逗号） | 建议 | 标签列表，首页和 JSON-LD 都会用到 |
| `summary` | 字符串 | 建议 | 摘要；不写则 RSS 会退回用标题 |
| `slug` | 字符串 | 建议 | 决定最终 URL `/posts/<slug>.html`；不写则从文件名取 |

### Markdown 支持的语法

- `#` / `##` / `###` 等 6 级标题
- `**粗体**` `*斜体*` `` `行内代码` ``
- ` ```lang ` 代码块（带可选语言标记）
- `-` 无序列表、`1.` 有序列表
- `> 引用`
- `[链接](url)` 与 `![图片](url)`
- `---` 分割线
- 站内 `.md` 链接会自动改成 `.html`

### 3. 重新构建

```bash
node build.js
```

脚本会：
- 自动生成 `posts/<slug>.html`；
- 自动在首页对应栏目下插入文章；
- 自动更新栏目页、sitemap、rss、feed.json、llms.txt；
- 检查必填字段、栏目有效性、slug 唯一性，有问题直接报错。

## 如何部署到静态托管

任何静态托管平台都可以，推荐：

| 平台 | 部署方式 |
|------|----------|
| **GitHub Pages** | 把整个仓库推到 GitHub，Settings → Pages 选 `main` 分支根目录 |
| **Netlify** | 把仓库连上去，Build command 填 `node build.js`，Publish directory 填 `.` |
| **Vercel** | Import 仓库，Build command `node build.js`，Output directory `.` |
| **Cloudflare Pages** | 同上，Framework preset 选 "None" |
| **自建 / Nginx** | 把整个目录（除了 `content/` 和 `build.js`）上传到站点根目录即可 |

**自定义域名**：在托管平台设置域名 A/CNAME 记录，然后**记得修改 `site.config.json` 里的 `site.url`**，重新构建后部署，保证 sitemap / RSS / canonical / JSON-LD 里的链接全部正确。

## 错误提示速查

构建脚本遇到以下情况会直接**报错退出**，方便你定位：

| 错误信息 | 原因 | 解决 |
|----------|------|------|
| `找不到 site.config.json` | 配置文件缺失 | 恢复本仓库的 `site.config.json` |
| `site.config.json 缺少 site.xxx` | 顶层必填字段缺失 | 补齐 `site` 对象里的字段 |
| `xxx.md: 缺少必填 front matter 字段: title, date` | 文章 front matter 不完整 | 补上 `title / date / category` |
| `xxx.md: category "yyy" 在 site.config.json 中不存在` | 文章引用了未定义的栏目 | 要么在 `categories` 里加上这个 slug，要么把文章里的 category 改成已有的 |
| `xxx.md: slug "zzz" 重复` | 两篇文章同 slug | 改其中一篇的 slug，或者删除其中一篇 |
| `content/posts/ 下没有任何 .md 文件` | 没有文章 | 至少保留一篇示例文章 |

## 为什么没有第三方依赖？

- `build.js` 只用到 `fs` / `path`，Node.js 自带。
- 避免 `node_modules`、锁文件、npm install。
- 构建时间 ~10ms，复制粘贴就能跑。
- 如果后续需要更复杂的 Markdown（表格、任务列表、脚注），把 `renderMarkdown()` 里的逻辑换成 `marked.parse()` 只需要改几行。

## SEO / AI 友好要点

- 每一页都有完整 `<title>`、`<meta description>`、`<link rel="canonical">`。
- 注入 Open Graph 与 Twitter Card 元信息。
- 首页注入 `Blog` 结构化数据，文章页注入 `BlogPosting` + `BreadcrumbList`。
- 生成 `sitemap.xml`、`robots.txt`、`rss.xml`、`feed.json`、`llms.txt`。
- 首页**直接** `<a href>` 所有文章链接，不依赖 JS 渲染。
- 日期使用 `<time datetime="YYYY-MM-DD">`。
- 语义化 HTML5：`header` / `nav` / `main` / `section` / `article` / `footer`。
- 无 JS 时搜索框退化但所有文章依然完整可见。
