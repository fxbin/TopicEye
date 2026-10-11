"""评分口径单一真相源回归测试(#110)。

历史缺陷:同一套精选评分口径分散在 prompt 教学 / 引擎 CONFIG / picks SQL
三处各写一份且互相矛盾(prompt 教五项 30/25/20/15/10 + 门槛 60,引擎六维
0.25/0.20/0.18/0.15/0.12/0.10 + 门槛 55,picks 硬编码 55/8 不读 CONFIG)。

本文件是「漂移即红」防线:从三套 prompt 成品文本里正则提取权重/门槛/扣分
数字,与 scoring_caliber.CONFIG 断言一致——绕过 caliber 模块手改 prompt
数字、或让引擎/picks 另起一份口径,这里立刻变红。
"""

from __future__ import annotations

import inspect
import re

from app.services import scoring_engine
from app.services.llm.prompts import analysis as analysis_prompts
from app.services.scoring_caliber import (
    CONFIG,
    LLM_RISK_PENALTY_POINTS,
    LLM_RISK_PENALTY_TRIGGER,
)

SIX_DIM_KEYS = (
    "w_info_density",
    "w_actionability",
    "w_creator_value",
    "w_viral_potential",
    "w_source_authority",
    "w_freshness",
)


def _expected_weights() -> list[int]:
    return [int(round(CONFIG[k] * 100)) for k in SIX_DIM_KEYS]


def _zh_weights(prompt: str) -> list[int]:
    seg = re.search(r"加权：(.*?)）", prompt)
    assert seg, "prompt 中找不到「加权：…」口径段"
    return [int(x) for x in re.findall(r"(\d+)%", seg.group(1))]


def _en_weights(prompt: str) -> list[int]:
    seg = re.search(r"weighted: (.*?), risk", prompt)
    assert seg, "prompt 中找不到 'weighted: …' 口径段"
    return [int(x) for x in re.findall(r"(\d+)%", seg.group(1))]


# ── CONFIG 自身完整性 ────────────────────────────────────────────────


def test_six_dim_weights_sum_to_one():
    assert abs(sum(CONFIG[k] for k in SIX_DIM_KEYS) - 1.0) < 1e-9


def test_engine_config_is_caliber_reexport():
    """引擎 CONFIG 必须就是 caliber 声明的同一对象,不允许复制成第二份。"""
    assert scoring_engine.CONFIG is CONFIG


# ── 三套 prompt 教学 vs CONFIG ───────────────────────────────────────


def test_zh_prompt_curation_weights_match_config():
    assert _zh_weights(analysis_prompts.ANALYSIS_PROMPT) == _expected_weights()


def test_en_prompt_curation_weights_match_config():
    assert _en_weights(analysis_prompts.ANALYSIS_PROMPT_EN) == _expected_weights()


def test_paper_prompt_curation_weights_match_config():
    assert _zh_weights(analysis_prompts.PAPER_ANALYSIS_PROMPT) == _expected_weights()


def test_prompts_curation_threshold_match_config():
    expected = CONFIG["curation_threshold"]
    zh = re.search(r"精选门槛为 (\d+) 分", analysis_prompts.ANALYSIS_PROMPT)
    paper = re.search(r"精选门槛为 (\d+) 分", analysis_prompts.PAPER_ANALYSIS_PROMPT)
    en = re.search(r"Curation threshold is (\d+) points", analysis_prompts.ANALYSIS_PROMPT_EN)
    assert zh and paper and en, "prompt 中找不到门槛句"
    assert int(zh.group(1)) == expected
    assert int(paper.group(1)) == expected
    assert int(en.group(1)) == expected


def test_prompts_risk_penalty_match_caliber():
    for prompt in (
        analysis_prompts.ANALYSIS_PROMPT,
        analysis_prompts.PAPER_ANALYSIS_PROMPT,
    ):
        m = re.search(r"风险分>(\d+)则扣(\d+)分", prompt)
        assert m, "中文 prompt 中找不到风险扣分规则"
        assert int(m.group(1)) == LLM_RISK_PENALTY_TRIGGER
        assert int(m.group(2)) == LLM_RISK_PENALTY_POINTS
    m_en = re.search(r"risk>(\d+) deducts (\d+) points", analysis_prompts.ANALYSIS_PROMPT_EN)
    assert m_en, "英文 prompt 中找不到风险扣分规则"
    assert int(m_en.group(1)) == LLM_RISK_PENALTY_TRIGGER
    assert int(m_en.group(2)) == LLM_RISK_PENALTY_POINTS


def test_analysis_prompts_still_formatable():
    """prompt 拼接口径片段后仍必须能被 .format(title=, content=) 消费。

    analysis.py:458 / :160 按此约定调用;拼接若引入未转义的单花括号,
    这里会在运行期之前先红。
    """
    for prompt in (
        analysis_prompts.ANALYSIS_PROMPT,
        analysis_prompts.ANALYSIS_PROMPT_EN,
        analysis_prompts.PAPER_ANALYSIS_PROMPT,
    ):
        rendered = prompt.format(title="标题X", content="正文Y")
        assert "标题X" in rendered and "正文Y" in rendered


# ── picks / today_picks 消费方 ───────────────────────────────────────


def test_picks_mixin_defaults_resolve_from_config():
    """query_today_picks 的门槛与加成默认值必须运行时读 CONFIG,不得硬编码。"""
    from app.services._duckdb_picks_mixin import PicksMixin, resolve_picks_params

    sig = inspect.signature(PicksMixin.query_today_picks)
    assert sig.parameters["curation_threshold"].default is None
    assert sig.parameters["weight_bonus"].default is None
    assert sig.parameters["risk_threshold"].default is None

    assert resolve_picks_params(None, None) == (
        float(CONFIG["curation_threshold"]),
        float(CONFIG["picks_weight_bonus"]),
    )
    # 显式传参按原样透传(today_picks 主链路传 curation_threshold=0 只取候选)
    assert resolve_picks_params(0, 5) == (0.0, 5.0)


def test_today_picks_fallback_weight_bonus_matches_config():
    """OLTP fallback 的 weight_bonus 必须与 CONFIG 同源,不得再复制一份 8。"""
    from app.services.today_picks import _OLTP_FALLBACK_WEIGHT_BONUS

    assert CONFIG["picks_weight_bonus"] == _OLTP_FALLBACK_WEIGHT_BONUS
