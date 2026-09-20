# -*- coding: utf-8 -*-
"""画出各层之间的真实 import 关系（写架构守卫测试前先看清楚现状）。"""
import ast
import pathlib
from collections import defaultdict

LAYERS = ("core", "db", "domains", "services", "api")


def module_name(path: pathlib.Path) -> str:
    rel = path.relative_to("app").with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def layer_of(name: str) -> str:
    head = name.split(".")[0]
    return head if head in LAYERS else "?"


edges = defaultdict(set)
for path in sorted(pathlib.Path("app").rglob("*.py")):
    if "__pycache__" in path.parts:
        continue
    src_name = module_name(path)
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.ImportFrom):
            if node.level:  # 相对导入：按当前包解析
                base = src_name.split(".")[:-1]
                up = node.level - 1
                base = base[: len(base) - up] if up else base
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            targets.append(target)
        elif isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
        for target in targets:
            if not target:
                continue
            parts = target.split(".")
            if parts[0] == "app":          # 绝对导入 app.xxx
                rest = parts[1:]
            elif parts[0] in LAYERS:       # 已经是层内相对目标（core.utils 等）
                rest = parts
            else:
                continue                   # 第三方 / 标准库
            if not rest:
                edges[src_name].add("app")
                continue
            tgt_layer = layer_of(".".join(rest))
            if tgt_layer == "?":
                edges[src_name].add("app." + ".".join(rest))
                continue
            tgt_mod = ".".join(rest[:2]) if len(rest) > 1 else tgt_layer
            same_layer = layer_of(src_name) == tgt_layer
            edges[src_name].add(("~" if same_layer else "") + "app." + tgt_mod)

print("== 跨层依赖（~ 前缀表示同层内） ==")
for src in sorted(edges):
    cross = sorted(t for t in edges[src] if not t.startswith("~"))
    same = sorted(t for t in edges[src] if t.startswith("~"))
    print(f"\n{src}  [{layer_of(src)}]")
    if cross:
        print("   跨层 ->", ", ".join(cross))
    if same:
        print("   同层 ->", ", ".join(t[1:] for t in same))
