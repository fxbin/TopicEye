"""前端体验指标（/api/v1/metrics/web-vitals）的请求/响应模型。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class WebVitalSampleIn(BaseModel):
    """单条上报样本。

    字段只做形状校验（长度/范围），语义校验（metric 白名单、值域、路径归一）
    在 service 层做——那是口径真源。
    """

    metric: str = Field(min_length=1, max_length=16, description="LCP | INP | CLS | FCP | TTFB")
    value: float = Field(description="指标原值：毫秒（CLS 除外，为无量纲分值）")
    path: str = Field(min_length=1, max_length=200, description="页面 pathname，服务端会归一化")
    navigation_type: str = Field(default="navigate", max_length=20)
    device_class: str = Field(default="unknown", max_length=10)


class WebVitalReportRequest(BaseModel):
    # 一次浏览最多 5 个指标（LCP/INP/CLS/FCP/TTFB），20 条留足未来批量的余量；
    # 上限同时限制匿名上报的写放大。
    samples: list[WebVitalSampleIn] = Field(min_length=1, max_length=20)


class WebVitalReportResponse(BaseModel):
    accepted: int = Field(description="成功落库的条数")
    rejected: int = Field(description="因非法或越界被丢弃的条数")


class MetricPercentile(BaseModel):
    """单个指标在窗口内的分位数聚合。"""

    metric: str
    p50: float | None = None
    p75: float | None = None
    p95: float | None = None
    rating: str = Field(description="按 p75 判定的档位：good | needs-improvement | poor")
    sample_count: int = 0


class RoutePercentile(BaseModel):
    """按路由模板拆分的单指标 p75。"""

    path: str
    metric: str
    p75: float
    rating: str
    sample_count: int


class WebVitalsSummaryResponse(BaseModel):
    hours: int
    navigation_type: str = Field(description="navigate | soft-navigation | all")
    generated_at: datetime
    sample_count: int = 0
    metrics: list[MetricPercentile] = Field(default_factory=list)
    routes: list[RoutePercentile] = Field(default_factory=list)
