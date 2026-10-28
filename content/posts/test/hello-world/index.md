---
title: Hello, World —— 我的第一篇文章
date: 2026-10-27
tags: [随笔, 建站, markdown]
summary: 从零开始搭建这个纯静态站点，聊一聊为什么选择 Markdown + 构建脚本而不是沉重的框架。
slug: hello-world
---

## 为什么又搭了一个站

每隔一段时间，我都会忍不住把博客推倒重来一次。这一次我给自己定了几条简单的规则：

- **纯静态 HTML**：不要运行时，不要 Node 服务，不要数据库。
- **文章用 Markdown 写**：用 front matter 管元信息，正文就是纯 Markdown。
- **首页直接输出所有文章链接**：不依赖 JS 渲染，搜索引擎一进来就能抓全。
- **配置集中管理**：站点名、域名、栏目都写在一个 `site.config.json` 里。

## 核心思路

整个站点的构建脚本只有一个文件 `build.js`，它做三件事：

1. 读取 `site.config.json` 和 `content/posts/*.md`。
2. 把 Markdown 渲染成 HTML，套上统一的模板。
3. 顺手生成 `sitemap.xml`、`rss.xml`、`feed.json`、`llms.txt`。

## 运行方式

```bash
node build.js
```

搞定。新增一篇文章，只要往 `content/posts/` 里扔一个 `.md` 文件，再跑一遍 `build.js` 就行。

> 这不是什么复杂的工程，只是把"写文章"和"发布"之间的摩擦降到最低。
