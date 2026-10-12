"""scoring_anchor_ab 对照跑分工具的纯函数单测(#114)。

覆盖:锚点段落剥离能还原旧 prompt(对照基线的正确性)、分布汇总与门槛
跨越统计的数值正确性。LLM 与 DB 路径不在此测(运行期工具,由 #114 的
对照跑分本身验证)。
"""

from __future__ import annotations

import importlib.util
import os

from app.services.llm.prompts.analysis import ANALYSIS_PROMPT, ANALYSIS_PROMPT_EN
from app.services.scoring_caliber import dimension_anchor_section

_SCRIPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts",
    "scoring_anchor_ab.py",
)
_spec = importlib.util.spec_from_file_location("scoring_anchor_ab", _SCRIPT_PATH)
assert _spec and _spec.loader
ab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ab)


def test_strip_anchor_section_restores_pre_anchor_layout():
    rendered = ANALYSIS_PROMPT.format(title="T", content="C")
    section = dimension_anchor_section()
    old = ab.strip_anchor_section(rendered, section)

    assert "六维评分锚点" not in old
    assert section not in old
    assert "精选分（curation_score）评判标准：" in old
    # 剥掉的恰是「段落 + 一组相邻空行」(2 个换行符),布局回到挂锚点前的形态
    assert len(rendered) - len(old) == len(section) + 2
    # 幂等:对已剥离文本再剥应报错(段落已不存在)
    try:
        ab.strip_anchor_section(old, section)
        raise AssertionError("已剥离的 prompt 再剥离应报 ValueError")
    except ValueError:
        pass


def test_strip_anchor_section_en_prompt():
    rendered = ANALYSIS_PROMPT_EN.format(title="T", content="C")
    old = ab.strip_anchor_section(rendered, dimension_anchor_section("en"))
    assert "Six-dimension scoring anchors" not in old
    assert "Curation score (curation_score) guidelines:" in old


def test_summarize_dimensions_and_threshold_crossing():
    # 2 组配对:均值迁移 + 门槛跨越(阈值取 CONFIG,默认 55)
    threshold = ab.CONFIG["curation_threshold"]
    old_rows = [
        {"curation_score": 50.0, "quality_score": 40.0},
        {"curation_score": 60.0, "quality_score": 60.0},
    ]
    new_rows = [
        {"curation_score": 58.0, "quality_score": 55.0},
        {"curation_score": 52.0, "quality_score": 65.0},
    ]
    summary = ab.summarize_dimensions(old_rows, new_rows)

    q = summary["quality_score"]
    assert q["old"]["mean"] == 50.0
    assert q["new"]["mean"] == 60.0
    assert q["mean_shift"] == 10.0

    t = summary["_threshold"]
    assert t["threshold"] == float(threshold)
    assert t["old_selected"] == 1  # 60 过线
    assert t["new_selected"] == 1  # 58 过线
    assert t["crossed_up"] == 1  # 50 → 58
    assert t["crossed_down"] == 1  # 60 → 52


def test_summarize_dimensions_missing_dim_is_reported_not_raised():
    summary = ab.summarize_dimensions(
        [{"curation_score": None, "risk_score": 10.0}],
        [{"curation_score": 70.0, "risk_score": 30.0}],
    )
    assert summary["curation_score"]["old"]["n"] == 0
    assert summary["curation_score"]["new"]["n"] == 1
    assert "mean_shift" not in summary["curation_score"]
    assert summary["risk_score"]["mean_shift"] == 20.0
