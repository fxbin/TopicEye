"""前端体验指标样本的 ORM 查询与写入（#179）。

只做查询与写入，不承载口径判断：p75 怎么算、阈值怎么定、路径怎么归一
都在 service 层（见 :mod:`app.services.web_vitals_service`）。

分位数用**最近秩法**（nearest rank）而不是 PostgreSQL 的 ``percentile_cont``：

- ``percentile_cont`` 只在 PG/DuckDB 有，SQLite 没有，测试就跑不起来；
- 最近秩法「排序后取第 ``ceil(p/100 × N)`` 个」在两个库上行为一致，
  且没有插值，结论可复现。

排名表达式 ``(total × p + 99) / 100`` 就是 ``ceil(total × p / 100)`` 的整数写法
（PG 与 SQLite 的整数除法都截断，行为一致）。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import and_, case, delete, func, insert, select

from app.models.web_vitals import WebVitalSample
from app.repositories.base import BaseRepository


def _nearest_rank_condition(rn, total, percentile: int):
    """最近秩排名条件：rn 是满足 ``rn × 100 ≥ total × p`` 的最小整数。

    等价于 ``rn == ceil(total × p / 100)``，但**只用乘法与比较**：
    SQLAlchemy 2.0 里整数列的 ``/`` 会渲染成真除法（`399 / 100` 得 3.99），
    截断语义会丢；这个写法在 PG 与 SQLite 上结果完全一致。
    """
    target = total * percentile
    return and_(rn * 100 >= target, (rn - 1) * 100 < target)


class WebVitalsRepository(BaseRepository[WebVitalSample]):
    """web_vitals_samples 表的读写。"""

    model = WebVitalSample

    async def insert_samples(self, rows: Sequence[dict[str, Any]]) -> int:
        """批量写入样本，返回写入条数。

        用 bulk insert 而非逐条 ORM add：上报是高频小批量写入，
        逐条 add 会把往返次数放大到条数级。
        """
        if not rows:
            return 0
        await self.db.execute(insert(WebVitalSample), list(rows))
        return len(rows)

    async def count_samples(self, cutoff: datetime, navigation_type: str = "all") -> int:
        stmt = select(func.count(WebVitalSample.id)).where(WebVitalSample.captured_at >= cutoff)
        if navigation_type != "all":
            stmt = stmt.where(WebVitalSample.navigation_type == navigation_type)
        return await self.db.scalar(stmt) or 0

    async def percentiles_by_metric(self, cutoff: datetime, navigation_type: str = "all") -> Sequence[tuple]:
        """按指标聚合窗口内的 p50 / p75 / p95 与样本数。

        返回 (metric, p50, p75, p95, count) 元组列表。
        """
        ranked = self._ranked(cutoff, navigation_type, [WebVitalSample.metric])
        total = ranked.c.total
        stmt = select(
            ranked.c.metric,
            func.max(case((_nearest_rank_condition(ranked.c.rn, total, 50), ranked.c.value))).label("p50"),
            func.max(case((_nearest_rank_condition(ranked.c.rn, total, 75), ranked.c.value))).label("p75"),
            func.max(case((_nearest_rank_condition(ranked.c.rn, total, 95), ranked.c.value))).label("p95"),
            func.count().label("sample_count"),
        ).group_by(ranked.c.metric)
        result = await self.db.execute(stmt)
        return result.all()

    async def percentiles_by_path_metric(
        self,
        cutoff: datetime,
        navigation_type: str = "all",
        limit: int = 300,
    ) -> Sequence[tuple]:
        """按 (路由模板, 指标) 聚合 p75 与样本数，按样本数降序取前 limit 组。

        返回 (path, metric, p75, count) 元组列表。
        """
        ranked = self._ranked(cutoff, navigation_type, [WebVitalSample.path, WebVitalSample.metric])
        total = ranked.c.total
        stmt = (
            select(
                ranked.c.path,
                ranked.c.metric,
                func.max(case((_nearest_rank_condition(ranked.c.rn, total, 75), ranked.c.value))).label("p75"),
                func.count().label("sample_count"),
            )
            .group_by(ranked.c.path, ranked.c.metric)
            .order_by(func.count().desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return result.all()

    async def delete_older_than(self, cutoff: datetime) -> int:
        """删除 cutoff 之前的样本，返回删除条数。"""
        result = await self.db.execute(delete(WebVitalSample).where(WebVitalSample.captured_at < cutoff))
        return int(result.rowcount or 0)

    @staticmethod
    def _ranked(cutoff: datetime, navigation_type: str, partition_by: list):
        """构造带序号与分组大小的子查询，供分位数聚合复用。"""
        stmt = select(
            WebVitalSample.path.label("path"),
            WebVitalSample.metric.label("metric"),
            WebVitalSample.value.label("value"),
            func.row_number().over(partition_by=partition_by, order_by=WebVitalSample.value).label("rn"),
            func.count().over(partition_by=partition_by).label("total"),
        ).where(WebVitalSample.captured_at >= cutoff)
        if navigation_type != "all":
            stmt = stmt.where(WebVitalSample.navigation_type == navigation_type)
        return stmt.subquery()
