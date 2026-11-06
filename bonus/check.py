# 加分题文档检查（run_all.py 调用入口）
# 该模块为「文档题」，无代码运行；此处仅校验交付物文件存在。
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = [
    ROOT / "bonus" / "q6_1_ai_collaboration.md",
    ROOT / "bonus" / "q6_2_business_insights.md",
]


def run() -> int:
    for d in DOCS:
        if not d.exists():
            raise FileNotFoundError(f"缺少交付物：{d}，请完成加分题文档。")
        print(f"✅ {d.name} 存在（{len(d.read_text(encoding='utf-8'))} 字符）。")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run())
