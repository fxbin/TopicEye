"""Unit tests for the interest vector personalization service."""

from __future__ import annotations

import pytest

from app.services.interest_vector_service import (
    BOOST_MAX,
    BOOST_MIN,
    compute_personalization_boost,
)


class TestComputePersonalizationBoost:
    """Test the personalization boost calculation."""

    def test_empty_user_vector_returns_zero(self):
        assert compute_personalization_boost(["AI", "科技"], {}) == 0.0

    def test_empty_content_tags_returns_zero(self):
        user_vector = {"ai": 2.0, "科技": 1.5}
        assert compute_personalization_boost([], user_vector) == 0.0

    def test_none_content_tags_returns_zero(self):
        user_vector = {"ai": 2.0}
        assert compute_personalization_boost(None, user_vector) == 0.0

    def test_no_matching_tags_returns_zero(self):
        user_vector = {"ai": 2.0, "科技": 1.5}
        assert compute_personalization_boost(["娱乐", "八卦"], user_vector) == 0.0

    def test_positive_boost_for_matching_tags(self):
        user_vector = {"ai": 2.0, "科技": 1.5}
        boost = compute_personalization_boost(["AI", "科技"], user_vector)
        assert boost > 0
        assert boost <= BOOST_MAX

    def test_negative_boost_for_disliked_tags(self):
        user_vector = {"娱乐": -2.0, "八卦": -1.5}
        boost = compute_personalization_boost(["娱乐", "八卦"], user_vector)
        assert boost < 0
        assert boost >= BOOST_MIN

    def test_boost_is_clamped_to_max(self):
        # Very high weight should be clamped
        user_vector = {"ai": 100.0}
        boost = compute_personalization_boost(["AI"], user_vector)
        assert boost == BOOST_MAX

    def test_boost_is_clamped_to_min(self):
        # Very negative weight should be clamped
        user_vector = {"娱乐": -100.0}
        boost = compute_personalization_boost(["娱乐"], user_vector)
        assert boost == BOOST_MIN

    def test_category_is_used_as_extra_tag(self):
        user_vector = {"ai": 2.0}
        # No content tags, but category matches
        boost = compute_personalization_boost([], user_vector, content_category="AI")
        assert boost > 0

    def test_tags_are_case_insensitive(self):
        user_vector = {"ai": 2.0}
        boost_lower = compute_personalization_boost(["ai"], user_vector)
        boost_upper = compute_personalization_boost(["AI"], user_vector)
        boost_mixed = compute_personalization_boost(["Ai"], user_vector)
        assert boost_lower == boost_upper == boost_mixed

    def test_mixed_positive_negative_tags(self):
        user_vector = {"ai": 3.0, "娱乐": -2.0}
        boost = compute_personalization_boost(["AI", "娱乐"], user_vector)
        # Net weight = (3.0 + (-2.0)) / 2 = 0.5 → boost = 0.5 * 15 = 7.5
        assert boost == pytest.approx(7.5, abs=0.1)

    def test_partial_match(self):
        user_vector = {"ai": 3.0}
        # Only 1 of 3 tags matches
        boost = compute_personalization_boost(["AI", "娱乐", "八卦"], user_vector)
        # avg_weight = 3.0 / 3 = 1.0 → boost = 1.0 * 15 = 15.0
        assert boost == pytest.approx(BOOST_MAX, abs=0.1)


class TestApplyPersonalizationBoost:
    """Test the batch apply function."""

    @pytest.mark.asyncio
    async def test_none_user_id_adds_zero_boost(self):
        from app.services.interest_vector_service import apply_personalization_boost

        items = [{"id": 1, "analysis": {"adjusted_curation_score": 80}}]
        result = await apply_personalization_boost(None, None, items)
        assert result[0]["personalization_boost"] == 0.0
        assert result[0]["analysis"]["adjusted_curation_score"] == 80

    @pytest.mark.asyncio
    async def test_items_without_analysis_get_boost_field(self):
        from unittest.mock import AsyncMock, MagicMock
        from app.services.interest_vector_service import apply_personalization_boost

        # Mock DB session that returns empty vector (user has no data)
        mock_db = MagicMock()
        mock_repo = MagicMock()
        mock_repo.get_user_vector = AsyncMock(return_value={})
        # Patch the repository constructor
        import app.services.interest_vector_service as svc_mod
        original_repo = svc_mod.InterestVectorRepository
        svc_mod.InterestVectorRepository = lambda db: mock_repo
        try:
            items = [{"id": 1, "tags": ["AI"], "category": "AI"}]
            result = await apply_personalization_boost(mock_db, 99999, items)
            assert result[0]["personalization_boost"] == 0.0
        finally:
            svc_mod.InterestVectorRepository = original_repo
