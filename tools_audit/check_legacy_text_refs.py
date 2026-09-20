# -*- coding: utf-8 -*-
"""扫 tools/ 与 _audit/ 下所有脚本，找出仍然把**已移动/已删除**的源文件当文本读的地方。

兼容转发层只救得了 ``import``，救不了 ``Path(...).read_text()``。
这里只**报告**，不修改；确认真坏了我再逐个修。
"""
import pathlib
import re

#: 重构后就不再存在的旧路径
GONE = [
    "machining_dfm.py", "machining_library.py", "machining_assets.py",
    "machining_machines.py", "machining_tools.py", "machining_fixtures.py",
    "machining_gauges.py", "machining_process.py", "machining_issue.py",
    "machining_selection.py", "machining_history.py", "machining_changes.py",
    "machining_seed.py", "machining_projection.py", "machining_project.py",
    "native_forms.py", "integration_contract.py", "html_literals.py", "settings.py",
]
#: 名字还在但内容全变了（已变成兼容转发层），当文本读就等于读错文件
SHIMMED = {"machining_dfm.py"}

READ_HINT = re.compile(r"read_text|open\(|read\(\)|Path\(|/\s*['\"]app['\"]|rglob|glob")

problems: list[tuple[str, int, str, str]] = []
for folder in ("tools", "_audit"):
    root = pathlib.Path(folder)
    if not root.is_dir():
        continue
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(source.splitlines(), 1):
            if ".sqlite3" in line:
                continue
            for name in GONE:
                if name not in line:
                    continue
                if name in SHIMMED and not READ_HINT.search(line):
                    continue          # import 兼容层 → 没问题
                if name in SHIMMED and f'"{name}"' not in line and f"'{name}'" not in line:
                    continue
                if READ_HINT.search(line):
                    problems.append((str(path), lineno, name, line.strip()[:110]))

if problems:
    print("× 这些地方把已移动/已删除的源文件当文本读，需要人工跟进：")
    for name, lineno, target, line in problems:
        print(f"  {name}:{lineno}  → {target}")
        print(f"      {line}")
else:
    print("√ tools/ 与 _audit/ 下没有把旧源文件当文本读的地方")
