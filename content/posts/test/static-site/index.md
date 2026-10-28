---
title: 静态站点生成器最小实现
date: 2026-10-27
tags: [静态站点, node, 实现]
summary: 不依赖任何第三方包，只用 Node.js 内置模块实现一个 Markdown → HTML 的构建脚本。
slug: static-site
---

## 目标

写一个**零依赖**的 `build.js`，能够：

- 解析 Markdown front matter（`---` 包裹的 YAML 片段）。
- 把常用 Markdown 语法渲染成 HTML。
- 套上统一的 HTML 模板（包含 SEO / Open Graph / JSON-LD）。
- 自动生成首页、栏目页、RSS、sitemap。

## Front matter 解析

用一个简单的正则分割 front matter 和正文：

```js
const fmRe = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/;
```

然后逐行解析字段，数组字段（`tags`）用 `[...]` 或逗号分隔。

## Markdown 渲染

支持的语法：

| 语法 | 说明 |
|------|------|
| `#` / `##` / `###` | 标题 |
| `**bold**` / `*italic*` | 强调 |
| `` `code` `` | 行内代码 |
| ```` ```lang ```` | 代码块 |
| `- item` | 无序列表 |
| `1. item` | 有序列表 |
| `[text](url)` | 链接 |
| `![alt](src)` | 图片 |
| `> quote` | 引用 |

够用就行，不需要把 CommonMark 的每一个角落都实现。

## 模板组合

每一页都先调用一个 `layout(title, meta, body, config)` 函数，统一输出 `<!doctype html>` 到 `</html>`。文章页额外注入 `BlogPosting` 结构化数据，首页注入 `Blog`。

## 性能

3 篇文章的构建时间在 10ms 以内。即使文章数涨到几百篇，单次构建也不会超过一秒。

## 为什么不引入 marked.js

引入之后，构建时间不会显著缩短，但依赖数会变成 1（再加传递依赖），"复制粘贴就能跑"这件事就被破坏了。**对一个小站来说，零依赖的可读性比功能完备更重要。**

如果你确实需要更复杂的 Markdown 特性（表格、任务列表、脚注），把 `renderMarkdown` 函数换成 marked 的调用也只需要改几行。
