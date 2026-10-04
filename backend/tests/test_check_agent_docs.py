"""check_agent_docs.py 的回归测试：它自己的正确性也得机器化。

这个脚本是 CI 作业 `agent-docs` 的全部内容。它一旦误报，agent 就会学会忽略检查结果；
它一旦漏报，AGENTS.md 的路径就会无声腐烂。两者都比没有这道门禁更糟，所以用测试钉住。

用例分两组：
- **应杀**：注入坏引用必须让脚本退出码为 1。
- **已知盲区**：CI 作业名、分支名同形，无法无歧义判定，明确**杀不掉**。
  这些用例的作用是锁住这个决定——防止有人把不可靠的 `check_ci_jobs` 加回来。
  背景见 `.agents/notes/rejected/2026-10-04-agent-docs-ci-job-name-check.md`。

本文件是纯 stdlib + subprocess，不碰数据库（外层 conftest 的 DB fixture 与它无关）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
SCRIPT = BACKEND_ROOT / "scripts" / "check_agent_docs.py"
REAL_DOC = REPO_ROOT / "AGENTS.md"


def run_checker(doc_text: str, tmp_path: Path) -> tuple[int, str]:
    """把 doc_text 写成临时 md 交给脚本跑，返回 (退出码, 输出)。

    走 subprocess 而不是直接 import：CI 依赖的是命令行 + 退出码这个契约，
    直接 import 测不到它。

    临时文件放 pytest 的 tmp_path，不放仓库内——进程被硬杀时不会在
    backend/ 留下可能被 pytest 收集或误暂存的残留。
    """
    tmp = tmp_path / "AGENTS.md"
    tmp.write_text(doc_text, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp)],
        capture_output=True,
        text=True,
        cwd=str(BACKEND_ROOT),
    )
    return proc.returncode, proc.stdout


@pytest.fixture(scope="module")
def real_agents_md() -> str:
    return REAL_DOC.read_text(encoding="utf-8")


# ── 基线 ──


def test_real_agents_md_passes(real_agents_md: str, tmp_path: Path) -> None:
    """真实 AGENTS.md 必须干净通过，否则下面所有变异用例都无意义。"""
    code, out = run_checker(real_agents_md, tmp_path)
    assert code == 0, f"真实 AGENTS.md 未通过校验：\n{out}"


# ── 应杀 ──


def test_nonexistent_repo_path_is_caught(real_agents_md: str, tmp_path: Path) -> None:
    code, out = run_checker(real_agents_md + "\n见 `backend/tests/conftest_typo.py`。\n", tmp_path)
    assert code == 1
    assert "conftest_typo.py" in out


def test_nonexistent_backend_shorthand_path_is_caught(real_agents_md: str, tmp_path: Path) -> None:
    """AGENTS.md 里 `app/...` 是相对 backend/ 的简写，这形态也得能杀掉。"""
    code, out = run_checker(real_agents_md + "\n见 `app/repositories/content_repo_typo.py`。\n", tmp_path)
    assert code == 1
    assert "content_repo_typo.py" in out


def test_nonexistent_make_target_is_caught(real_agents_md: str, tmp_path: Path) -> None:
    code, out = run_checker(real_agents_md + "\n验证命令是 `make layeringg`。\n", tmp_path)
    assert code == 1
    assert "layeringg" in out


# ── 已知盲区：必须杀不掉 ──


def test_ci_job_name_is_not_checked(real_agents_md: str, tmp_path: Path) -> None:
    """CI 作业名不在检查范围内。

    `security-scanx` 是个不存在的作业名，脚本**不该**报错。
    若哪天这条断言失败，说明有人把不可靠的作业名检查加回来了，见 rejected 笔记。
    """
    code, _ = run_checker(real_agents_md + "\n对应 CI 作业 `security-scanx`。\n", tmp_path)
    assert code == 0, "CI 作业名检查被加回来了，它误报与漏报并存，见 rejected 笔记"


def test_branch_name_is_not_checked(real_agents_md: str, tmp_path: Path) -> None:
    """分支命名示例含连字符，与作业名同形，同样不该报错。"""
    code, _ = run_checker(real_agents_md + "\n分支命名如 `issue-4-cryptography-50`。\n", tmp_path)
    assert code == 0


def test_script_no_longer_carries_ci_job_checker() -> None:
    """`check_ci_jobs` / `is_dependency_chain_context` / `CI_WORKFLOW` 必须保持删除。"""
    source = SCRIPT.read_text(encoding="utf-8")
    for gone in ("def check_ci_jobs", "def is_dependency_chain_context", "CI_WORKFLOW"):
        assert gone not in source, f"{gone} 不该存在于 check_agent_docs.py"
