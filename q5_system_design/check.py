# Q5 系统设计文档检查（run_all.py 调用入口）
# 该模块为「文档题」，无代码运行；此处仅校验交付物文件存在。
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "q5_system_design" / "real_time_pipeline_design.md"


def run() -> int:
    if not DOC.exists():
        raise FileNotFoundError(f"缺少交付物：{DOC}，请完成 Q5 文档。")
    # 简单校验篇幅（题目建议 800-1500 字）
    text = DOC.read_text(encoding="utf-8")
    if len(text) < 800:
        print(f"⚠️ {DOC.name} 篇幅偏短（{len(text)} 字符），建议扩充到 800+。")
    print(f"✅ Q5 文档存在，{len(text)} 字符。")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run())
