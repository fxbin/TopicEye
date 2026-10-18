"""check_scoring_mirror.py 的回归测试：口径门禁自身的正确性机器化。

#112 落地的门禁（CI 作业 scoring-mirror）。它一旦误报，agent 会学会忽略
检查结果；它一旦漏报，前端镜像数字回到静默漂移——#110 的学费就白交了。

用例分三组：
- **应杀**：镜像数字漂移（82→84）、豁免标记被删，都必须红。
- **放行**：豁免档位带标记改值不红（它是前端自有，改值是合法决定）；
  常量整体移除不算漂移。
- **契约**：对真实仓库命令行调用退出码 0（CI 依赖命令行 + 退出码契约）。

本文件纯 stdlib + subprocess，不碰数据库（外层 conftest 的 DB fixture 与它无关）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND_ROOT / "scripts" / "check_scoring_mirror.py"

REAL_TS = BACKEND_ROOT.parent / "frontend" / "src" / "lib" / "recommendation.ts"

BASE_CONFIG = {"risk_threshold": 82, "quality_gate_min": 45}

BASE_SOURCE = """const RISK_HARD_EXCLUDE = 82; // = CONFIG.risk_threshold（镜像，CI 对比锁死）
const RISK_HIGH = 75; // 前端自有展示档位：后端无对应数字，不参与口径对比
const QUALITY_GATE_MIN = 45; // = CONFIG.quality_gate_min（镜像，CI 对比锁死）
"""


def load_mod():
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_scoring_mirror_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return load_mod()


def write_ts(tmp_path: Path, source: str) -> Path:
    p = tmp_path / "recommendation.ts"
    p.write_text(source, encoding="utf-8")
    return p


# ── 应杀 ──


def test_mirror_drift_is_caught(mod, tmp_path: Path) -> None:
    """后端调到 84 而前端还是 82 → 红（或反向手改前端）。"""
    src = BASE_SOURCE.replace("RISK_HARD_EXCLUDE = 82", "RISK_HARD_EXCLUDE = 84")
    violations = mod.run_check(write_ts(tmp_path, src), BASE_CONFIG)
    assert len(violations) == 1
    assert "RISK_HARD_EXCLUDE" in violations[0]


def test_exempt_marker_removed_is_caught(mod, tmp_path: Path) -> None:
    """RISK_HIGH 行的「前端自有」标记被删 → 红（防止无意识动豁免语义）。"""
    src = BASE_SOURCE.replace("// 前端自有展示档位：后端无对应数字，不参与口径对比", "")
    violations = mod.run_check(write_ts(tmp_path, src), BASE_CONFIG)
    assert any("RISK_HIGH" in v for v in violations)


def test_missing_const_is_caught(mod, tmp_path: Path) -> None:
    src = "const QUALITY_GATE_MIN = 45; // = CONFIG.quality_gate_min（镜像，CI 对比锁死）\n"
    violations = mod.run_check(write_ts(tmp_path, src), BASE_CONFIG)
    assert any("RISK_HARD_EXCLUDE" in v for v in violations)


# ── 放行 ──


def test_exempt_value_change_with_marker_passes(mod, tmp_path: Path) -> None:
    """豁免档位带标记改值：前端自有，合法决定，不红。"""
    src = BASE_SOURCE.replace("RISK_HIGH = 75", "RISK_HIGH = 78")
    assert mod.run_check(write_ts(tmp_path, src), BASE_CONFIG) == []


def test_base_source_passes(mod, tmp_path: Path) -> None:
    assert mod.run_check(write_ts(tmp_path, BASE_SOURCE), BASE_CONFIG) == []


# ── 契约 ──


def test_real_repo_invocation_passes() -> None:
    """真实仓库命令行调用必须退出码 0（真实 CONFIG × 真实 recommendation.ts）。"""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(BACKEND_ROOT),
    )
    assert proc.returncode == 0, f"真实仓库口径一致性未通过：\n{proc.stdout}{proc.stderr}"


def test_real_ts_exists_and_matches_shape(mod) -> None:
    """真实 recommendation.ts 三个常量都在（防重构后测试对象悄悄消失）。"""
    source = REAL_TS.read_text(encoding="utf-8")
    for name in ("RISK_HARD_EXCLUDE", "RISK_HIGH", "QUALITY_GATE_MIN"):
        assert mod.extract_const(source, name) is not None, f"{name} 不在真实前端文件里"
