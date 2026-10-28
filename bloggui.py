#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bloggui —— 博客站点图形化管理界面（Tkinter）
==============================================

底层复用 tools/blogctl.py 的所有业务逻辑，
仅做 GUI 壳层。零第三方依赖，Python 3.8+ 自带 Tkinter。

启动:  python3 bloggui.py
"""

from __future__ import annotations

import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

# 把 tools/ 加进 sys.path，直接 import 业务逻辑
import sys
_TOOLS = Path(__file__).resolve().parent / "tools"
sys.path.insert(0, str(_TOOLS))
import blogctl  # type: ignore

BLOG_DIR = blogctl.DEFAULT_BLOG_DIR


# ---------------------------------------------------------------------------
# 日志队列：子线程 → 主线程
# ---------------------------------------------------------------------------

class LogBridge:
    """收集所有子线程产生的日志，通过 queue 回传给 UI 主线程。"""
    def __init__(self) -> None:
        self.q: queue.Queue[str] = queue.Queue()

    def push(self, line: str) -> None:
        self.q.put(line)

    def push_error(self, line: str) -> None:
        self.q.put(f"[error] {line}")


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def _safe_resolve_blog_dir(root: tk.Misc) -> Path:
    try:
        return blogctl.resolve_blog_dir(None)
    except SystemExit as e:
        messagebox.showerror("初始化失败", str(e))
        root.destroy()
        raise


def _on_error(root: tk.Misc, exc: Exception) -> None:
    messagebox.showerror("操作失败", f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Tab 1: 站点配置
# ---------------------------------------------------------------------------

class ConfigTab(ttk.Frame):
    """左侧 JSON 原始树（只读 + 点击编辑）+ 右侧快速字段面板。"""

    def __init__(self, master, log: LogBridge) -> None:
        super().__init__(master)
        self.log = log
        self.cfg_path = BLOG_DIR / blogctl.CONFIG_NAME

        # 三列布局
        self.columnconfigure(0, weight=1, uniform="col")
        self.columnconfigure(1, weight=1, uniform="col")
        self.rowconfigure(1, weight=1)

        # 顶部工具栏
        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=(8, 4))
        ttk.Button(bar, text="刷新", command=self.reload).pack(side="left")
        ttk.Button(bar, text="保存修改", command=self.save_all).pack(side="left", padx=4)
        ttk.Button(bar, text="用编辑器打开", command=self.open_in_editor).pack(side="left")

        # 左：快速字段（最常用）
        self.quick = ttk.LabelFrame(self, text="快速字段（site.*）")
        self.quick.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)

        self._quick_entries: dict[str, ttk.Entry] = {}
        self._build_quick_form()

        # 右：JSON 原文（可直接手改）
        self.json_text = tk.Text(self, wrap="none", font=("Menlo", 12), undo=True)
        self.json_text.grid(row=1, column=1, sticky="nsew", padx=8, pady=4)

        # 底部提示
        ttk.Label(self, text="提示：左侧改完点「保存修改」；右侧也可以直接手改 JSON 再点「保存修改」。").grid(
            row=2, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8)
        )

        self.reload()

    # --- 快速表单 ---

    QUICK_FIELDS = [
        ("站点名称",   "site.name"),
        ("站点域名",   "site.url"),
        ("站点描述",   "site.description"),
        ("作者",       "site.author"),
        ("语言",       "site.language"),
        ("版权",       "site.copyright"),
    ]

    def _build_quick_form(self) -> None:
        for i, (label, key) in enumerate(self.QUICK_FIELDS):
            ttk.Label(self.quick, text=label + ":").grid(row=i, column=0, sticky="w", padx=8, pady=4)
            entry = ttk.Entry(self.quick)
            entry.grid(row=i, column=1, sticky="ew", padx=8, pady=4)
            self.quick.columnconfigure(1, weight=1)
            self._quick_entries[key] = entry

    def _get_quick_value(self, key: str) -> str:
        return self._quick_entries[key].get()

    # --- 加载 / 保存 ---

    def reload(self) -> None:
        try:
            cfg = blogctl.read_json(self.cfg_path)
        except Exception as e:
            messagebox.showerror("读取失败", str(e))
            return

        # 填快速字段
        for label, key in self.QUICK_FIELDS:
            keys = key.split(".")
            cur = cfg
            for k in keys:
                cur = cur.get(k, "")
            self._quick_entries[key].delete(0, "end")
            self._quick_entries[key].insert(0, str(cur))

        # 填 JSON 原文
        self.json_text.delete("1.0", "end")
        self.json_text.insert("1.0", json.dumps(cfg, ensure_ascii=False, indent=2))

        self.log.push(f"[config] 已加载 {self.cfg_path}")

    def save_all(self) -> None:
        # 1) 把右侧 JSON 原文先尝试 parse，作为主数据源
        raw = self.json_text.get("1.0", "end").strip()
        try:
            cfg = json.loads(raw)
        except json.JSONDecodeError as e:
            # 原文有错误 → 提示但用左侧快速字段的结果兜底？
            if not messagebox.askyesno(
                "JSON 格式错误",
                f"右侧 JSON 语法错误：{e}\n\n仍然按左侧快速字段的当前值保存吗？",
            ):
                return
            cfg = blogctl.read_json(self.cfg_path)

        # 2) 左侧快速字段覆盖（如果用户在左侧改了）
        changed_something = False
        for label, key in self.QUICK_FIELDS:
            keys = key.split(".")
            cur = cfg
            for k in keys[:-1]:
                cur = cur.setdefault(k, {})
            new_val = self._get_quick_value(key)
            old_val = cur.get(keys[-1], "")
            if str(old_val) != new_val:
                cur[keys[-1]] = new_val
                changed_something = True

        # 3) 写回
        try:
            blogctl.write_json(self.cfg_path, cfg)
        except Exception as e:
            messagebox.showerror("写入失败", str(e))
            return

        self.log.push(f"[config] ✓ 已保存 {self.cfg_path}{'（有字段变更）' if changed_something else ''}")

        # 刷新两侧
        self.json_text.delete("1.0", "end")
        self.json_text.insert("1.0", json.dumps(cfg, ensure_ascii=False, indent=2))

    def open_in_editor(self) -> None:
        try:
            blogctl.open_in_editor(self.cfg_path)
        except Exception as e:
            messagebox.showerror("打开失败", str(e))


# ---------------------------------------------------------------------------
# Tab 2: 文章管理
# ---------------------------------------------------------------------------

class PostsTab(ttk.Frame):
    """Treeview 列表 + 新建/编辑/删除/查看 操作。"""

    def __init__(self, master, log: LogBridge) -> None:
        super().__init__(master)
        self.log = log
        self.cfg_path = BLOG_DIR / blogctl.CONFIG_NAME
        self.posts_dir = BLOG_DIR / blogctl.POSTS_DIR

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # 顶部工具栏
        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        ttk.Button(bar, text="🔄 刷新", command=self.refresh).pack(side="left")
        ttk.Button(bar, text="➕ 新建文章", command=self.new_post_dialog).pack(side="left", padx=4)
        ttk.Button(bar, text="📝 编辑", command=self.edit_selected).pack(side="left")
        ttk.Button(bar, text="👁 预览 Front Matter", command=self.preview_selected).pack(side="left", padx=4)
        ttk.Button(bar, text="🗑 删除", command=self.delete_selected).pack(side="left")
        ttk.Button(bar, text="🔎 打开所在目录", command=self.open_posts_dir).pack(side="right")

        # 搜索框
        search_bar = ttk.Frame(self)
        search_bar.grid(row=0, column=0, sticky="e", padx=150, pady=(8, 4))
        ttk.Label(search_bar, text="搜索:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Entry(search_bar, textvariable=self.search_var, width=24).pack(side="left", padx=4)

        # Treeview
        cols = ("date", "category", "slug", "title", "tags")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="browse")
        headings = {
            "date":     ("日期",   100),
            "category": ("栏目",   100),
            "slug":     ("slug",   180),
            "title":    ("标题",   400),
            "tags":     ("标签",   180),
        }
        for c, (label, width) in headings.items():
            self.tree.heading(c, text=label)
            self.tree.column(c, width=width, anchor="w")
        self.tree.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)

        # 滚动条
        sb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        sb.grid(row=1, column=1, sticky="ns", pady=4)
        self.tree.configure(yscrollcommand=sb.set)

        # 双击 → 编辑
        self.tree.bind("<Double-1>", lambda _e: self.edit_selected())

        # 底部状态栏
        self.status_var = tk.StringVar(value="共 0 篇文章")
        ttk.Label(self, textvariable=self.status_var).grid(
            row=2, column=0, sticky="w", padx=8, pady=(0, 8)
        )

        self._all_rows: list[dict] = []

        self.refresh()

    # --- 刷新列表 ---

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._all_rows.clear()

        self.posts_dir.mkdir(parents=True, exist_ok=True)
        md_files = blogctl.scan_index_md(BLOG_DIR)

        for f in md_files:
            try:
                text = f.read_text(encoding="utf-8")
                fm, _body = blogctl.parse_front_matter(text)
            except Exception:
                continue
            tags = fm.get("tags", [])
            if isinstance(tags, list):
                tag_str = ", ".join(tags)
            else:
                tag_str = str(tags)
            row = {
                "file": f,
                "slug": fm.get("slug", f.parent.name),
                "title": fm.get("title", "(无标题)"),
                "date": fm.get("date", ""),
                "category": blogctl.resolve_category(f, fm),
                "tags": tag_str,
            }
            self._all_rows.append(row)

        self._all_rows.sort(key=lambda r: r["date"], reverse=True)
        for r in self._all_rows:
            self.tree.insert("", "end", values=(
                r["date"], r["category"], r["slug"], r["title"], r["tags"]
            ))

        self.status_var.set(f"共 {len(self._all_rows)} 篇文章")
        self._apply_filter()

    def _apply_filter(self) -> None:
        q = self.search_var.get().strip().lower()
        for item in self.tree.get_children():
            values = self.tree.item(item, "values")
            hay = " ".join(str(v).lower() for v in values)
            self.tree.detach(item)
            if not q or q in hay:
                self.tree.reattach(item, "", "end")

    # --- 选中行 ---

    def _get_selected_row(self) -> Optional[dict]:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在列表里选一篇文章")
            return None
        idx = self.tree.index(sel[0])
        visible = [r for r in self._all_rows]
        return visible[idx] if idx < len(visible) else None

    # --- 操作 ---

    def new_post_dialog(self) -> None:
        cfg = blogctl.read_json(self.cfg_path)
        cat_options = [f"{c['name']} ({c['slug']})" for c in cfg.get("categories", [])]

        dlg = NewPostDialog(self, cat_options)
        self.wait_window(dlg)
        if not dlg.result:
            return
        slug, title, category, tags, date, summary = dlg.result

        posts_dir = self.posts_dir
        article_dir = posts_dir / category / slug
        article_dir.mkdir(parents=True, exist_ok=True)
        target = article_dir / "index.md"
        if target.exists():
            messagebox.showerror("冲突", f"slug '{slug}' 已存在，换一个。")
            return

        # front matter 默认不写 category —— 构建脚本自动从栏目文件夹名识别
        front = {
            "title": title, "date": date,
            "tags": tags, "summary": summary, "slug": slug,
        }
        body = (
            blogctl.render_front_matter(front)
            + "\n## 正文\n\n开始写正文吧…\n\n"
            "> 图片/PDF 直接丢在本文章文件夹里，Markdown 写相对路径 `![](文件名)` 就行。\n"
        )
        target.write_text(body, encoding="utf-8")

        self.log.push(f"[post] ✓ 已创建 {target}")
        self.log.push(f"       栏目归属: {category} （自动识别自目录 content/posts/{category}/）")
        self.refresh()

        if messagebox.askyesno("创建成功", f"已创建 {target.name}，现在打开编辑器吗？"):
            blogctl.open_in_editor(target)

    def edit_selected(self) -> None:
        row = self._get_selected_row()
        if not row:
            return
        blogctl.open_in_editor(row["file"])
        self.log.push(f"[post] 打开 {row['file'].name}")

    def preview_selected(self) -> None:
        row = self._get_selected_row()
        if not row:
            return
        text = row["file"].read_text(encoding="utf-8")
        fm, body = blogctl.parse_front_matter(text)
        preview = "\n".join(f"  {k}: {v}" for k, v in fm.items())
        messagebox.showinfo(
            f"Front Matter — {row['title']}",
            f"文件: {row['file']}\n\n{preview}\n\n正文预览 (前 300 字):\n{body[:300]}",
        )

    def delete_selected(self) -> None:
        row = self._get_selected_row()
        if not row:
            return
        if not messagebox.askyesno(
            "确认删除",
            f"真的要删除这篇文章吗？\n\n  {row['title']}\n  {row['file']}\n\n此操作不可撤销。",
        ):
            return
        row["file"].unlink()
        self.log.push(f"[post] ✓ 已删除 {row['file'].name}")
        self.refresh()

    def open_posts_dir(self) -> None:
        try:
            blogctl.open_in_editor(self.posts_dir)
        except Exception:
            import subprocess, platform
            p = self.posts_dir
            sys_name = platform.system().lower()
            if sys_name == "darwin":
                subprocess.Popen(["open", str(p)])
            elif sys_name == "windows":
                os.startfile(str(p))  # noqa
            else:
                subprocess.Popen(["xdg-open", str(p)])


# ---------------------------------------------------------------------------
# 新建文章对话框（模态）
# ---------------------------------------------------------------------------

class NewPostDialog(tk.Toplevel):
    def __init__(self, master, cat_options: list[str]):
        super().__init__(master)
        self.title("新建文章")
        self.transient(master)
        self.grab_set()
        self.result = None

        self.columnconfigure(1, weight=1)

        r = 0
        ttk.Label(self, text="栏  目").grid(row=r, column=0, padx=8, pady=6, sticky="e")
        self.cat_var = tk.StringVar(value=cat_options[0] if cat_options else "")
        ttk.Combobox(self, textvariable=self.cat_var, values=cat_options, state="readonly").grid(
            row=r, column=1, padx=8, pady=6, sticky="we"
        ); r += 1

        ttk.Label(self, text="标  题").grid(row=r, column=0, padx=8, pady=6, sticky="e")
        self.title_entry = ttk.Entry(self); self.title_entry.grid(row=r, column=1, padx=8, pady=6, sticky="we"); r += 1

        ttk.Label(self, text="slug").grid(row=r, column=0, padx=8, pady=6, sticky="e")
        self.slug_entry = ttk.Entry(self); self.slug_entry.grid(row=r, column=1, padx=8, pady=6, sticky="we"); r += 1

        ttk.Label(self, text="日  期").grid(row=r, column=0, padx=8, pady=6, sticky="e")
        self.date_entry = ttk.Entry(self)
        self.date_entry.insert(0, blogctl.today_str())
        self.date_entry.grid(row=r, column=1, padx=8, pady=6, sticky="we"); r += 1

        ttk.Label(self, text="标  签").grid(row=r, column=0, padx=8, pady=6, sticky="e")
        self.tags_entry = ttk.Entry(self)
        self.tags_entry.grid(row=r, column=1, padx=8, pady=6, sticky="we"); r += 1

        ttk.Label(self, text="摘  要").grid(row=r, column=0, padx=8, pady=6, sticky="ne")
        self.summary_text = tk.Text(self, height=3)
        self.summary_text.grid(row=r, column=1, padx=8, pady=6, sticky="we"); r += 1

        # 按钮
        btns = ttk.Frame(self)
        btns.grid(row=r, column=0, columnspan=2, pady=10)
        ttk.Button(btns, text="确定", command=self._ok).pack(side="left", padx=6)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=6)

        # 自动填 slug 兜底（标题变化时）
        self.title_entry.bind(
            "<KeyRelease>",
            lambda _e: self.slug_entry.insert(0, blogctl.slugify(self.title_entry.get()))
                       if not self.slug_entry.get() else None,
        )

        # 默认选中标题输入
        self.title_entry.focus_set()

        self.geometry("480x420")
        self.wait_visibility()
        self.grab_set()

    def _ok(self) -> None:
        title = self.title_entry.get().strip()
        if not title:
            messagebox.showerror("缺少字段", "标题不能为空"); return
        slug = self.slug_entry.get().strip() or blogctl.slugify(title)
        date = self.date_entry.get().strip() or blogctl.today_str()

        # 栏目名 → slug
        cat_display = self.cat_var.get()
        cat_slug = cat_display.split("(")[-1].rstrip(")") if "(" in cat_display else cat_display

        tags = [t.strip() for t in self.tags_entry.get().split(",") if t.strip()]
        summary = self.summary_text.get("1.0", "end").strip()

        self.result = (slug, title, cat_slug, tags, date, summary)
        self.destroy()


# ---------------------------------------------------------------------------
# Tab 3: 构建 + 部署
# ---------------------------------------------------------------------------

class DeployTab(ttk.Frame):
    def __init__(self, master, log: LogBridge, log_widget):
        super().__init__(master)
        self.log = log
        self.log_widget = log_widget  # 直接把 LogTab 的 Text 传过来
        self.blog_dir = BLOG_DIR

        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        # Git 状态面板
        git_frame = ttk.LabelFrame(self, text="Git 状态")
        git_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        self.git_status_var = tk.StringVar(value="点击「刷新 Git 状态」查看")
        ttk.Label(git_frame, textvariable=self.git_status_var, wraplength=600).pack(padx=8, pady=6, anchor="w")
        ttk.Button(git_frame, text="🔄 刷新 Git 状态", command=self.refresh_git).pack(anchor="e", padx=8, pady=4)

        # 构建按钮
        build_frame = ttk.LabelFrame(self, text="构建")
        build_frame.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        ttk.Button(build_frame, text="▶ 运行 build.js", command=self.build_async).pack(padx=8, pady=8, anchor="w")
        ttk.Label(build_frame, text="会调用 Node.js 的 build.js，重新生成所有 HTML / sitemap / rss 等文件。",
                  foreground="#666").pack(padx=8, anchor="w")

        # 部署按钮
        deploy_frame = ttk.LabelFrame(self, text="部署到 Git")
        deploy_frame.grid(row=2, column=0, sticky="ew", padx=8, pady=4)

        row0 = ttk.Frame(deploy_frame); row0.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(row0, text="远程:").pack(side="left")
        self.remote_var = tk.StringVar(value="origin")
        ttk.Entry(row0, textvariable=self.remote_var, width=12).pack(side="left", padx=4)
        ttk.Label(row0, text="分支:").pack(side="left", padx=(16, 0))
        self.branch_var = tk.StringVar(value="master")
        ttk.Entry(row0, textvariable=self.branch_var, width=16).pack(side="left", padx=4)
        ttk.Label(row0, text="(留空则自动取当前 HEAD)", foreground="#666").pack(side="left")

        row1 = ttk.Frame(deploy_frame); row1.pack(fill="x", padx=8, pady=4)
        ttk.Label(row1, text="Commit Message:").pack(side="left")
        self.msg_var = tk.StringVar(value="")
        ttk.Entry(row1, textvariable=self.msg_var).pack(side="left", padx=4, fill="x", expand=True)
        ttk.Label(row1, text="(留空则自动生成)", foreground="#666").pack(side="left")

        row2 = ttk.Frame(deploy_frame); row2.pack(fill="x", padx=8, pady=4)
        ttk.Button(row2, text="👁 Dry-run（预览将提交什么）",
                   command=lambda: self.deploy_async(dry_run=True)).pack(side="left")
        ttk.Button(row2, text="🚀 真正推送 (add + commit + push)",
                   command=lambda: self.deploy_async(dry_run=False)).pack(side="left", padx=8)

        # 说明
        ttk.Label(
            self,
            text="注意：真正推送会执行 git add / commit / push。请确保已配置好 git user.name / user.email 和 remote origin。",
            foreground="#a33", wraplength=600,
        ).grid(row=3, column=0, sticky="nw", padx=8, pady=4)

    # --- 异步执行器（避免阻塞 GUI）---

    def _run_async(self, label: str, fn):
        self.log.push(f"[{label}] ▶ 开始…")
        t = threading.Thread(target=self._safe_thread_run, args=(label, fn), daemon=True)
        t.start()

    def _safe_thread_run(self, label: str, fn):
        try:
            fn()
            self.log.push(f"[{label}] ✓ 完成")
        except SystemExit as e:
            # blogctl.die() 内部会 sys.exit(1)，拦截下来转成友好提示
            self.log.push_error(str(e))
        except Exception as e:
            self.log.push_error(f"{type(e).__name__}: {e}")

    # --- 具体动作 ---

    def refresh_git(self) -> None:
        self._run_async("git-status", self._do_refresh_git)

    def _do_refresh_git(self):
        if not (self.blog_dir / ".git").exists():
            self.git_status_var.set("⚠ 不是 Git 仓库（请先 git init 或在 blogctl init 中初始化）")
            return
        res = blogctl.run(["git", "status", "--short"], cwd=self.blog_dir, capture=True, check=False)
        lines = res.stdout.strip().splitlines() or ["(working tree clean)"]
        display = "\n".join(lines[:20])
        if len(lines) > 20:
            display += f"\n… 还有 {len(lines) - 20} 行"
        self.git_status_var.set(display)
        self.log.push(f"[git-status] {len(lines)} 行变更")

    def build_async(self) -> None:
        self._run_async("build", lambda: blogctl.build_site(self.blog_dir))

    def deploy_async(self, *, dry_run: bool) -> None:
        self._run_async("deploy", lambda: blogctl.deploy(
            self.blog_dir,
            commit_msg=self.msg_var.get() or None,
            skip_build=False,
            dry_run=dry_run,
            remote=self.remote_var.get() or "origin",
            branch=self.branch_var.get() or None,
        ))


# ---------------------------------------------------------------------------
# Tab 4: 日志面板
# ---------------------------------------------------------------------------

class LogTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        bar = ttk.Frame(self); bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        ttk.Button(bar, text="清屏", command=self.clear).pack(side="left")
        ttk.Button(bar, text="保存到文件…", command=self.save_to_file).pack(side="left", padx=4)
        ttk.Label(bar, text="所有操作日志", foreground="#666").pack(side="right")

        self.text = tk.Text(self, height=18, state="disabled", wrap="word",
                            font=("Menlo", 11))
        self.text.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)

        sb = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        sb.grid(row=1, column=1, sticky="ns", pady=4)
        self.text.configure(yscrollcommand=sb.set)

        # 颜色标签
        self.text.tag_configure("error", foreground="#c00")
        self.text.tag_configure("ok", foreground="#07a668")
        self.text.tag_configure("info", foreground="#666")

    def append(self, line: str) -> None:
        self.text.configure(state="normal")
        tag = "ok" if "✓" in line else ("error" if "[error]" in line or "失败" in line else "")
        self.text.insert("end", line + "\n", tag)
        self.text.see("end")
        self.text.configure(state="disabled")

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def save_to_file(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".log",
            filetypes=[("日志文件", "*.log"), ("所有文件", "*.*")],
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.text.get("1.0", "end"))
        messagebox.showinfo("已保存", f"日志已写入 {path}")


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("博客站点管理")
        self.geometry("980x640")
        self.minsize(820, 560)

        # 日志桥
        self.log_bridge = LogBridge()

        # 顶部菜单
        menu_bar = tk.Menu(self)
        file_menu = tk.Menu(menu_bar, tearoff=0)
        file_menu.add_command(label="重新加载所有数据", command=self.reload_all)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.destroy)
        menu_bar.add_cascade(label="文件", menu=file_menu)

        help_menu = tk.Menu(menu_bar, tearoff=0)
        help_menu.add_command(label="关于", command=self._about)
        menu_bar.add_cascade(label="帮助", menu=help_menu)
        self.config(menu=menu_bar)

        # Notebook
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=4, pady=4)

        # 先建 LogTab（DeployTab 会引用它的 widget）
        self.log_tab = LogTab(nb)
        self.config_tab = ConfigTab(nb, self.log_bridge)
        self.posts_tab = PostsTab(nb, self.log_bridge)
        self.deploy_tab = DeployTab(nb, self.log_bridge, self.log_tab.text)

        nb.add(self.config_tab, text="① 站点配置")
        nb.add(self.posts_tab, text="② 文章管理")
        nb.add(self.deploy_tab, text="③ 构建 / 部署")
        nb.add(self.log_tab, text="④ 日志")

        # 状态栏
        self.status_var = tk.StringVar(value=f"站点目录: {BLOG_DIR}  |  就绪")
        ttk.Label(self, textvariable=self.status_var, anchor="w").pack(fill="x", padx=8, pady=(0, 4))

        # 启动日志
        self.log_bridge.push(f"[boot] 博客目录 = {BLOG_DIR}")
        self.log_bridge.push("[boot] Python Tkinter GUI 已启动")

        # 主线程轮询日志队列（100ms）
        self._poll_queue()
        self.after(100, self._poll_queue)

    # --- 日志队列 ---

    def _poll_queue(self) -> None:
        # 主线程周期性地取 queue → Text
        while True:
            try:
                line = self.log_bridge.q.get_nowait()
            except queue.Empty:
                break
            self.log_tab.append(line)
        self.after(100, self._poll_queue)

    # --- 顶部菜单回调 ---

    def reload_all(self) -> None:
        self.config_tab.reload()
        self.posts_tab.refresh()
        self.deploy_tab.refresh_git()
        self.log_bridge.push("[reload] 所有面板已刷新")

    def _about(self) -> None:
        messagebox.showinfo(
            "关于",
            "博客站点管理 GUI\n\n"
            "底层复用 tools/blogctl.py 的业务逻辑，\n"
            "零第三方依赖，仅用 Python 内置 Tkinter。\n\n"
            f"站点目录: {BLOG_DIR}",
        )


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = App()
    app.mainloop()
