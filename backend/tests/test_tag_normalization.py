"""标签规范化（services/tag_normalization.py）单元测试。"""

from __future__ import annotations

from app.services.tag_normalization import normalize_tag_key, normalize_tag_list, split_compound_tags


def test_split_compound_tags_variants():
    assert split_compound_tags("AI安全, 联合国, 风险警告") == ["AI安全", "联合国", "风险警告"]
    assert split_compound_tags("模型；产品；工具") == ["模型", "产品", "工具"]
    assert split_compound_tags("a、b") == ["a", "b"]


def test_slash_and_pipe_are_not_splitters():
    # "BERT/NLP" 这类合法整段标签不能被拆
    assert split_compound_tags("BERT/NLP") == ["BERT/NLP"]
    assert split_compound_tags("a|b") == ["a|b"]


def test_normalize_tag_key_lowercases_ascii_only():
    assert normalize_tag_key("AI") == "ai"
    assert normalize_tag_key("OpenAI") == "openai"
    assert normalize_tag_key("机器学习") == "机器学习"  # 中文无大小写
    assert normalize_tag_key("  ＡＩ  ") == "ai"  # NFKC 折叠全角 + 去空白
    assert normalize_tag_key("machine   learning") == "machine learning"


def test_normalize_tag_list_case_dedup_keeps_order():
    assert normalize_tag_list(["AI", "ai", "AI安全", "ai"]) == ["ai", "ai安全"]


def test_normalize_tag_list_splits_compound_elements():
    # 模型把复合串当成单个数组元素返回
    assert normalize_tag_list(["AI安全, 联合国, 风险警告"]) == ["ai安全", "联合国", "风险警告"]


def test_normalize_tag_list_truncates_and_dedups():
    many = [f"tag{i}" for i in range(20)]
    assert normalize_tag_list(many, max_items=5) == ["tag0", "tag1", "tag2", "tag3", "tag4"]


def test_normalize_tag_list_tolerates_json_string_and_none():
    assert normalize_tag_list('["AI", "模型"]') == ["ai", "模型"]
    assert normalize_tag_list("not json") == ["not json"]
    assert normalize_tag_list(None) == []
    assert normalize_tag_list(42) == []
    assert normalize_tag_list(["ok", 7, None, ""]) == ["ok"]


def test_normalize_tag_list_idempotent():
    once = normalize_tag_list(["AI安全, 联合国", "OpenAI"])
    assert normalize_tag_list(once) == once
