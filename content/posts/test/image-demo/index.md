---
title: 图片示例：三种写法都能显示
date: 2026-10-27
tags: [图片, 教程]
summary: 演示本地图片、子目录图片、外链图片三种写法，以及 build.js 如何自动规整路径。
slug: image-demo
---

## 封面图（相对路径）

![封面大图](banner.svg)

> 直接写相对路径 `banner.svg`，构建脚本会自动规整成 `/assets/image-demo/banner.svg`（站点根绝对路径），**首页 `/` 和文章页 `/posts/image-demo.html` 都能正确加载**，永远不会有相对路径算不准的问题。

## 子目录图片（保留目录结构）

![一杯咖啡](2026/coffee.svg)

> 子目录路径保留，构建后也是 `/assets/image-demo/2026/coffee.svg`。
> 你的资源目录长什么样，站点上就长什么样，一目了然。

## 外链图片

![在线占位图](https://placekitten.com/640/320)

> 外链 URL 原样保留，不会被改写。

## 图注（figure + figcaption）

也可以在 `<figure>` 里套图片 + `<figcaption>`，CSS 会自动让它变小变灰：

<figure>
  <img src="./banner.svg" alt="banner">
  <figcaption>这是一行图注。用相对路径 ./banner.svg 也能正常加载。</figcaption>
</figure>
