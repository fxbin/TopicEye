#!/usr/bin/env python3
"""前后端评分口径一致性检查（#112）：前端镜像数字与 CONFIG 的漂移门禁。

`frontend/src/lib/recommendation.ts` 硬编码了两个镜像后端 CONFIG 的展示门槛：

- `RISK_HARD_EXCLUDE` ↔ `CONFIG["risk_threshold"]`（硬排除线）
- `QUALITY_GATE_MIN` ↔ `CONFIG["quality_gate_min"]`（过薄下限）

#110 的教训是「同口径数字的第二份手写副本会静默漂移」；#111 给后端 Python 侧
建了正则防线（tests/test_scoring_caliber.py），本脚本是同一防线的跨树延伸：
CONFIG 调整而前端忘了跟，CI 即红。

`RISK_HIGH` 是前端自创的展示档位（后端无对应数字，软起点 45 / 硬排除 82 之间
的展示分档），**不参与对比**——但必须带着「前端自有」标记注释存在：标记被删
说明有人动了这个数字却没意识到它是豁免项，同样红。

方案取舍见 #112：接口下发被否决（为一年一变的常量引入 fetch/加载态/失败面
不成比例），注释豁免单独不足（漂移只有门禁拦得住）。

用法：
    python scripts/check_scoring_mirror.py   # 在 backend/ 下运行

不一致时打印 前端值 vs CONFIG 值 并以退出码 1 结束，供 CI 阻断。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
FRONTEND_TS = REPO_ROOT / "frontend" / "src" / "lib" / "recommendation.ts"

# 前端常量名 → CONFIG 键（参与一致性对比的镜像对）。
MIRROR_PAIRS: dict[str, str] = {
    "RISK_HARD_EXCLUDE": "risk_threshold",
    "QUALITY_GATE_MIN": "quality_gate_min",
}

# 豁免档位：不对比，但行内必须带这个标记（防止无声地改掉豁免语义）。
EXEMPT_CONSTANTS: dict[str, str] = {"RISK_HIGH": "前端自有"}

_CONST_RE = r"^\s*const\s+{name}\s*=\s*(\d+)\s*;"


def extract_const(source: str, name: str) -> tuple[int, int] | None:
    """返回 (值, 行号)；找不到返回 None。"""
    for lineno, line in enumerate(source.splitlines(), start=1):
        m = re.match(_CONST_RE.format(name=name), line)
        if m:
            return int(m.group(1)), lineno
    return None


def run_check(ts_path: Path, config: dict) -> list[str]:
    """返回违规描述列表（空列表表示一致）。config 传入以便测试注入。"""
    source = ts_path.read_text(encoding="utf-8")
    violations: list[str] = []

    for const_name, config_key in MIRROR_PAIRS.items():
        found = extract_const(source, const_name)
        if found is None:
            violations.append(f"{ts_path}: 找不到 `{const_name}` 常量声明（改名请同步本脚本）")
            continue
        value, lineno = found
        expected = config[config_key]
        if value != expected:
            violations.append(
                f"{ts_path}:{lineno}: `{const_name} = {value}` 与 CONFIG['{config_key}'] = {expected} "
                f"漂移——调口径时前端镜像必须同步（或反向：后端改了口径，前端解释文案已失真）"
            )

    for const_name, marker in EXEMPT_CONSTANTS.items():
        found = extract_const(source, const_name)
        if found is None:
            continue  # 常量被删除（功能移除）不算漂移
        _, lineno = found
        line = source.splitlines()[lineno - 1]
        if marker not in line:
            violations.append(
                f"{ts_path}:{lineno}: `{const_name}` 行内缺少「{marker}」标记——"
                f"它是豁免对比的前端展示档位，改它或去标记都必须是有意识的决定"
            )

    return violations


def main() -> int:
    sys.path.insert(0, str(BACKEND_ROOT))
    from app.core.scoring_caliber import CONFIG  # noqa: E402 — sys.path 就绪后才能 import

    violations = run_check(FRONTEND_TS, CONFIG)
    if violations:
        print("评分口径前后端不一致（详见 scripts/check_scoring_mirror.py 与 #112）：", file=sys.stderr)
        for line in violations:
            print(f"  {line}", file=sys.stderr)
        return 1

    mirrors = "、".join(f"{c}={CONFIG[k]}" for c, k in MIRROR_PAIRS.items())
    print(f"口径一致性通过：前端镜像 {mirrors} 与 CONFIG 一致；豁免档位标记在位。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
