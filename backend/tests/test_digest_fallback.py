from app.services.digest_fallback import build_daily_editorial_fallback, build_digest_fallback


def test_build_digest_fallback_returns_chinese_summary_and_picks():
    digest = build_digest_fallback(
        [
            {
                "title": "AI 视频工具开始争夺创作者工作流",
                "category": "AI",
                "source_name": "技术观察",
                "adjusted_score": 86.4,
                "summary": "多家平台更新视频生成能力，重点面向短视频和营销素材。",
                "recommendation": "适合拆解成创作者工具选型和实测对比。",
                "url": "https://example.com/a",
            },
            {
                "title": "小红书本地生活内容升温",
                "category": "小红书",
                "source_name": "运营笔记",
                "curation_score": 74,
                "summary": "探店和城市活动类内容近期互动稳定。",
                "url": "https://example.com/b",
            },
        ],
        label="今日快照",
    )

    assert "系统已基于 2 条已分析素材生成基础摘要" in digest["overview"]
    assert digest["keywords"][0] == "AI"
    assert digest["top_picks"][0]["title"] == "AI 视频工具开始争夺创作者工作流"
    assert digest["top_picks"][0]["reason"].startswith("综合分约 86.4")
    assert digest["top_picks"][0]["source_url"] == "https://example.com/a"


def test_daily_fallback_keeps_an_editorial_lead_and_actionable_feature_cards():
    digest = build_daily_editorial_fallback(
        [
            {
                "title": "AI 视频工具开始争夺创作者工作流",
                "category": "产品更新",
                "source_name": "技术观察",
                "adjusted_score": 86.4,
                "summary": "多家平台更新视频生成能力，重点面向短视频和营销素材。",
                "recommendation": "适合拆解成创作者工具选型和实测对比。",
                "url": "https://example.com/a",
            },
            {
                "title": "开源 Agent 框架补齐本地工具调用",
                "category": "开源项目",
                "source_name": "开发者社区",
                "adjusted_score": 80.1,
                "summary": "新版本补充了本地工具调用能力。",
                "url": "https://example.com/b",
            },
        ],
        label="今日快照",
    )

    assert "今天先写" in digest["overview"]
    assert "LLM" not in digest["overview"]
    assert digest["top_picks"][0]["source_idx"] == 1
    assert digest["top_picks"][0]["tier"] == "feature"
    assert digest["top_picks"][0]["angles"]
    assert digest["top_picks"][0]["source_title"] == "AI 视频工具开始争夺创作者工作流"
