---
title: "Hugo 入门：从零搭建一个 AI 友好的静态博客"
date: 2026-10-19T10:00:00+08:00
author: "作者名"
description: "手把手教你用 Hugo + PaperMod 搭建一个面向 Cloudflare Pages 部署、高度优化的 AI 友好静态博客"
tags: ["Hugo", "PaperMod", "Cloudflare Pages", "AI 优化", "静态站点"]
draft: false
image: "cover.svg"
cover:
  image: "cover.svg"
  relative: true
  hidden: false
---

## 为什么选 Hugo？

Hugo 是目前最轻量、构建速度最快的静态站点生成器之一。一个中等规模的博客（几百篇文章），Hugo 可以在**几百毫秒**内完成构建，对比 Jekyll（几秒）、Next.js（几十秒到几分钟），优势非常明显。

结合 **PaperMod** 主题和 **Cloudflare Pages** 的免费全球 CDN 部署方案，你可以在 10 分钟内上线一个自己的博客。

![Hugo Logo](https://gohugo.io/images/hugo-logo-wide.svg "Hugo 官方 Logo")

## 本文目标

读完本文，你将获得：

1. ✅ 完整的项目源码（Hugo + PaperMod）
2. ✅ 开箱即用的 **config.yml** 配置
3. ✅ 面向 AI 大模型的 **JSON-LD 结构化数据**、**llms.txt**、**robots.txt**
4. ✅ Cloudflare Pages 一键部署参数
5. ✅ 完整的 Markdown 发文工作流

## 目录结构约定（Hugo Page Bundle）

Hugo 推荐使用 **Page Bundle（页面包）** 模式管理文章。每篇文章是一个独立文件夹，Markdown 和配图放在一起：

```
content/posts/
├── my-first-article/
│   ├── index.md          # 文章正文
│   ├── cover.svg         # 封面图（小驼峰命名）
│   └── diagram.png       # 正文配图
└── another-article/
    ├── index.md
    └── images/
        ├── screenshot-1.jpg
        └── screenshot-2.jpg
```

这样做的好处：
- 图片和文章永远在一起，删除文章不会遗漏图片
- Markdown 里用相对路径引用图片，移动目录也不怕
- Hugo 会自动把同目录下的图片识别为 **Page Resources**，供模板使用

## Markdown 写作示例

### Front Matter 模板

每篇文章的 `index.md` 顶部必须包含 YAML Front Matter（在 `---` 分隔线之间）：

```yaml
---
title: "文章标题"
date: 2026-10-19T10:00:00+08:00
author: "作者名"
description: "一句话摘要，用于 OG、JSON-LD、SEO 描述"
tags: ["标签一", "标签二"]
draft: false
cover:
  image: "cover.svg"
  relative: true
---
```

### 图片的 alt 和 caption

无障碍访问（a11y）和 AI 爬虫都依赖图片的 **alt 文本**。Hugo 支持两种方式插入图片：

#### 方式一：纯 Markdown 语法（简单插图）

```markdown
![这是一张示意图](diagram.png "图片标题（可选）")
```

输出效果：

> Hugo 的 render-image.html 会自动把 alt 文本渲染为 `<img alt="...">`。

#### 方式二：figure shortcode（带 caption 图注）

```markdown
{{</* figure src="screenshot-1.jpg" alt="Cloudflare Pages 构建日志截图" caption="图 1：Cloudflare Pages 上一次构建成功" */>}}
```

输出效果：

{{< figure src="cover.svg" alt="Hugo 博客封面图，橙紫渐变背景" caption="图 1：本文封面图（SVG 矢量图，可任意缩放）" >}}

### 标题层级（H1 → H2 → H3）

HTML 语义化对 SEO 和 AI 爬虫至关重要：

- **H1**（`# 标题`）：每篇文章只有一个，就是 `title` Front Matter
- **H2**（`## 标题`）：文章的大章节标题
- **H3**（`### 标题`）：子章节标题
- 不要跳过层级（比如从 H2 直接跳到 H4）

> 主题的 anchored_headings 会自动给每个标题加锚点，方便目录（TOC）生成。

## AI 爬虫优化清单

### 1. llms.txt（专门给大模型读的站点目录）

站点根目录的 `llms.txt` 会被 **所有主流 AI 爬虫** 优先读取（OpenAI 的 GPTBot、Anthropic 的 ClaudeBot、Google-Extended、Perplexity 等），它告诉 AI：

> 「这个网站有哪些页面、每个页面讲什么」

我们的模板会自动递归所有 section，输出格式化的页面列表 + 描述摘要。

### 2. JSON-LD 结构化数据

每篇文章的 `<head>` 里会自动注入 `BlogPosting` schema：

```json
{
  "@context": "https://schema.org",
  "@type": "BlogPosting",
  "headline": "Hugo 入门：从零搭建一个 AI 友好的静态博客",
  "author": { "@type": "Person", "name": "作者名" },
  "datePublished": "2026-10-19T10:00:00+08:00",
  "articleBody": "... 完整正文 ...",
  "mainEntityOfPage": { "@type": "WebPage", "@id": "https://..." }
}
```

### 3. robots.txt 全放行

```
User-agent: GPTBot        Allow: /
User-agent: ClaudeBot     Allow: /
User-agent: CCBot        Allow: /
...
User-agent: *             Allow: /
```

### 4. canonical / OG / 语义化 HTML

- 每页都有唯一的 `<link rel="canonical">`
- 每篇文章都有 `og:title` / `og:image` / `article:published_time`
- 正文直接渲染在 HTML 里，**没有 JS 动态加载的文字**
- 所有图片都有 alt 文本（Markdown alt 属性或 figure shortcode）

## Cloudflare Pages 部署参数

在 Cloudflare Pages 新建项目时填写：

| 项目 | 值 |
|---|---|
| Production branch | `main` |
| Build command | `hugo` |
| Build output directory | `public` |
| 环境变量 `HUGO_VERSION` | `"0.134.0"` |

## 总结

Hugo + PaperMod + Cloudflare Pages 的组合，是目前技术博客领域最轻量、部署成本最低的方案之一。配合 llms.txt 和 JSON-LD 结构化数据，你的文章会被越来越多的 AI Agent 发现和引用。

> 📖 想深入了解？请看本站首页的完整文章列表。
