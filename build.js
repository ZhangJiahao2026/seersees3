#!/usr/bin/env node
/* =========================================================
   build.js —— 零依赖静态站点构建器
   用法: node build.js
   依赖: 仅 Node.js 内置模块 (fs, path, process, url)
   ========================================================= */

const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');

const ROOT = __dirname;
const POSTS_DIR = path.join(ROOT, 'content', 'posts');
const OUT_POSTS_DIR = path.join(ROOT, 'posts');
const OUT_CATEGORY_DIR = path.join(ROOT, 'category');

// ---------- 工具 ----------

function log(msg) { console.log(`[build] ${msg}`); }
function fatal(msg) { console.error(`[build][error] ${msg}`); process.exit(1); }

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function readFile(p) {
  return fs.readFileSync(p, 'utf8');
}

function writeFile(p, content) {
  ensureDir(path.dirname(p));
  fs.writeFileSync(p, content, 'utf8');
}

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function escapeXml(str) {
  return escapeHtml(str);
}

function slugify(str) {
  return str
    .toLowerCase()
    .trim()
    .replace(/[^\w\u4e00-\u9fff]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'post';
}

function formatDate(dateStr) {
  // YYYY-MM-DD → YYYY年MM月DD日
  const d = new Date(dateStr + 'T00:00:00Z');
  if (isNaN(d.getTime())) return dateStr;
  return `${d.getUTCFullYear()}年${String(d.getUTCMonth() + 1).padStart(2, '0')}月${String(d.getUTCDate()).padStart(2, '0')}日`;
}

function isoDate(dateStr) {
  const d = new Date(dateStr + 'T00:00:00Z');
  if (isNaN(d.getTime())) return dateStr;
  return d.toISOString();
}

function lastModDate() {
  return new Date().toISOString();
}

function joinUrl(base, rel) {
  if (!base.endsWith('/')) base += '/';
  const clean = rel.replace(/^\//, '');
  return base + clean;
}

// ---------- 1. 读取站点配置 ----------

function loadConfig() {
  const cfgPath = path.join(ROOT, 'site.config.json');
  if (!fs.existsSync(cfgPath)) fatal('找不到 site.config.json');
  const cfg = JSON.parse(readFile(cfgPath));

  // 基础校验
  const required = ['site', 'categories', 'nav'];
  for (const k of required) {
    if (!cfg[k]) fatal(`site.config.json 缺少顶层字段: ${k}`);
  }
  const s = cfg.site;
  for (const k of ['name', 'url', 'description', 'author']) {
    if (!s[k]) fatal(`site.config.json 缺少 site.${k}`);
  }
  cfg.site.url = cfg.site.url.replace(/\/$/, '') + '/';

  // 快速索引
  cfg._catMap = Object.fromEntries(cfg.categories.map(c => [c.slug, c]));
  return cfg;
}

// ---------- 2. 解析 front matter ----------

const FM_RE = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/;

function parseFrontMatter(raw) {
  const m = raw.match(FM_RE);
  if (!m) return { data: {}, body: raw };
  const yaml = m[1];
  const body = raw.slice(m[0].length);
  const data = parseSimpleYaml(yaml);
  return { data, body };
}

// 一个足够好的 YAML 子集解析器（仅支持本项目需要的格式）
function parseSimpleYaml(src) {
  const out = {};
  const lines = src.split(/\r?\n/);
  for (const rawLine of lines) {
    const line = rawLine.replace(/\s+#.*$/, '').trim();
    if (!line || line.startsWith('#')) continue;

    const colon = line.indexOf(':');
    if (colon === -1) continue;

    const key = line.slice(0, colon).trim();
    let val = line.slice(colon + 1).trim();

    // 数组: [a, b, c]
    if (val.startsWith('[') && val.endsWith(']')) {
      val = val.slice(1, -1).split(',').map(s => s.trim().replace(/^['"]|['"]$/g, '')).filter(Boolean);
    } else {
      // 去掉引号
      val = val.replace(/^['"]|['"]$/g, '');
    }
    out[key] = val;
  }
  return out;
}

// ---------- 3. 渲染 Markdown ----------

// 保护 $...$ / $$...$$ 数学公式不被 Markdown 斜体粗体规则破坏
// 用 \x00MK<id>\x00 占位（空字符不会在正常 HTML/Markdown 里出现）
function protectMath(src) {
  const store = [];
  const marker = (id) => `\x00MK${id}\x00`;

  // 先匹配块级 $$...$$（可能跨行，直到下一个 $$ 出现为止）
  let s = src.replace(/\$\$([\s\S]*?)\$\$/g, (match) => {
    store.push(match);
    return marker(store.length - 1);
  });

  // 再匹配行内 $...$（同一行内，且不是 $$ 的一部分）
  // 规则：在非 $$ 环境下，$...$ 配对；$ 前面不能是 \（\$ 是字面量）
  s = s.replace(/(?<!\\)\$(?!\$)([^$\n]+?)\$/g, (match) => {
    store.push(match);
    return marker(store.length - 1);
  });

  return { s, store };
}
function restoreMath(s, store) {
  let out = s;
  // 倒序替换，避免前面的还原影响后面的占位符
  for (let i = store.length - 1; i >= 0; i--) {
    out = out.split(`\x00MK${i}\x00`).join(store[i]);
  }
  // 还原转义的字面量 \$ → $
  out = out.replace(/\\\$/g, '$');
  return out;
}

// 轻量 Markdown → HTML（块级 + 行内）
// articleAssetsSiteDir: 当前文章的资源在站点根的路径，如 "/assets/hello-world"
function renderMarkdown(src, articleAssetsSiteDir) {
  // ⚠️ 关键：在任何 Markdown 解析之前，先保护所有数学公式
  // （公式里有大量 _ * 等字符，会被 Markdown 误解析成斜体粗体）
  const { s: protectedSrc, store } = protectMath(src);

  const text = protectedSrc.replace(/\r\n/g, '\n');
  const lines = text.split('\n');
  let out = '';
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) { i++; continue; }

    if (/^```/.test(line)) {
      const lang = line.replace(/^```/, '').trim();
      let buf = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) {
        buf.push(lines[i]); i++;
      }
      i++;
      out += `<pre><code${lang ? ` class="language-${escapeHtml(lang)}"` : ''}>${escapeHtml(buf.join('\n'))}</code></pre>\n`;
      continue;
    }

    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      const level = h[1].length;
      out += `<h${level}>${renderInline(h[2], articleAssetsSiteDir)}</h${level}>\n`;
      i++;
      continue;
    }

    if (/^>\s?/.test(line)) {
      let buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) {
        buf.push(lines[i].replace(/^>\s?/, '')); i++;
      }
      out += `<blockquote>${renderInline(buf.join(' '), articleAssetsSiteDir)}</blockquote>\n`;
      continue;
    }

    if (/^-{3,}$|^\*{3,}$/.test(line.trim())) {
      out += `<hr>\n`;
      i++;
      continue;
    }

    if (/^[-*]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^[-*]\s+/, '')); i++;
      }
      out += `<ul>${items.map(x => `<li>${renderInline(x, articleAssetsSiteDir)}</li>`).join('')}</ul>\n`;
      continue;
    }

    if (/^\d+\.\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\.\s+/, '')); i++;
      }
      out += `<ol>${items.map(x => `<li>${renderInline(x, articleAssetsSiteDir)}</li>`).join('')}</ol>\n`;
      continue;
    }

    let buf = [line];
    i++;
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^(#{1,6})\s+/.test(lines[i]) &&
      !/^```/.test(lines[i]) &&
      !/^[-*]\s+/.test(lines[i]) &&
      !/^\d+\.\s+/.test(lines[i]) &&
      !/^>\s?/.test(lines[i]) &&
      !/^-{3,}$/.test(lines[i].trim())
    ) {
      buf.push(lines[i]); i++;
    }
    out += `<p>${renderInline(buf.join(' '), articleAssetsSiteDir)}</p>\n`;
  }
  // 兜底：渲染后再扫一遍 HTML，规整原生 HTML <img src="..."> / <a href="..."> 的相对路径
  if (articleAssetsSiteDir) {
    out = normalizeAssetUrlsInHtml(out, articleAssetsSiteDir);
  }
  // ⚠️ 还原数学公式占位符 → 原始 LaTeX 源码
  out = restoreMath(out, store);
  return out;
}

// 对一段 HTML 字符串里的所有 src="..." / href="..." 做二次规整
// 只碰"需要规整"的路径：相对路径、文件名、非绝对 URL。
// 已经是 /xxx（站点根绝对）、http(s)://、//xxx、data: 的原样保留。
function normalizeAssetUrlsInHtml(html, articleAssetsSiteDir) {
  const re = /(src|href)=("|')([^"']+)\2/g;
  return html.replace(re, (full, attr, quote, url) => {
    if (isExternalUrl(url) || url.startsWith('/')) return full;
    const normalized = normalizeAssetUrl(url, articleAssetsSiteDir);
    return `${attr}=${quote}${normalized}${quote}`;
  });
}

// ---------- 资源 URL 规范化（文章内相对路径优先于全局资源桶） ----------
//
// 优先级（从高到低）：
//   1) 外链 / data: / 协议相对 //xxx → 原样保留
//   2) 站点根绝对路径（/xxx）→ 原样保留
//   3) 以 ./ 或 ../ 开头的相对路径 → 按文章目录算，规整到 /assets/<slug>/...
//   4) 纯文件名（无 /）且当前文章有 assetsSiteDir → /assets/<slug>/<name>
//   5) 纯文件名但无上下文（旧 flat 结构兜底）→ /images/ 或 /resources/ 分桶
//   6) 带子目录且无 bucket 前缀 → 看后缀分桶
//   7) 显式 resources/xxx / images/xxx 前缀 → 规整到根

const IMAGE_EXT = new Set(['png','jpg','jpeg','gif','webp','svg','avif','bmp','ico']);
const SITE_ASSETS_DIR = path.join(ROOT, 'assets');  // 站点根 /assets/

function isExternalUrl(url) {
  return /^https?:\/\//i.test(url)
      || /^data:(image|application|audio|video|text)\//i.test(url)
      || /^\/\//.test(url);
}

function detectBucketByExt(urlPath) {
  const m = urlPath.toLowerCase().match(/\.([a-z0-9]+)(?:$|\?|#)/);
  if (m && IMAGE_EXT.has(m[1])) return 'images';
  return 'resources';
}

/**
 * @param {string} raw  - Markdown 里写的 URL
 * @param {string|null} articleAssetsSiteDir  - 当前文章在站点上的 assets 路径，如 "/assets/hello-world"
 */
function normalizeAssetUrl(raw, articleAssetsSiteDir) {
  if (!raw) return raw;
  const url = raw.trim();
  if (isExternalUrl(url)) return url;
  if (url.startsWith('/')) return url;  // 用户显式写了站点根绝对路径，不动

  // 拆出查询串和锚点
  const qIdx = Math.min(
    url.includes('?') ? url.indexOf('?') : url.length,
    url.includes('#') ? url.indexOf('#') : url.length,
  );
  const head = url.slice(0, qIdx);
  const tail = url.slice(qIdx);

  // 情况 A：文章上下文存在，视为文章文件夹内的相对引用
  //         （不管是 ./xxx 还是 纯文件名 还是 子目录路径）
  const hasRelMarker = /^\.\/|^\.\.\//.test(head);
  if (articleAssetsSiteDir && (hasRelMarker || !head.includes('/'))) {
    const clean = head.replace(/^\.\/+/, '').replace(/^(\.\.\/)+/, '');
    return `${articleAssetsSiteDir}/${clean}${tail}`.replace('//', '/');
  }
  if (articleAssetsSiteDir && head.includes('/')) {
    // 带 / 但没显式 bucket 前缀（如 2026/report.pdf）→ 当作文章子目录
    const isImgKnownPrefix = head.startsWith('images/') || head.startsWith('resources/') || head.startsWith('assets/');
    if (!isImgKnownPrefix) {
      return `${articleAssetsSiteDir}/${head}${tail}`;
    }
  }

  // 情况 B：兜底 —— 按全局 bucket 规则
  let clean = head.replace(/^\.\/+/, '').replace(/^(\.\.\/)+/, '');
  clean = clean.replace(/^content\/posts\//, '');  // 用户可能写了源路径

  if (clean.startsWith('images/') || clean.startsWith('resources/') || clean.startsWith('assets/')) {
    return '/' + clean + tail;
  }

  // 纯文件名（不含 /）
  if (!clean.includes('/')) {
    const bucket = detectBucketByExt(clean);
    return `/${bucket}/${clean}${tail}`;
  }

  // 带子目录但没前缀 → 分桶（兜底）
  const bucket = detectBucketByExt(clean);
  return `/${bucket}/${clean}${tail}`;
}

// ---------- 构建时拷贝资源 ----------

function copyTree(src, dst) {
  if (!fs.existsSync(src)) return 0;
  ensureDir(dst);
  let count = 0;
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const sPath = path.join(src, entry.name);
    const dPath = path.join(dst, entry.name);
    if (entry.isDirectory()) {
      count += copyTree(sPath, dPath);
    } else if (entry.isFile()) {
      // 跳过 index.md 这种 Markdown 正文，正文由渲染输出到 posts/ 目录
      if (entry.name.endsWith('.md')) continue;
      fs.copyFileSync(sPath, dPath);
      count++;
    }
  }
  return count;
}

function syncAssetsForPost(post) {
  if (post.isLegacy) return;  // 旧 flat 结构不拷贝 per-article 资源
  const src = post.articleDir;
  if (!fs.existsSync(src)) return 0;
  const dst = path.join(SITE_ASSETS_DIR, post.slug);
  return copyTree(src, dst);
}

function syncSharedBuckets() {
  // content/posts/images/ → /images/ （共享图片桶，保持兼容）
  const OLD_IMAGES_SRC = path.join(POSTS_DIR, 'images');
  const RESOURCES_SRC_DIR = path.join(POSTS_DIR, 'resources');
  if (fs.existsSync(OLD_IMAGES_SRC)) {
    copyTree(OLD_IMAGES_SRC, path.join(ROOT, 'images'));
    log(`共享图片桶    → /images/`);
  }
  if (fs.existsSync(RESOURCES_SRC_DIR)) {
    copyTree(RESOURCES_SRC_DIR, path.join(ROOT, 'resources'));
    log(`共享资源桶    → /resources/`);
  }
}

// ---------- 行内语法处理
function renderInline(src, articleAssetsSiteDir) {
  let s = src;

  // 图片 ![alt](url)
  s = s.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, url) => {
    const normalized = normalizeAssetUrl(url.trim(), articleAssetsSiteDir);
    return `<img src="${escapeHtml(normalized)}" alt="${escapeHtml(alt)}" loading="lazy">`;
  });

  // 链接 [text](url) —— 站内 .md → .html；其他走 URL 规范化
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, text, url) => {
    let raw = url.trim();
    if (!isExternalUrl(raw) && !raw.startsWith('/')) {
      if (raw.endsWith('.md')) raw = raw.replace(/\.md$/, '.html');
    }
    const href = normalizeAssetUrl(raw, articleAssetsSiteDir);
    // 自动给外链加 target="_blank" + rel，给下载类文件加 download 友好提示
    const extra = [];
    if (isExternalUrl(href)) extra.push('target="_blank" rel="noopener noreferrer"');
    const cleanHref = href.split('?')[0].split('#')[0];
    const isDownload = /\.(pdf|zip|rar|7z|tar|gz|mp3|wav|mp4|mov|dmg|exe|msi|docx?|xlsx?|pptx?|epub)$/i.test(cleanHref);
    if (isDownload) extra.push(`download="${path.posix.basename(cleanHref)}"`);
    return `<a href="${escapeHtml(href)}"${extra.length ? ' ' + extra.join(' ') : ''}>${renderInline(text, articleAssetsSiteDir)}</a>`;
  });

  // 行内代码 `code`
  s = s.replace(/`([^`]+)`/g, (_, code) => `<code>${escapeHtml(code)}</code>`);

  // **bold**
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  // *italic*
  s = s.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  // __bold__
  s = s.replace(/__([^_]+)__/g, '<strong>$1</strong>');
  // _italic_
  s = s.replace(/_([^_]+)_/g, '<em>$1</em>');

  return s;
}

// ---------- 4. 扫描与校验文章 ----------

function walkIndexMd(config) {
  /**
   * 新结构：content/posts/<category-slug>/<slug>/index.md
   * 旧结构（兼容过渡）：content/posts/*.md
   * 返回 [{ fullPath, folderSlug, parentCatFromDir, isLegacy }]
   */
  const results = [];
  if (!fs.existsSync(POSTS_DIR)) return results;

  const entries = fs.readdirSync(POSTS_DIR, { withFileTypes: true });

  for (const entry of entries) {
    const full = path.join(POSTS_DIR, entry.name);
    if (entry.isDirectory()) {
      // 目录 = 栏目 → 再下一层找文章文件夹
      for (const sub of fs.readdirSync(full, { withFileTypes: true })) {
        const artFolder = path.join(full, sub.name);
        if (sub.isDirectory()) {
          const idx = path.join(artFolder, 'index.md');
          if (fs.existsSync(idx)) {
            results.push({
              fullPath: idx,
              folderSlug: sub.name,
              parentCatFromDir: entry.name,
              isLegacy: false,
              articleDir: artFolder,
            });
          }
        } else if (sub.isFile() && sub.name.endsWith('.md')) {
          // 兼容过渡：content/posts/<cat>/xxx.md（一层嵌套）
          results.push({
            fullPath: artFolder,
            folderSlug: path.basename(artFolder, '.md'),
            parentCatFromDir: entry.name,
            isLegacy: 'shallow',
            articleDir: full,
          });
        }
      }
    } else if (entry.isFile() && entry.name.endsWith('.md')) {
      // 旧的 flat 结构
      results.push({
        fullPath: full,
        folderSlug: path.basename(entry.name, '.md'),
        parentCatFromDir: null,
        isLegacy: true,
        articleDir: POSTS_DIR,
      });
    }
  }

  // 栏目文件夹名必须是 site.config.json 里定义过的 slug（避免拼写错的目录悄悄被扫进来）
  const knownCats = new Set(config.categories.map(c => c.slug));
  for (const r of results) {
    if (r.parentCatFromDir && !knownCats.has(r.parentCatFromDir)) {
      fatal(`扫描到文章目录 "content/posts/${r.parentCatFromDir}/"，但 "站点配置里没有定义这个栏目。`);
    }
  }
  return results;
}

function loadPosts(config) {
  if (!fs.existsSync(POSTS_DIR)) fatal(`文章目录不存在: ${POSTS_DIR}`);
  const entries = walkIndexMd(config);
  if (entries.length === 0) {
    fatal('content/posts/ 下没有找到任何 index.md 或 .md 文件。' +
          '\n  标准结构：content/posts/<栏目slug>/<文章slug>/index.md' +
          '\n  也兼容旧结构：content/posts/*.md');
  }

  const posts = [];
  const slugs = new Set();

  for (const entry of entries) {
    const file = path.relative(ROOT, entry.fullPath);
    const raw = readFile(entry.fullPath);
    const { data, body } = parseFrontMatter(raw);

    // category 解析优先级（翻转后）：
    //   1. 文章所在的栏目文件夹名（最自然的约定，自动识别）
    //   2. front matter 里显式写的 category（覆盖用）
    //   3. 旧 flat 结构下两者都没有 → fatal
    const dirCategory = entry.parentCatFromDir || null;          // 文章所在的栏目文件夹名
    const fmCategory  = data.category ? String(data.category).trim() : null;
    let category;
    if (dirCategory) {
      // 新结构：栏目文件夹名 = 默认 category；front matter 可以显式覆盖
      category = dirCategory;
      if (fmCategory && fmCategory !== dirCategory) {
        console.warn(`  ⚠ ${file}: 文章在 "${dirCategory}/" 下，但 front matter category = "${fmCategory}"。以 front matter 为准。`);
        category = fmCategory;
      }
    } else if (fmCategory) {
      // 旧 flat 结构：没有栏目文件夹，只能靠 front matter
      category = fmCategory;
    } else {
      fatal(`${file}: 无法确定 category。` +
            '\n  建议：把文章放到 content/posts/<栏目slug>/<文章slug>/index.md。' +
            '\n  或者在 front matter 里写 category: xxx。');
    }

    // 必填字段校验（category 已从必填移除）
    const missing = [];
    for (const k of ['title', 'date']) {
      if (!data[k]) missing.push(k);
    }
    if (missing.length) {
      fatal(`${file}: 缺少必填 front matter 字段: ${missing.join(', ')}`);
    }

    // slug：front matter → 文章文件夹名 → 文件名
    let slug = data.slug || entry.folderSlug;
    slug = String(slug).trim();
    if (!slug) {
      fatal(`${file}: 无法确定 slug`);
    }
    if (slugs.has(slug)) fatal(`${file}: slug "${slug}" 重复（和别的文章冲突）`);
    slugs.add(slug);

    // 校验最终 category 是否在 site.config.json 里定义过
    if (!config._catMap[category]) {
      fatal(`${file}: 最终 category "${category}" 在 site.config.json 的 categories 里不存在。` +
            `\n  请在 site.config.json 里添加该栏目，或把文章移动到已定义的栏目文件夹下。`);
    }

    const tags = Array.isArray(data.tags) ? data.tags : [];
    const summary = data.summary || '';

    // 每篇文章自己的目录 → 其下所有非 .md 文件都是它的资源
    const articleDir = entry.articleDir;
    posts.push({
      sourceFile: file,
      sourceAbsPath: entry.fullPath,
      articleDir,                                // 文章文件夹的绝对路径
      isLegacy: entry.isLegacy,                  // true | 'shallow' | false
      slug,
      title: String(data.title),
      date: String(data.date),
      category,                                  // 解析后的最终 category（优先栏目文件夹名）
      tags,
      summary,
      bodyMarkdown: body,
      url: joinUrl(config.site.url, `posts/${slug}.html`),
      relUrl: `/posts/${slug}.html`,
      assetsSiteDir: `/assets/${slug}`,          // 该文章的资源在站点上的根路径
    });
  }

  // 按日期倒序
  posts.sort((a, b) => (a.date < b.date ? 1 : -1));
  return posts;
}

// ---------- 5. 模板 ----------

function siteMeta(config) {
  const s = config.site;
  return {
    name: s.name,
    url: s.url,
    desc: s.description,
    author: s.author,
    lang: s.language || 'zh-CN',
    copyright: s.copyright || `© ${new Date().getFullYear()} ${s.name}`,
    favicon: s.favicon || '/favicon.svg',
  };
}

function buildHeader(config, activePath) {
  const m = siteMeta(config);
  const navItems = config.nav.map(n => {
    const active = n.href === activePath ||
      (activePath === '/' && n.href === '/') ||
      (n.href !== '/' && activePath.startsWith(n.href));
    return `<a href="${n.href}"${active ? ' aria-current="page"' : ''}>${n.label}</a>`;
  }).join('\n        ');

  return `  <header class="site-header">
    <div class="container">
      <a class="site-title" href="/">${escapeHtml(m.name)}</a>
      <nav class="site-nav" aria-label="主导航">
        ${navItems}
      </nav>
    </div>
  </header>`;
}

function buildFooter(config) {
  const m = siteMeta(config);
  return `  <footer class="site-footer">
    <div class="container">
      <span>${escapeHtml(m.copyright)}</span>
      <span>
        <a href="${config.feed.rssPath}">RSS</a> ·
        <a href="${config.feed.jsonPath}">JSON Feed</a> ·
        <a href="${config.feed.llmsPath}">LLMs.txt</a> ·
        <a href="/sitemap.xml">Sitemap</a>
      </span>
    </div>
  </footer>`;
}

function pageShell({ config, activePath, title, description, canonical, body, ogImage, jsonLd, extraHead, extraBody }) {
  const m = siteMeta(config);
  const fullTitle = title && title !== m.name ? `${title} · ${m.name}` : m.name;
  const desc = description || m.desc;
  const can = canonical || m.url;
  const ogImg = ogImage ? escapeHtml(ogImage) : '';

  // 判断 JSON-LD 里是否包含 BlogPosting（文章页 → og:type=article）
  const hasBlogPosting = (function () {
    if (!jsonLd) return false;
    if (Array.isArray(jsonLd)) return jsonLd.some(x => x && x['@type'] === 'BlogPosting');
    return jsonLd['@type'] === 'BlogPosting';
  })();

  const headExtra = [
    `<meta name="description" content="${escapeHtml(desc)}">`,
    `<link rel="canonical" href="${can}">`,
    // Open Graph
    `<meta property="og:site_name" content="${escapeHtml(m.name)}">`,
    `<meta property="og:title" content="${escapeHtml(title || m.name)}">`,
    `<meta property="og:description" content="${escapeHtml(desc)}">`,
    `<meta property="og:url" content="${can}">`,
    `<meta property="og:type" content="${hasBlogPosting ? 'article' : 'website'}">`,
    `<meta property="og:locale" content="${m.lang}">`,
    ogImg && `<meta property="og:image" content="${ogImg}">`,
    // Twitter Card
    `<meta name="twitter:card" content="${ogImg ? 'summary_large_image' : 'summary'}">`,
    `<meta name="twitter:title" content="${escapeHtml(title || m.name)}">`,
    `<meta name="twitter:description" content="${escapeHtml(desc)}">`,
    ogImg && `<meta name="twitter:image" content="${ogImg}">`,
    // JSON-LD
    jsonLd && `<script type="application/ld+json">${JSON.stringify(jsonLd)}</script>`,
    extraHead || '',
  ].filter(Boolean).join('\n    ');

  return `<!doctype html>
<html lang="${m.lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="generator" content="my-static-site-builder">
  <title>${escapeHtml(fullTitle)}</title>
  <link rel="icon" href="${m.favicon || '/favicon.svg'}" type="image/svg+xml">
  <link rel="alternate" type="application/rss+xml" title="${escapeHtml(m.name)} RSS" href="${config.feed.rssPath}">
  <link rel="alternate" type="application/feed+json" title="${escapeHtml(m.name)} JSON Feed" href="${config.feed.jsonPath}">
  <link rel="stylesheet" href="/style.css">
  <!-- KaTeX 数学公式样式（全站引入，tiny CSS） -->
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css" integrity="sha384-nB0miv6/jRmo5UMMR1wu3Gz6NLsoTkbqJghGIsx//Rlm+ZU03BU6SQNC66uf4l5+" crossorigin="anonymous">
    ${headExtra}
</head>
<body>
${buildHeader(config, activePath)}
<main>
${body}
</main>
${buildFooter(config)}
${extraBody || ''}
</body>
</html>`;
}

// ---------- 6. 生成首页 ----------

function buildIndex(config, posts) {
  const m = siteMeta(config);

  // 按栏目分组
  const byCat = {};
  for (const c of config.categories) byCat[c.slug] = [];
  for (const p of posts) byCat[p.category].push(p);

  // Home JSON-LD: Blog
  const blogLd = {
    '@context': 'https://schema.org',
    '@type': 'Blog',
    name: m.name,
    description: m.desc,
    url: m.url,
    author: { '@type': 'Person', name: m.author },
    blogPost: posts.map(p => ({
      '@type': 'BlogPosting',
      headline: p.title,
      datePublished: p.date,
      url: p.url,
    })),
  };

  // 搜索框
  const searchBar = `  <div class="search-bar" role="search">
    <label for="site-search" class="sr-only" hidden>搜索文章</label>
    <input id="site-search" type="search" placeholder="搜索文章标题或标签…" autocomplete="off">
  </div>`;

  // 栏目块
  const sectionsHtml = config.categories.map(cat => {
    const list = byCat[cat.slug] || [];
    if (list.length === 0) return '';
    const itemsHtml = list.map(p => {
      const tags = p.tags.length ? `<span class="tags">${p.tags.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join('')}</span>` : '';
      return `      <li class="article-item" data-title="${escapeHtml(p.title.toLowerCase())}" data-tags="${escapeHtml(p.tags.join(' ').toLowerCase())}">
        <a class="article-link" href="${p.relUrl}">${escapeHtml(p.title)}</a>
        <div class="meta">
          <a class="cat" href="/category/${cat.slug}.html" rel="tag">${escapeHtml(cat.name)}</a>
          <span class="sep">·</span>
          <time datetime="${p.date}">${formatDate(p.date)}</time>
        </div>
        ${p.summary ? `<div class="summary">${escapeHtml(p.summary)}</div>` : ''}
        ${tags}
      </li>`;
    }).join('\n');

    return `  <section class="category-section" data-category="${cat.slug}">
    <h2 class="category-title"><a href="/category/${cat.slug}.html">${escapeHtml(cat.name)}</a></h2>
    <p class="category-meta">${escapeHtml(cat.description)} · ${list.length} 篇</p>
    <ul class="article-list">
${itemsHtml}
    </ul>
  </section>`;
  }).filter(Boolean).join('\n');

  const noResultsHtml = `  <p class="no-results" id="no-results" hidden>没有找到匹配的文章。</p>`;

  const body = `  <div class="container">
    <h1 class="page-title">${escapeHtml(m.name)}</h1>
    <p class="page-desc">${escapeHtml(m.desc)}</p>
${searchBar}
    <div class="home-grid" id="home-grid">
${sectionsHtml}
    </div>
${noResultsHtml}
  </div>

  <script>
  (function () {
    var input = document.getElementById('site-search');
    if (!input) return;
    var items = document.querySelectorAll('.article-item');
    var sections = document.querySelectorAll('.category-section');
    var noResults = document.getElementById('no-results');

    function filter() {
      var q = input.value.trim().toLowerCase();
      var anyShown = false;
      sections.forEach(function (sec) {
        var secShown = false;
        var secItems = sec.querySelectorAll('.article-item');
        secItems.forEach(function (li) {
          var hay = (li.getAttribute('data-title') || '') + ' ' + (li.getAttribute('data-tags') || '');
          var show = !q || hay.indexOf(q) !== -1;
          li.classList.toggle('is-hidden', !show);
          if (show) { secShown = true; anyShown = true; }
        });
        sec.hidden = !secShown;
      });
      if (noResults) noResults.hidden = anyShown;
    }

    input.addEventListener('input', filter);
    // 清除搜索时也重置
    input.addEventListener('search', filter);
  })();
  </script>`;

  return pageShell({
    config,
    activePath: '/',
    title: m.name,
    description: m.desc,
    canonical: m.url,
    jsonLd: blogLd,
    body,
  });
}

// ---------- 7. 生成栏目页 ----------

function buildCategoryPage(config, cat, posts) {
  const catPosts = posts.filter(p => p.category === cat.slug);

  // JSON-LD: BreadcrumbList + CollectionPage
  const breadcrumb = {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: '首页', item: config.site.url },
      { '@type': 'ListItem', position: 2, name: cat.name, item: joinUrl(config.site.url, `category/${cat.slug}.html`) },
    ],
  };

  const listHtml = catPosts.map(p => {
    return `      <li class="article-item">
        <a class="article-link" href="${p.relUrl}">${escapeHtml(p.title)}</a>
        <div class="meta">
          <time datetime="${p.date}">${formatDate(p.date)}</time>
        </div>
        ${p.summary ? `<div class="summary">${escapeHtml(p.summary)}</div>` : ''}
      </li>`;
  }).join('\n');

  const body = `  <div class="container">
    <div class="breadcrumb"><a href="/">首页</a> / <span>${escapeHtml(cat.name)}</span></div>
    <h1 class="page-title">${escapeHtml(cat.name)}</h1>
    <p class="page-desc">${escapeHtml(cat.description)} · 共 ${catPosts.length} 篇</p>
    <ul class="article-list">
${listHtml}
    </ul>
  </div>`;

  return pageShell({
    config,
    activePath: `/category/${cat.slug}.html`,
    title: cat.name,
    description: cat.description,
    canonical: joinUrl(config.site.url, `category/${cat.slug}.html`),
    jsonLd: breadcrumb,
    body,
  });
}

// ---------- 8. 生成文章页 ----------

function buildPostPage(config, post, posts) {
  const m = siteMeta(config);
  const cat = config._catMap[post.category];

  // BreadcrumbList
  const breadcrumb = {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: '首页', item: m.url },
      { '@type': 'ListItem', position: 2, name: cat.name, item: joinUrl(m.url, `category/${cat.slug}.html`) },
      { '@type': 'ListItem', position: 3, name: post.title, item: post.url },
    ],
  };

  // BlogPosting
  const articleLd = {
    '@context': 'https://schema.org',
    '@type': 'BlogPosting',
    headline: post.title,
    description: post.summary,
    datePublished: post.date,
    dateModified: post.date,
    author: { '@type': 'Person', name: m.author },
    publisher: { '@type': 'Organization', name: m.name, url: m.url },
    mainEntityOfPage: { '@type': 'WebPage', '@id': post.url },
    articleSection: cat.name,
    keywords: post.tags.join(', '),
  };

  // 上一篇/下一篇
  const idx = posts.findIndex(p => p.slug === post.slug);
  const prev = posts[idx + 1]; // 倒序，上一篇 = 日期更早
  const next = posts[idx - 1];
  const navHtml = `    <nav class="article-nav" aria-label="文章导航">
      ${prev ? `<a href="${prev.relUrl}" rel="prev">← ${escapeHtml(prev.title)}</a>` : '<span></span>'}
      ${next ? `<a href="${next.relUrl}" rel="next">${escapeHtml(next.title)} →</a>` : ''}
    </nav>`;

  const tagsHtml = post.tags.length
    ? `<span class="tags">${post.tags.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join('')}</span>`
    : '';

  const body = `  <article>
    <div class="container">
      <div class="breadcrumb">
        <a href="/">首页</a> / <a href="/category/${cat.slug}.html">${escapeHtml(cat.name)}</a> / <span>${escapeHtml(post.title)}</span>
      </div>
      <header class="article-header">
        <h1 class="page-title">${escapeHtml(post.title)}</h1>
        <div class="meta">
          <time datetime="${post.date}">${formatDate(post.date)}</time>
          <span>栏目: <a href="/category/${cat.slug}.html">${escapeHtml(cat.name)}</a></span>
          ${tagsHtml}
        </div>
      </header>
      <div class="article-body">
${post.bodyHtml}
      </div>
${navHtml}
    </div>
  </article>`;

  // 合并两个 JSON-LD
  const mergedLd = [breadcrumb, articleLd];

  // KaTeX auto-render：只在文章详情页加载（首页/栏目页通常没数学公式）
  // 语法约定：$...$ 行内、$$...$$ 块级；支持 \$ 转义字面量 $
  const katexScript = `
  <!-- KaTeX auto-render 数学公式自动扫描渲染 -->
  <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js" integrity="sha384-7MPPZK+n7U2+jwlII5Vatjr+8V4pZsgwaOs3uGR0sQoMhvrj3HbshVAydFVgwc6" crossorigin="anonymous"></script>
  <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js" integrity="sha384-hUV2yhElN6C86HYm7nXoKc4kXKQnO/JOqB0OQ3C6cE7hYw9P0jJ9hVhP1GdQpY0Hm" crossorigin="anonymous" onload="renderMathInElement(document.body,{delimiters:[{left:'$$',right:'$$',display:true},{left:'$',right:'$',display:false}],throwOnError:false,strict:false})"></script>`;

  return pageShell({
    config,
    activePath: post.relUrl,
    title: post.title,
    description: post.summary || post.title,
    canonical: post.url,
    jsonLd: mergedLd,
    body,
    extraBody: katexScript,
  });
}

// ---------- 9. 生成关于页 ----------

function buildAboutPage(config) {
  const m = siteMeta(config);
  const body = `  <div class="container">
    <h1 class="page-title">关于本站</h1>
    <p class="page-desc">${escapeHtml(m.desc)}</p>
    <p>本站由 <strong>${escapeHtml(m.author)}</strong> 维护，内容使用 Markdown 编写，
    通过零依赖的 Node.js 构建脚本生成静态 HTML。</p>
    <p>栏目与文章列表：</p>
    <ul>
      ${config.categories.map(c => `<li><a href="/category/${c.slug}.html">${escapeHtml(c.name)}</a> — ${escapeHtml(c.description)}</li>`).join('\n      ')}
    </ul>
  </div>`;
  return pageShell({
    config,
    activePath: '/about.html',
    title: '关于',
    description: `关于${m.name}`,
    canonical: joinUrl(m.url, 'about.html'),
    body,
  });
}

// ---------- 10. 生成 sitemap.xml ----------

function buildSitemap(config, posts) {
  const urls = [
    { loc: config.site.url, priority: '1.0' },
    { loc: joinUrl(config.site.url, 'about.html'), priority: '0.5' },
    ...config.categories.map(c => ({ loc: joinUrl(config.site.url, `category/${c.slug}.html`), priority: '0.7' })),
    ...posts.map(p => ({ loc: p.url, priority: '0.8' })),
  ];

  const lastmod = lastModDate();
  const entries = urls.map(u => `  <url>
    <loc>${escapeXml(u.loc)}</loc>
    <lastmod>${lastmod}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>${u.priority}</priority>
  </url>`).join('\n');

  return `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${entries}
</urlset>
`;
}

// ---------- 11. 生成 rss.xml ----------

function buildRss(config, posts) {
  const m = siteMeta(config);
  const items = posts.map(p => {
    const cat = config._catMap[p.category];
    return `  <item>
    <title>${escapeXml(p.title)}</title>
    <link>${p.url}</link>
    <guid isPermaLink="true">${p.url}</guid>
    <pubDate>${new Date(isoDate(p.date)).toUTCString()}</pubDate>
    <category>${escapeXml(cat.name)}</category>
    <description>${escapeXml(p.summary || p.title)}</description>
  </item>`;
  }).join('\n');

  return `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>${escapeXml(m.name)}</title>
  <link>${m.url}</link>
  <description>${escapeXml(m.desc)}</description>
  <language>${m.lang}</language>
  <lastBuildDate>${new Date().toUTCString()}</lastBuildDate>
${items}
</channel>
</rss>
`;
}

// ---------- 12. 生成 feed.json (JSON Feed 1.1) ----------

function buildJsonFeed(config, posts) {
  const m = siteMeta(config);
  const feed = {
    version: 'https://jsonfeed.org/version/1.1',
    title: m.name,
    description: m.desc,
    home_page_url: m.url,
    feed_url: joinUrl(m.url, 'feed.json'),
    language: m.lang,
    authors: [{ name: m.author }],
    items: posts.map(p => {
      const cat = config._catMap[p.category];
      return {
        id: p.url,
        url: p.url,
        title: p.title,
        content_html: p.bodyHtml,
        summary: p.summary,
        date_published: isoDate(p.date),
        tags: [cat.name, ...p.tags],
      };
    }),
  };
  return JSON.stringify(feed, null, 2) + '\n';
}

// ---------- 13. 生成 llms.txt ----------

function buildLlmsTxt(config, posts) {
  const m = siteMeta(config);
  let out = `# ${m.name}\n\n`;
  out += `${m.desc}\n\n`;
  out += `- URL: ${m.url}\n`;
  out += `- Author: ${m.author}\n`;
  out += `- Language: ${m.lang}\n\n`;
  out += `## Categories\n\n`;
  for (const c of config.categories) {
    out += `- [${c.name}](${joinUrl(m.url, `category/${c.slug}.html`)}) — ${c.description}\n`;
  }
  out += `\n## Posts\n\n`;
  for (const p of posts) {
    out += `- [${p.title}](${p.url}) — ${p.date} — ${p.summary || ''}\n`;
  }
  out += `\n## Feeds\n\n`;
  out += `- RSS: ${joinUrl(m.url, 'rss.xml')}\n`;
  out += `- JSON Feed: ${joinUrl(m.url, 'feed.json')}\n`;
  return out;
}

// ---------- 主流程 ----------

function main() {
  log('读取 site.config.json …');
  const config = loadConfig();
  log(`站点: ${config.site.name} (${config.site.url})`);

  log('扫描 content/posts/<栏目>/<slug>/index.md …');
  const posts = loadPosts(config);
  log(`共 ${posts.length} 篇文章`);

  // 每篇文章的文件夹下 → 拷贝非 .md 文件到 /assets/<slug>/
  let total = 0;
  for (const p of posts) total += syncAssetsForPost(p);
  if (total) log(`同步文章资源  → /assets/<slug>/  (共 ${total} 个文件)`);

  // 兼容旧的全局桶 content/posts/images/ / content/posts/resources/
  syncSharedBuckets();

  // 先渲染正文（带着各自的 assetsSiteDir 上下文）
  for (const p of posts) {
    p.bodyHtml = renderMarkdown(p.bodyMarkdown, p.isLegacy ? null : p.assetsSiteDir);
  }

  // 写文章详情页
  log('生成文章详情页 …');
  ensureDir(OUT_POSTS_DIR);
  for (const p of posts) {
    const html = buildPostPage(config, p, posts);
    writeFile(path.join(OUT_POSTS_DIR, `${p.slug}.html`), html);
    log(`  ✓ posts/${p.slug}.html`);
  }

  // 写栏目页
  log('生成栏目页 …');
  ensureDir(OUT_CATEGORY_DIR);
  for (const c of config.categories) {
    const html = buildCategoryPage(config, c, posts);
    writeFile(path.join(OUT_CATEGORY_DIR, `${c.slug}.html`), html);
    log(`  ✓ category/${c.slug}.html`);
  }

  // 写首页
  log('生成首页 …');
  writeFile(path.join(ROOT, 'index.html'), buildIndex(config, posts));
  log('  ✓ index.html');

  // 关于页
  writeFile(path.join(ROOT, 'about.html'), buildAboutPage(config));
  log('  ✓ about.html');

  // 索引文件
  log('生成 sitemap.xml / rss.xml / feed.json / llms.txt …');
  writeFile(path.join(ROOT, 'sitemap.xml'), buildSitemap(config, posts));
  log('  ✓ sitemap.xml');
  writeFile(path.join(ROOT, 'rss.xml'), buildRss(config, posts));
  log('  ✓ rss.xml');
  writeFile(path.join(ROOT, 'feed.json'), buildJsonFeed(config, posts));
  log('  ✓ feed.json');
  writeFile(path.join(ROOT, 'llms.txt'), buildLlmsTxt(config, posts));
  log('  ✓ llms.txt');

  log('完成 ✅');
}

try {
  main();
} catch (err) {
  console.error(err.stack || err);
  process.exit(1);
}
