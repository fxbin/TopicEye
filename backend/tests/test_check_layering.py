"""check_layering.py 的回归测试：repositories→services 禁令自身的正确性机器化。

#113 落地的门禁。它一旦误报，agent 会学会忽略检查结果；它一旦漏报
（比如只查模块级 import、漏掉函数体内的局部 import——#113 的违例全部藏在
函数体里），逆向依赖就回到静默存续。两者都比没有这道门禁更糟，用测试钉住。

用例分三组：
- **应杀**：合成违例文件（模块级 / 函数内局部 / `import app.services.x` 三形态）
  必须被抓到。
- **豁免**：allowlist 内的前缀放行、前缀外的仍杀（棘轮语义——豁免是
  模块粒度不是文件粒度，analysis_repo 若新增第三个 services 依赖照样红）。
- **契约**：对真实仓库默认调用退出码为 0（CI 依赖命令行 + 退出码契约）。

本文件是纯 stdlib + subprocess，不碰数据库（外层 conftest 的 DB fixture 与它无关）。
背景：#113（范围 2→5 处的取证）、#122（allowlist 清空的重构单）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND_ROOT / "scripts" / "check_layering.py"


def run_script(*args: str) -> tuple[int, str]:
    """跑命令行契约（退出码 + 输出），cwd 固定 backend/ 让相对目录生效。"""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(BACKEND_ROOT),
    )
    return proc.returncode, proc.stdout + proc.stderr


def load_cl():
    """按路径加载 scripts/check_layering.py（scripts 不是包）。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_layering_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cl():
    return load_cl()


def repo_violations(tmp_path: Path, source: str, cl) -> list[str]:
    """写入临时文件跑 check_repo_services_imports。"""
    target = tmp_path / "some_repo.py"
    target.write_text(source, encoding="utf-8")
    return cl.check_repo_services_imports(target)


# ── 应杀 ──


def test_module_level_from_services_is_caught(cl, tmp_path: Path) -> None:
    src = "from app.services.scoring_engine import score_items\n"
    assert repo_violations(tmp_path, src, cl)


def test_function_local_from_services_is_caught(cl, tmp_path: Path) -> None:
    """#113 的违例形态：藏在函数体内的局部 import。"""
    src = (
        "def f():\n"
        "    from app.services.scoring_engine import CONFIG as SCORING_CONFIG\n"
        "    return SCORING_CONFIG\n"
    )
    assert repo_violations(tmp_path, src, cl)


def test_plain_import_services_is_caught(cl, tmp_path: Path) -> None:
    src = "import app.services.feedback_signal\n"
    assert repo_violations(tmp_path, src, cl)


def test_non_services_import_is_fine(cl, tmp_path: Path) -> None:
    """core/models/repositories 内部依赖不受影响。"""
    src = (
        "from app.core.scoring_caliber import CONFIG\n"
        "from app.core.tag_normalization import normalize_tag_key\n"
        "from app.repositories.base import BaseRepository\n"
    )
    assert repo_violations(tmp_path, src, cl) == []


# ── 豁免（棘轮语义）──


def test_allowlisted_module_passes_and_prefix_escape_is_caught(cl, tmp_path: Path) -> None:
    """豁免按 文件名+模块前缀 生效：allowlist 外的 services 依赖仍然杀。"""
    allowed = "from app.services.scoring_engine import score_items\n"
    escaped = "from app.services.duckdb_service import run_query\n"
    # 同名文件才走 analysis_repo 的豁免
    target = tmp_path / "analysis_repo.py"
    target.write_text(allowed + escaped, encoding="utf-8")
    violations = cl.check_repo_services_imports(target)
    assert len(violations) == 1
    assert "duckdb_service" in violations[0]


# ── 契约 ──


def test_real_repo_default_invocation_passes() -> None:
    """真实仓库默认调用（api/v1 + repositories）必须退出码 0。"""
    code, out = run_script()
    assert code == 0, f"真实仓库分层检查未通过：\n{out}"


def test_allowlist_only_shrinks() -> None:
    """allowlist 只减不增：当前仅剩 analysis_repo 一条（#122 清空）。"""
    cl = load_cl()
    assert set(cl.REPO_SERVICES_IMPORT_ALLOWLIST) == {"analysis_repo.py"}
