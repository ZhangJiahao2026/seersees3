#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
blogctl —— 静态博客站点一体化运维工具
======================================

配套本仓库的 Node.js 构建脚本 (build.js)，提供：
  1) 站点配置读写（site.config.json 增删改查）
  2) 文章全生命周期管理（新建 / 列表 / 编辑 / 查看）
  3) 构建 + Git 一键推送（deploy 子命令）

零第三方依赖，仅 Python 3.8+ 标准库。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, List, Optional

# ---------------------------------------------------------------------------
# 基础常量
# ---------------------------------------------------------------------------

# 站点根目录：默认是本文件的父目录的父目录（tools/blogctl.py → /workspace）
DEFAULT_BLOG_DIR = Path(__file__).resolve().parent.parent
CONFIG_NAME = "site.config.json"
BUILDER = "build.js"
POSTS_DIR = Path("content") / "posts"


def scan_index_md(blog_dir: Path) -> List[Path]:
    """
    统一扫描文章源文件（新结构 + 旧 flat 结构兼容）。

    新结构（推荐）：content/posts/<栏目slug>/<文章slug>/index.md
    旧结构（兼容）：content/posts/*.md

    返回所有找到的 index.md / .md 文件路径列表（绝对路径）。
    """
    posts_dir = blog_dir / POSTS_DIR
    if not posts_dir.exists():
        return []

    results: List[Path] = []
    for entry in posts_dir.iterdir():
        if entry.is_dir():
            # 栏目目录 → 再下一层找文章文件夹
            for sub in entry.iterdir():
                if sub.is_dir():
                    idx = sub / "index.md"
                    if idx.exists():
                        results.append(idx)
                elif sub.is_file() and sub.name.endswith(".md"):
                    # 兼容过渡：content/posts/<cat>/xxx.md
                    results.append(sub)
        elif entry.is_file() and entry.name.endswith(".md"):
            # 旧的 flat 结构
            results.append(entry)

    return sorted(results)


def find_index_by_slug(blog_dir: Path, slug: str) -> Optional[Path]:
    """
    按 slug 查找 index.md。优先级：
      1. content/posts/<cat>/<slug>/index.md（新结构）
      2. content/posts/<cat>/<slug>.md（过渡结构）
      3. content/posts/<slug>.md（旧 flat 结构）
    4. 扫描所有 index.md 读 front matter 里的 slug 字段兜底
    """
    posts_dir = blog_dir / POSTS_DIR

    # 逐个栏目尝试新结构
    if posts_dir.exists():
        for cat_entry in posts_dir.iterdir():
            if cat_entry.is_dir():
                c = cat_entry / slug / "index.md"
                if c.exists():
                    return c
                c_shallow = cat_entry / f"{slug}.md"          # 过渡结构
                if c_shallow.exists():
                    return c_shallow

    # 旧 flat 结构
    old_flat = posts_dir / f"{slug}.md"
    if old_flat.exists():
        return old_flat

    # 最后兜底：扫描所有 index.md 读 front matter 里的 slug
    for f in scan_index_md(blog_dir):
        try:
            text = f.read_text(encoding="utf-8")
            fm, _ = parse_front_matter(text)
            if fm.get("slug") == slug:
                return f
        except Exception:
            continue
    return None


def resolve_category(index_md: Path, fm: dict) -> str:
    """
    和 build.js 保持完全一致的 category 解析逻辑：
      1. front matter 里显式写了 category → 用它
      2. 否则看文章所在的栏目文件夹名（content/posts/<cat>/... 里的 <cat>）
      3. 旧 flat 结构下两者都没有 → 返回 "(未分类)"
    """
    fm_cat = fm.get("category")
    if fm_cat:
        return str(fm_cat).strip()

    posts_dir_name = POSTS_DIR.name  # "posts"
    parts = index_md.parts
    if posts_dir_name in parts:
        idx = parts.index(posts_dir_name)
        if idx + 1 < len(parts):
            # posts/ 之后紧接的是栏目文件夹（不是 index.md 所在的文章文件夹）
            # 路径：.../content/posts/<栏目>/<slug>/index.md
            cat = parts[idx + 1]
            if cat != index_md.parent.name:  # sanity：不是文章文件夹名
                return cat

    return "(未分类)"

# Git add 时排除的路径（相对于 BLOG_DIR）
GIT_IGNORED_DIRS = {
    ".git", ".gitignore", "__pycache__", ".DS_Store",
    "*.pyc", "*.pyo", "*.log", "*.swp", ".vscode", ".idea",
}


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def cprint(text: str, color: str = "") -> None:
    """彩色打印（仅 ANSI 终端生效，Windows 原生 cmd 上会退化为纯文本）。"""
    colors = {
        "green": "\033[32m", "red": "\033[31m", "yellow": "\033[33m",
        "cyan": "\033[36m", "bold": "\033[1m", "reset": "\033[0m",
    }
    if not color or not sys.stdout.isatty():
        print(text)
        return
    prefix = colors.get(color, "")
    print(f"{prefix}{text}{colors['reset']}")


def die(msg: str, code: int = 1) -> None:
    cprint(f"[blogctl][error] {msg}", "red")
    sys.exit(code)


def run(
    cmd: list[str],
    cwd: Path,
    check: bool = True,
    capture: bool = False,
    timeout: Optional[int] = None,
) -> subprocess.CompletedProcess:
    """统一的 subprocess 包装：list 形式、不拼 shell、跨平台安全。"""
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            shell=False,             # 关键：避免 PowerShell / bash 差异
            check=check,
            capture_output=capture,
            text=True,
            timeout=timeout,
        )
        return result
    except FileNotFoundError:
        die(f"找不到可执行文件: {cmd[0]}（请确认已安装并在 PATH 中）")
    except subprocess.TimeoutExpired:
        die(f"命令超时: {' '.join(cmd)}")
    except subprocess.CalledProcessError as exc:
        # Git 等工具会把错误写 stderr；Node.js 工具两向都有
        err = (exc.stderr or exc.stdout or str(exc)).strip()
        die(f"命令失败: {' '.join(cmd)}\n{err}")


def read_json(path: Path) -> dict:
    if not path.exists():
        die(f"文件不存在: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def today_str() -> str:
    return _dt.date.today().isoformat()


def slugify(text: str) -> str:
    """中文友好的简单 slug：小写、替换非字母数字为连字符。"""
    import re
    s = text.lower().strip()
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "post"


def default_editor() -> str:
    """选择默认编辑器：优先环境变量，其次按 OS 兜底。"""
    if os.environ.get("EDITOR"):
        return os.environ["EDITOR"]
    if os.environ.get("VISUAL"):
        return os.environ["VISUAL"]
    sys_name = platform.system().lower()
    if sys_name == "windows":
        return "notepad"
    if sys_name == "darwin":
        return "open -t"  # 用默认编辑器打开文本
    return "vi"


def open_in_editor(file_path: Path) -> None:
    """用系统默认编辑器打开文件。"""
    editor = default_editor()
    cprint(f"  → 用 {editor} 打开 {file_path.name}", "cyan")
    # macOS 的 'open -t' 需要用 shell=True，其他走 list
    if editor == "open -t":
        subprocess.run(f'open -t "{file_path}"', shell=True, check=False)
    else:
        subprocess.run([editor, str(file_path)], check=False)


# ---------------------------------------------------------------------------
# 配置相关
# ---------------------------------------------------------------------------

def resolve_blog_dir(cli_path: Optional[str]) -> Path:
    target = Path(cli_path).resolve() if cli_path else DEFAULT_BLOG_DIR
    if not target.is_dir():
        die(f"博客目录不存在: {target}")
    config = target / CONFIG_NAME
    if not config.exists():
        die(f"{CONFIG_NAME} 缺失: {config}（这看起来不是一个有效的博客根目录）")
    return target


def config_show(blog_dir: Path) -> None:
    cfg = read_json(blog_dir / CONFIG_NAME)
    cprint(json.dumps(cfg, ensure_ascii=False, indent=2), "cyan")


def _dig(cfg: dict, dotted_key: str) -> tuple[dict, str]:
    """把 'site.name' 拆成 (parent_dict, last_key)。"""
    keys = dotted_key.split(".")
    cur = cfg
    for k in keys[:-1]:
        if not isinstance(cur, dict) or k not in cur:
            die(f"键不存在: {dotted_key}（在 '{k}' 处中断）")
        cur = cur[k]
        if not isinstance(cur, dict):
            die(f"键路径 {dotted_key} 中途遇到非字典值，无法继续深入")
    return cur, keys[-1]


def _coerce_json_value(raw: str) -> Any:
    """命令行传的都是字符串，尝试转成 bool/int/float/null/JSON。"""
    lower = raw.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower in ("null", "none", "~"):
        return None
    try:
        return json.loads(raw)  # 支持 "[1,2]" / '{"a":1}' 这种合法 JSON
    except json.JSONDecodeError:
        pass
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        return raw  # 最终退回字符串


def config_set(blog_dir: Path, key: str, raw_value: str) -> None:
    cfg = read_json(blog_dir / CONFIG_NAME)
    parent, last = _dig(cfg, key)
    value = _coerce_json_value(raw_value)
    parent[last] = value
    write_json(blog_dir / CONFIG_NAME, cfg)
    cprint(f"[ok] {key} = {json.dumps(value, ensure_ascii=False)}", "green")


def config_open(blog_dir: Path) -> None:
    open_in_editor(blog_dir / CONFIG_NAME)


# ---------------------------------------------------------------------------
# 文章相关
# ---------------------------------------------------------------------------

def parse_front_matter(text: str) -> tuple[dict, str]:
    """从 Markdown 文本分离 front matter 和正文。"""
    import re
    m = re.match(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?", text)
    if not m:
        return {}, text
    yaml = m.group(1)
    rest = text[m.end():]
    # 简单 YAML 子集（与 build.js 保持一致）
    data = {}
    for raw_line in yaml.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        colon = line.find(":")
        if colon == -1:
            continue
        k = line[:colon].strip()
        v = line[colon + 1:].strip()
        if v.startswith("[") and v.endswith("]"):
            v = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
        else:
            v = v.strip("'\"")
        data[k] = v
    return data, rest


def render_front_matter(data: dict) -> str:
    """把 dict 回写成 YAML front matter 字符串。"""
    lines = ["---"]
    for k, v in data.items():
        if isinstance(v, list):
            items = ", ".join(str(x) for x in v)
            lines.append(f"{k}: [{items}]")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def ensure_categories(cfg: dict) -> list[str]:
    return [c["slug"] for c in cfg.get("categories", [])]


def new_post(
    blog_dir: Path,
    *,
    slug: Optional[str] = None,
    title: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[list[str]] = None,
    date: Optional[str] = None,
    summary: Optional[str] = None,
    no_open: bool = False,
) -> Path:
    cfg = read_json(blog_dir / CONFIG_NAME)
    allowed_cats = ensure_categories(cfg)

    # 确定栏目：交互式
    if category is None:
        cprint("可选栏目:", "cyan")
        for i, c in enumerate(cfg["categories"], 1):
            print(f"  {i}) {c['name']}  (slug: {c['slug']})")
        while True:
            pick = _safe_input("选择栏目编号 (或输入 slug): ")
            if pick.isdigit():
                idx = int(pick) - 1
                if 0 <= idx < len(cfg["categories"]):
                    category = cfg["categories"][idx]["slug"]
                    break
            elif pick in allowed_cats:
                category = pick
                break
            cprint("  无效，请重试", "yellow")
    if category not in allowed_cats:
        die(f"栏目 '{category}' 未在 site.config.json 中定义。有效栏目: {allowed_cats}")

    if title is None:
        title = _safe_input("文章标题: ") or "未命名文章"

    if slug is None:
        slug = _safe_input(f"slug [默认 {slugify(title)}]: ") or slugify(title)

    if tags is None:
        raw = _safe_input("标签（逗号分隔，可留空）: ")
        tags = [t.strip() for t in raw.split(",") if t.strip()]

    if date is None:
        date = _safe_input(f"日期 [默认 {today_str()}]: ") or today_str()

    if summary is None:
        summary = _safe_input("摘要（可留空）: ")

    posts_dir = blog_dir / POSTS_DIR
    article_dir = posts_dir / category / slug
    article_dir.mkdir(parents=True, exist_ok=True)
    target = article_dir / "index.md"
    if target.exists():
        die(f"文章已存在: {target}（slug '{slug}' 重复，请换一个）")

    # front matter 里默认不写 category —— 构建脚本会从文章所在的栏目文件夹名自动识别
    # 如果以后想显式覆盖，可以手动加一行 category: xxx
    front = {
        "title": title,
        "date": date,
        "tags": tags,
        "summary": summary,
        "slug": slug,
    }
    body = render_front_matter(front)
    body += (
        "\n## 正文\n\n"
        "从这里开始写正文。支持标准 Markdown：标题、列表、代码块、引用、链接、图片。\n\n"
        "> 放图片/PDF 就把文件丢在本文章文件夹里，然后在 Markdown 里写相对路径就行，"
        "构建脚本会自动规整。例如：`![封面](cover.svg)` / `[下载资料](paper.pdf)`。\n"
    )
    target.write_text(body, encoding="utf-8")

    cprint(f"[ok] 已创建 {target}", "green")
    cprint(f"    栏目归属: {category}  （自动识别自目录 content/posts/{category}/）", "cyan")
    cprint(f"    文章资源目录: {article_dir} （可以直接往里面丢图片/PDF）", "cyan")
    if not no_open:
        open_in_editor(target)
    return target


def list_posts(blog_dir: Path) -> None:
    md_files = scan_index_md(blog_dir)
    if not md_files:
        cprint("（还没有任何文章）", "yellow")
        cprint("  提示：文章应放在 content/posts/<栏目>/<slug>/index.md 下", "cyan")
        return

    rows = []
    for f in md_files:
        try:
            text = f.read_text(encoding="utf-8")
            fm, _ = parse_front_matter(text)
            rows.append({
                "slug": fm.get("slug", f.parent.name),
                "title": fm.get("title", "(无标题)"),
                "date": fm.get("date", "(无日期)"),
                "category": resolve_category(f, fm),
                "tags": ", ".join(fm.get("tags", [])) or "-",
                "source": f,
            })
        except Exception as e:
            cprint(f"  ⚠ 解析失败 {f}: {e}", "yellow")

    rows.sort(key=lambda r: r["date"], reverse=True)

    header = f"{'DATE':12}  {'CATEGORY':<10}  {'SLUG':<24}  TITLE"
    cprint(header, "bold")
    cprint("-" * len(header), "bold")
    for r in rows:
        print(
            f"{r['date']:12}  {r['category']:<10}  {r['slug']:<24}  {r['title']}"
        )
    print(f"\n共 {len(rows)} 篇文章。")


def find_post(blog_dir: Path, slug_or_file: str) -> Optional[Path]:
    """按 slug 或文件路径查找文章。优先 slug 匹配（能找新结构），其次作为路径直接找。"""
    # 先试直接当路径
    direct = Path(slug_or_file)
    if direct.exists():
        return direct.resolve()
    as_blog_rel = blog_dir / slug_or_file
    if as_blog_rel.exists():
        return as_blog_rel.resolve()
    # 再试按 slug 查找（新结构 + 旧结构都覆盖）
    return find_index_by_slug(blog_dir, slug_or_file)


def show_post(blog_dir: Path, slug: str) -> None:
    path = find_post(blog_dir, slug)
    if path is None:
        die(f"找不到文章: {slug}")
    text = path.read_text(encoding="utf-8")
    fm, body = parse_front_matter(text)
    cprint(f"文件: {path}", "cyan")
    for k in ("title", "date", "category", "slug", "summary"):
        if k in fm:
            print(f"  {k}: {fm[k]}")
    if fm.get("tags"):
        print(f"  tags: {', '.join(fm['tags'])}")
    print(f"\n正文预览:")
    cprint(body.strip()[:400], "cyan")
    if len(body.strip()) > 400:
        print("  …（截断）")


def edit_post(blog_dir: Path, slug: str) -> None:
    path = find_post(blog_dir, slug)
    if path is None:
        die(f"找不到文章: {slug}（先运行 `blogctl post list` 查看所有 slug）")
    open_in_editor(path)


# ---------------------------------------------------------------------------
# 构建 + Git 推送
# ---------------------------------------------------------------------------

def _safe_input(prompt: str) -> str:
    """带 EOF 容错的 input()：管道/CI 场景下不要抛 traceback。"""
    try:
        return input(prompt).strip()
    except EOFError:
        die("当前环境不支持交互式输入。请:\n"
            "  - 在有 TTY 的终端里运行本命令，或\n"
            "  - 先用 `git remote add origin <URL>` 配置好再运行，或\n"
            "  - 使用非交互式方式: blogctl deploy --remote <URL> --branch <branch>")


def ensure_git_repo(blog_dir: Path, *, interactive: bool = True) -> None:
    """确认 blog_dir 是一个 Git 仓库，且已配置 remote origin。

    interactive=False 时（如 dry-run / CI 脚本），只做只读检查，
    缺失项以 warn 形式提示，不触发 input()。
    """
    if not (blog_dir / ".git").exists():
        if not interactive:
            cprint("[warn] 不是 Git 仓库（dry-run 跳过交互式初始化）", "yellow")
            return
        cprint(f"[warn] {blog_dir} 不是 Git 仓库", "yellow")
        init = _safe_input("是否现在初始化？(y/N): ").lower()
        if init == "y":
            run(["git", "init"], cwd=blog_dir)
            cprint("[ok] 已执行 git init", "green")
            cprint("  接下来请用 `git remote add origin <URL>` 添加远程仓库，再运行本脚本。", "yellow")
        sys.exit(0)

    # 检查是否有 remote origin
    res = run(["git", "remote"], cwd=blog_dir, capture=True, check=False)
    remotes = set(res.stdout.strip().splitlines())
    if "origin" not in remotes:
        if not interactive:
            cprint("[warn] 未配置 remote 'origin'（dry-run 跳过交互式配置）", "yellow")
            return
        cprint("[warn] 未配置 remote 'origin'", "yellow")
        url = _safe_input("origin 仓库 URL (可留空跳过): ")
        if url:
            run(["git", "remote", "add", "origin", url], cwd=blog_dir)
            cprint(f"[ok] origin = {url}", "green")
        else:
            die("未配置 remote，无法推送。请先 `git remote add origin <URL>`。")


def _check_git_identity(blog_dir: Path) -> None:
    """检查 git user.name / user.email 是否已配置，commit 前必须通过。"""
    def get(key: str) -> str:
        r = run(["git", "config", key], cwd=blog_dir, capture=True, check=False)
        return r.stdout.strip()

    name = get("user.name")
    email = get("user.email")
    missing = []
    if not name:
        missing.append("user.name")
    if not email:
        missing.append("user.email")
    if missing:
        die(
            "Git 未配置身份信息: " + ", ".join(missing) + "\n"
            "  请运行:\n"
            "    git config user.name  '你的名字'\n"
            "    git config user.email 'your@email.com'\n"
            "  （加 --global 则对所有仓库生效）"
        )


def _has_any_commit(blog_dir: Path) -> bool:
    """判断仓库是否已经有至少一个 commit（HEAD 存在）。"""
    r = run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=blog_dir, capture=True, check=False,
    )
    return r.returncode == 0


def git_status_changes(blog_dir: Path) -> tuple[list[str], list[str]]:
    """返回 (已暂存变更文件列表, 未暂存变更文件列表)。"""
    res = run(["git", "status", "--porcelain"], cwd=blog_dir, capture=True)
    staged, unstaged = [], []
    for line in res.stdout.splitlines():
        if len(line) < 4:
            continue
        flag = line[:2]
        path = line[3:].strip()
        if flag[0] != " ":
            staged.append(path)
        if flag[1] != " ":
            unstaged.append(path)
    return staged, unstaged


def _diff_name_only(blog_dir: Path, against: str = "HEAD") -> list[str]:
    res = run(["git", "diff", "--name-only", against], cwd=blog_dir, capture=True, check=False)
    return [l.strip() for l in res.stdout.splitlines() if l.strip()]


def build_site(blog_dir: Path) -> None:
    """调用 Node.js 的 build.js。"""
    builder = blog_dir / BUILDER
    if not builder.exists():
        die(f"找不到 {BUILDER}")
    cprint(f"→ node {BUILDER}", "cyan")
    res = run(["node", str(BUILDER)], cwd=blog_dir, check=False)
    if res.returncode != 0:
        die(f"构建失败（node 退出码 {res.returncode}）。请检查 build.js 的输出。")
    cprint("[ok] 构建完成", "green")


def _assemble_commit_msg(blog_dir: Path, custom_msg: Optional[str]) -> str:
    if custom_msg:
        return custom_msg
    ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    if _has_any_commit(blog_dir):
        changes = _diff_name_only(blog_dir)
        label = ", ".join(changes[:5]) or "站点更新"
        if len(changes) > 5:
            label += f" 等 {len(changes)} 个文件"
    else:
        label = "首次提交"
    return f"build: {ts} — {label}"


def _collect_staged_targets(blog_dir: Path) -> list[str]:
    """git add 哪些路径：白名单式，避免把 __pycache__ 等脏文件带进去。"""
    all_things = run(["git", "status", "--porcelain", "-z"], cwd=blog_dir, capture=True)
    entries = all_things.stdout.split("\0")
    targets = []
    for entry in entries:
        if not entry:
            continue
        # 前 2 字符是状态，第 3 字符是空格，后面是路径
        path = entry[3:]
        if path.endswith("/"):
            continue
        # 过滤忽略项
        parts = Path(path).parts
        if any(p in GIT_IGNORED_DIRS for p in parts):
            continue
        if any(path.endswith(ig) for ig in ("__pycache__",)):
            continue
        targets.append(path)
    return targets


def deploy(
    blog_dir: Path,
    *,
    commit_msg: Optional[str] = None,
    skip_build: bool = False,
    dry_run: bool = False,
    remote: str = "origin",
    branch: Optional[str] = None,
) -> None:
    """构建 → 提交 → 推送 的一条龙。"""
    # 1) 构建
    if not skip_build:
        build_site(blog_dir)

    # 2) 确认 Git 环境
    ensure_git_repo(blog_dir, interactive=not dry_run)

    # 3) 看看有什么变更
    all_changes = _collect_staged_targets(blog_dir)
    if not all_changes:
        cprint("[info] 没有任何变更需要提交（构建后无差异），跳过 push。", "yellow")
        return

    cprint(f"本次将提交 {len(all_changes)} 个文件:", "cyan")
    for p in all_changes[:15]:
        print(f"  - {p}")
    if len(all_changes) > 15:
        print(f"  … 还有 {len(all_changes) - 15} 个文件")
    if dry_run:
        cprint("\n[dry-run] 到此为止，未执行 git add/commit/push。", "yellow")
        cprint(f"          提交消息: {_assemble_commit_msg(blog_dir, commit_msg)}", "yellow")
        cprint("          如需真正推送，请去掉 --dry-run 并确保：", "yellow")
        cprint("            1) git config user.name / user.email 已设置", "yellow")
        cprint("            2) git remote add origin <URL> 已添加", "yellow")
        return

    # 4) commit 前检查身份
    _check_git_identity(blog_dir)

    # 5) git add（逐个路径，避免把不相关的脏文件带进去）
    cprint("→ git add", "cyan")
    run(["git", "add", *all_changes], cwd=blog_dir)

    # 6) git commit
    msg = _assemble_commit_msg(blog_dir, commit_msg)
    cprint(f"→ git commit -m {msg!r}", "cyan")
    res = run(["git", "commit", "-m", msg], cwd=blog_dir, check=False)
    if res.returncode != 0:
        # 比如 "nothing to commit (working directory clean)" —— 不是真错
        if "nothing to commit" in (res.stdout + res.stderr).lower():
            cprint("[info] 没有新变更，跳过 push。", "yellow")
            return
        err = (res.stderr or res.stdout).strip()
        die(f"git commit 失败:\n{err}")

    # 6) 推送分支：优先用户指定，否则取当前分支
    if branch is None:
        branch = run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=blog_dir, capture=True, check=False,
        ).stdout.strip() or "master"

    # 尝试 push
    cprint(f"→ git push -u {remote} {branch}", "cyan")
    try:
        subprocess.run(
            ["git", "push", "-u", remote, branch],
            cwd=str(blog_dir), shell=False, check=True,
        )
        cprint(f"[ok] 已推送到 {remote}/{branch}", "green")
    except subprocess.CalledProcessError:
        # push 失败时，给用户可复制的命令清单作为 fallback
        cprint("\n[warn] push 失败（可能是网络 / 权限问题）。", "yellow")
        cprint("       请手动在本地执行以下命令：", "yellow")
        cprint("\n  # 方案 A：直推当前分支", "cyan")
        cprint(f"  cd {blog_dir}")
        cprint(f'  git add {" ".join(all_changes)}')
        cprint(f'  git commit -m {msg!r}')
        cprint(f"  git push -u {remote} {branch}")
        cprint("\n  # 方案 B：先推到新分支再提 PR/PR（推荐协作场景）", "cyan")
        feature_branch = f"auto/update-{today_str()}"
        cprint(f"  git checkout -b {feature_branch}")
        cprint(f'  git commit -m {msg!r}')
        cprint(f"  git push -u {remote} {feature_branch}")
        raise SystemExit(2)


# ---------------------------------------------------------------------------
# 状态
# ---------------------------------------------------------------------------

def status(blog_dir: Path) -> None:
    cfg = read_json(blog_dir / CONFIG_NAME)
    cprint("=== 站点信息 ===", "bold")
    print(f"  名称:    {cfg['site']['name']}")
    print(f"  域名:    {cfg['site']['url']}")
    print(f"  描述:    {cfg['site']['description']}")
    print(f"  作者:    {cfg['site']['author']}")
    print(f"  栏目:    {len(cfg['categories'])} 个")
    for c in cfg["categories"]:
        print(f"     - {c['name']}  (slug: {c['slug']}) — {c['description']}")

    # 文章
    md_files = scan_index_md(blog_dir)
    cprint(f"\n=== 文章 ({len(md_files)} 篇) ===", "bold")
    for f in md_files:
        try:
            text = f.read_text(encoding="utf-8")
            fm, _ = parse_front_matter(text)
            cat = resolve_category(f, fm)
            print(f"  {fm.get('date','(无日期)')}  [{cat}]  {fm.get('title','?')}  ({fm.get('slug', f.parent.name)})")
        except Exception as e:
            print(f"  ⚠ {f}: {e}")

    # Git
    cprint("\n=== Git ===", "bold")
    if (blog_dir / ".git").exists():
        res = run(["git", "status", "--short"], cwd=blog_dir, capture=True, check=False)
        lines = res.stdout.strip().splitlines()
        print(f"  仓库: yes")
        print(f"  待处理变更: {len([l for l in lines if l])} 行")
        for l in lines[:10]:
            print(f"    {l}")
        if len(lines) > 10:
            print(f"    … 还有 {len(lines) - 10} 行")
    else:
        print("  仓库: no（尚未 git init）")


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="blogctl",
        description="静态博客运维工具：配置 / 文章 / 构建 / Git 推送",
    )
    p.add_argument("--dir", default=None, help="博客根目录（默认自动检测）")
    sub = p.add_subparsers(dest="cmd", required=True)

    # ---- config ----
    sp = sub.add_parser("config", help="站点配置读写")
    subsub = sp.add_subparsers(dest="config_cmd", required=True)
    subsub.add_parser("show", help="打印 site.config.json（美化）")
    sp_set = subsub.add_parser("set", help="设置一个配置项")
    sp_set.add_argument("key", help="如 site.url 或 site.name")
    sp_set.add_argument("value", help="支持 true/false/null/整数/小数/JSON 字符串")
    subsub.add_parser("open", help="用默认编辑器打开 site.config.json")

    # ---- post ----
    sp = sub.add_parser("post", help="文章管理")
    subsub = sp.add_subparsers(dest="post_cmd", required=True)
    sp_new = subsub.add_parser("new", help="新建文章（交互式）")
    sp_new.add_argument("--slug")
    sp_new.add_argument("--title")
    sp_new.add_argument("--category")
    sp_new.add_argument("--tags", help="逗号分隔，如 '随笔,建站'")
    sp_new.add_argument("--date")
    sp_new.add_argument("--summary")
    sp_new.add_argument("--no-open", action="store_true", help="创建后不自动打开编辑器")
    subsub.add_parser("list", help="列出所有文章（日期倒序）")
    sp_show = subsub.add_parser("show", help="查看某篇文章的 front matter 与摘要")
    sp_show.add_argument("slug")
    sp_edit = subsub.add_parser("edit", help="用默认编辑器打开某篇 .md")
    sp_edit.add_argument("slug")

    # ---- build ----
    sub.add_parser("build", help="调用 node build.js 重新生成站点")

    # ---- deploy ----
    sp = sub.add_parser("deploy", help="构建 → 提交 → 推送，一条龙")
    sp.add_argument("--msg", help="自定义 commit message（不传则自动生成）")
    sp.add_argument("--skip-build", action="store_true", help="跳过 build，直接推送（调试用）")
    sp.add_argument("--dry-run", action="store_true", help="只打印将要做的事，不执行 git 写操作")
    sp.add_argument("--remote", default="origin", help="远程仓库名，默认 origin")
    sp.add_argument("--branch", help="目标分支名，不传则取当前分支")

    # ---- status ----
    sub.add_parser("status", help="汇总站点 / 文章 / Git 状态")

    # ---- init ----
    sp = sub.add_parser("init", help="首次使用：检查目录结构与 Git 配置")
    sp.add_argument("--remote", help="远程仓库 URL（可选，传入则自动配置 origin）")
    sp.add_argument("--with-gitignore", action="store_true", help="生成一份推荐的 .gitignore")

    return p


GITIGNORE_TEMPLATE = """\
# Python
__pycache__/
*.pyc
*.pyo

# 编辑器
.vscode/
.idea/
*.swp
*.swo

# 系统
.DS_Store
Thumbs.db

# Node（本项目为零依赖，留空也可）
node_modules/

# 临时文件
*.log
*.tmp
"""


def cmd_init(blog_dir: Path, remote: Optional[str], with_gitignore: bool) -> None:
    cprint("=== blogctl 初始化 ===", "bold")
    cprint(f"博客目录: {blog_dir}", "cyan")

    # 1) 检查关键文件
    checks = [
        ("site.config.json", (blog_dir / CONFIG_NAME).exists()),
        ("build.js", (blog_dir / BUILDER).exists()),
        ("content/posts/", (blog_dir / POSTS_DIR).exists()),
    ]
    for name, ok in checks:
        mark = "✓" if ok else "✗"
        color = "green" if ok else "red"
        cprint(f"  {mark} {name}", color)
    if not all(ok for _, ok in checks):
        die("项目文件不完整，请确认这是正确的博客根目录")

    # 2) Git 仓库
    if (blog_dir / ".git").exists():
        cprint("  ✓ 已是 Git 仓库", "green")
    else:
        if _safe_input("  不是 Git 仓库，现在 git init ? (y/N): ").lower() == "y":
            run(["git", "init"], cwd=blog_dir)
            cprint("  ✓ git init 完成", "green")

    # 3) 配置 remote
    if remote:
        # 如果已经有 origin，先改；否则 add
        res = run(["git", "remote"], cwd=blog_dir, capture=True, check=False)
        if "origin" in res.stdout.splitlines():
            run(["git", "remote", "set-url", "origin", remote], cwd=blog_dir)
        else:
            run(["git", "remote", "add", "origin", remote], cwd=blog_dir)
        cprint(f"  ✓ origin = {remote}", "green")

    # 4) .gitignore
    gi = blog_dir / ".gitignore"
    if with_gitignore:
        if gi.exists():
            cprint("  [info] .gitignore 已存在，跳过（如想覆盖请先手动删除）", "yellow")
        else:
            gi.write_text(GITIGNORE_TEMPLATE, encoding="utf-8")
            cprint("  ✓ 已生成 .gitignore", "green")
    elif gi.exists():
        cprint("  ✓ 已存在 .gitignore", "green")

    cprint("\n[ok] 初始化完成，可以开始用了：", "green")
    print("  blogctl status          看当前状态")
    print("  blogctl post new        新建文章")
    print("  blogctl build           构建站点")
    print("  blogctl deploy --dry-run  预览本次将推送什么")


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()
    blog_dir = resolve_blog_dir(getattr(args, "dir", None))

    if args.cmd == "config":
        if args.config_cmd == "show":
            config_show(blog_dir)
        elif args.config_cmd == "set":
            config_set(blog_dir, args.key, args.value)
        elif args.config_cmd == "open":
            config_open(blog_dir)

    elif args.cmd == "post":
        if args.post_cmd == "new":
            tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None
            new_post(
                blog_dir,
                slug=args.slug, title=args.title,
                category=args.category, tags=tags,
                date=args.date, summary=args.summary,
                no_open=args.no_open,
            )
        elif args.post_cmd == "list":
            list_posts(blog_dir)
        elif args.post_cmd == "show":
            show_post(blog_dir, args.slug)
        elif args.post_cmd == "edit":
            edit_post(blog_dir, args.slug)

    elif args.cmd == "build":
        build_site(blog_dir)

    elif args.cmd == "deploy":
        deploy(
            blog_dir,
            commit_msg=args.msg,
            skip_build=args.skip_build,
            dry_run=args.dry_run,
            remote=args.remote,
            branch=args.branch,
        )

    elif args.cmd == "status":
        status(blog_dir)

    elif args.cmd == "init":
        cmd_init(blog_dir, args.remote, args.with_gitignore)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已中断。")
        sys.exit(130)
