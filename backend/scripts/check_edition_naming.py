"""刊物种属词族前后端对账（#132，模式抄 check_scoring_mirror.py）。

frontend/src/lib/edition-naming.ts 与 backend/app/core/edition_naming.py
必须逐值一致——命名圆桌（2026-10-20）定的「情报正族」是全站唯一口径，
两边任何一边改词都会造成口径分裂（前科：AI 日报/AI 周刊/全行业信息日报
三种叫法并存）。CI 作业 edition-naming 跑本脚本，不一致即红。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_LIB = BACKEND_ROOT.parent / "frontend" / "src" / "lib" / "edition-naming.ts"
BACKEND_MODULE = BACKEND_ROOT / "app" / "core" / "edition_naming.py"

KEYS = ("daily", "weekly", "monthly", "special")


def parse_frontend() -> dict[str, str]:
    source = FRONTEND_LIB.read_text(encoding="utf-8")
    result: dict[str, str] = {}
    for key in KEYS:
        match = re.search(rf"^\s*{key}:\s*'([^']+)'", source, re.MULTILINE)
        if not match:
            raise SystemExit(f"FAIL 前端 edition-naming.ts 缺少 {key} 条目")
        result[key] = match.group(1)
    return result


def parse_backend() -> dict[str, str]:
    source = BACKEND_MODULE.read_text(encoding="utf-8")
    result: dict[str, str] = {}
    for key in KEYS:
        match = re.search(rf'^\s*"{key}":\s*"([^"]+)"', source, re.MULTILINE)
        if not match:
            raise SystemExit(f"FAIL 后端 edition_naming.py 缺少 {key} 条目")
        result[key] = match.group(1)
    return result


def main() -> int:
    if not FRONTEND_LIB.exists():
        raise SystemExit(f"FAIL 找不到前端镜像 {FRONTEND_LIB}")
    if not BACKEND_MODULE.exists():
        raise SystemExit(f"FAIL 找不到后端镜像 {BACKEND_MODULE}")

    frontend = parse_frontend()
    backend = parse_backend()

    mismatches = [
        f"{key}: 前端「{frontend[key]}」 vs 后端「{backend[key]}」" for key in KEYS if frontend[key] != backend[key]
    ]
    if mismatches:
        print("FAIL 刊物种属词族前后端不一致（改词必须两边同步改）：")
        for line in mismatches:
            print(f"  {line}")
        return 1

    print("edition naming mirror OK:", ", ".join(f"{key}={frontend[key]}" for key in KEYS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
