"""SelectBench regression checks
PostgreSQL must be disposable."""

import csv
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401
from app.models.analysis import AiAnalysis
from app.models.content import ContentItem, ContentStatus
from app.models.content_label import ContentLabel
from app.models.source import Source
from app.services.auth_service import create_user
from scripts import selectbench_eval as evaluation, selectbench_import_labels as importer


@pytest_asyncio.fixture
async def bench(monkeypatch):
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(evaluation, "async_session", factory)
    monkeypatch.setattr(importer, "async_session", factory)
    async with factory() as db:
        admin = await create_user(db, email="bench-admin@example.com", password="Password123", role="admin")
        user = await create_user(db, email="bench-user@example.com", password="Password123", role="user")
        source = Source(name="AIHOT fixture", url="https://aihot.example/all.xml", source_type="RSS", status="active")
        db.add(source)
        await db.flush()
        ids = []
        now = datetime.now(UTC)
        for index, owner in enumerate([None, user.id, None]):
            item = ContentItem(
                title=f"Benchmark {index}",
                url=f"https://fixture.invalid/{index}",
                source_id=source.id,
                source_name=source.name,
                source_type="RSS",
                owner_user_id=owner,
                status=ContentStatus.ANALYZED,
                created_at=now - timedelta(hours=1),
                crawled_at=now - timedelta(hours=1),
            )
            db.add(item)
            await db.flush()
            db.add(
                AiAnalysis(
                    content_id=item.id,
                    curation_score=70,
                    creator_score=70,
                    risk_score=10,
                    summary_source="llm",
                    created_at=now,
                )
            )
            if index < 2:
                db.add(ContentLabel(content_id=item.id, label="worth_writing", source="human", labeled_by=admin.id))
            ids.append(item.id)
        await db.commit()
        identity = {"admin": admin.id, "user": user.id, "public": ids[0], "private": ids[1], "unlabeled": ids[2]}
    yield factory, identity
    await engine.dispose()


def write_csv(path, rows):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["content_id", "label", "notes"])
        writer.writeheader()
        writer.writerows(rows)


def test_zero_f1_is_not_unknown():
    scored = [
        (SimpleNamespace(selected=True, final_score=80), SimpleNamespace(content_id=1, title="wrong")),
        (SimpleNamespace(selected=False, final_score=10), SimpleNamespace(content_id=2, title="missed")),
    ]
    metrics = evaluation._metrics(scored, {1: "not_worth", 2: "worth_writing"})
    assert metrics["precision"] == metrics["recall"] == metrics["f1"] == 0


@pytest.mark.asyncio
async def test_gold_set_eager_loads_public_articles_and_sources(bench):
    _, ids = bench
    items, labels, analysis_ids = await evaluation.load_gold_set()
    assert [item.id for item in items] == [ids["public"]]
    assert labels == {ids["public"]: "worth_writing"}
    assert items[0].source.name == "AIHOT fixture" and items[0].analyses
    assert analysis_ids[ids["public"]] == items[0].analyses[-1].id


@pytest.mark.asyncio
async def test_import_defaults_to_dry_run_and_requires_explicit_actor_for_apply(bench, tmp_path):
    factory, ids = bench
    path = tmp_path / "labels.csv"
    write_csv(path, [{"content_id": ids["unlabeled"], "label": "not_worth"}])
    await importer.import_labels(str(path))
    async with factory() as db:
        assert await db.scalar(select(ContentLabel).where(ContentLabel.content_id == ids["unlabeled"])) is None
    with pytest.raises((ValueError, SystemExit), match="reviewer"):
        await importer.import_labels(str(path), False)


@pytest.mark.asyncio
async def test_apply_validates_whole_public_batch_and_records_explicit_reviewer(bench, tmp_path):
    factory, ids = bench
    path = tmp_path / "labels.csv"
    write_csv(
        path,
        [{"content_id": ids["public"], "label": "not_worth"}, {"content_id": ids["private"], "label": "not_worth"}],
    )
    with pytest.raises(ValueError, match="public"):
        await importer.import_labels(str(path), False, reviewer_user_id=ids["admin"])
    async with factory() as db:
        assert (
            await db.scalar(select(ContentLabel).where(ContentLabel.content_id == ids["public"]))
        ).label == "worth_writing"
    write_csv(path, [{"content_id": ids["unlabeled"], "label": "not_worth", "notes": "fixture review"}])
    with pytest.raises(ValueError, match="active admin"):
        await importer.import_labels(str(path), False, reviewer_user_id=ids["user"])
    result = await importer.import_labels(str(path), False, reviewer_user_id=ids["admin"])
    assert result["written"] == 1 and not result["dry_run"]
    async with factory() as db:
        label = await db.scalar(select(ContentLabel).where(ContentLabel.content_id == ids["unlabeled"]))
        assert label.labeled_by == ids["admin"] and label.evidence["csv_sha256"] == result["csv_sha256"]
        assert label.evidence["reviewer_identity_declared_by_operator"] is True


def test_duplicate_alias_ids_rejected_before_import(tmp_path):
    path = tmp_path / "duplicate.csv"
    write_csv(path, [{"content_id": "1", "label": "worth_writing"}, {"content_id": "001", "label": "not_worth"}])
    with pytest.raises(ValueError, match="duplicate"):
        importer._read_labels(str(path))


@pytest.mark.asyncio
async def test_matrix_reads_public_scope_and_absent_feed_item_stays_unknown(bench, tmp_path, monkeypatch):
    from scripts import selectbench_matrix as matrix

    factory, ids = bench
    monkeypatch.setattr(matrix, "async_session", factory)

    async def feed():
        return [{"guid": "0", "published": datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S +0000")}]

    monkeypatch.setattr(matrix, "fetch_aihot_selected", feed)
    result = await matrix.build_matrix(7, str(tmp_path))
    rows = [row for group in result["detail"].values() for row in group]
    assert {row["content_id"] for row in rows} == {ids["public"], ids["unlabeled"]}
    assert next(row for row in rows if row["content_id"] == ids["unlabeled"])["aihot_selected"] is None
    assert result["agreement_rate"] is None and result["aihot_absence_is_unknown"]
    assert result["pool_total"] == result["pool_loaded"] == 2 and not result["pool_truncated"]


@pytest.mark.asyncio
async def test_small_non_aihot_sample_fills_quota_without_duplicates_or_private_rows(bench):
    import random

    from scripts import selectbench_sample as sample

    factory, ids = bench
    async with factory() as db:
        source = await db.scalar(select(Source))
        source.url = "https://publisher.invalid/feed"
        await db.commit()
    sample_factory = sample.async_session
    sample.async_session = factory
    try:
        metadata = {}
        rows = await sample.load_non_aihot_layer(2, random.Random(42), metadata)
    finally:
        sample.async_session = sample_factory
    assert {row["content_id"] for row in rows} == {ids["public"], ids["unlabeled"]} and len(rows) == 2
    assert metadata == {"pool_total": 2, "pool_loaded": 2, "pool_truncated": False}


@pytest.mark.asyncio
async def test_evaluation_restores_configuration_and_marks_batch_scope(bench, tmp_path):
    import json

    baseline = dict(evaluation.scoring_engine.CONFIG)
    await evaluation.run([65, 70], str(tmp_path))
    payload = json.loads(next(tmp_path.glob("eval_*.json")).read_text())
    assert baseline == evaluation.scoring_engine.CONFIG
    assert payload["batch_comparison_only"] and not payload["independent_holdout_verified"]
    assert payload["gold_size"] == 1 and payload["scoring_config"] == baseline
    assert set(payload["results"]) == {"p65", "p70"}


def test_sample_cli_creates_directory_and_exports_blank_labels(tmp_path, monkeypatch):
    import json
    import sys

    from scripts import selectbench_sample as sample

    matrix_path = tmp_path / "matrix.json"
    matrix_path.write_text(
        json.dumps(
            {
                "owner_user_id": None,
                "aihot_absence_is_unknown": True,
                "detail": {
                    "aihot_only": [{"content_id": 10, "label": "worth_writing", "notes": "old answer"}],
                    "te_only": [],
                    "both": [],
                    "neither": [],
                },
            }
        )
    )
    out_dir = tmp_path / "new-output"

    async def pool(quota, rng, metadata):
        return [{"content_id": 11, "label": "not_worth", "notes": "inherited"}]

    monkeypatch.setattr(sample, "load_non_aihot_layer", pool)
    monkeypatch.setattr(
        sys, "argv", ["selectbench_sample.py", "--matrix", str(matrix_path), "--out", str(out_dir), "--total", "4"]
    )
    sample.main()
    with next(out_dir.glob("*.csv")).open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert {int(row["content_id"]) for row in rows} == {10, 11}
    assert all(row["label"] == row["notes"] == "" for row in rows)
    manifest = json.loads(next(out_dir.glob("*.manifest.json")).read_text())
    assert manifest["actual"] == 2 and manifest["gold_labels_verified"] is False


def test_hard_filtered_positive_remains_in_recall_denominator():
    inputs = [
        evaluation.scoring_engine.ScoringInput(
            content_id=i,
            title=f"item {i}",
            curation_score=90,
            creator_score=90,
            info_density=90,
            actionability=90,
            source_weight=90,
            viral_score=90,
            freshness_score=90,
            quality_score=90,
            hot_score=90,
            risk_score=risk,
        )
        for i, risk in [(1, 0), (2, 100)]
    ]
    scored = evaluation.scoring_engine.score_items(inputs)
    assert len(scored) == 1 and scored[0][0].selected
    metrics = evaluation._metrics(scored, {1: "worth_writing", 2: "worth_writing"}, inputs)
    assert metrics["n"] == 2 and metrics["scored_n"] == 1
    assert metrics["recall"] == 0.5 and metrics["f1"] == 0.667
    assert metrics["false_negatives"] == [
        {"content_id": 2, "final_score": None, "title": "item 2", "excluded_from_scoring": True}
    ]
    all_filtered = evaluation._metrics([], {2: "worth_writing"}, inputs[1:])
    assert all_filtered["n"] == 1 and all_filtered["recall"] == all_filtered["f1"] == 0
