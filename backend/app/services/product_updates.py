"""Product updates service — 留作未来扩展用.

历史上有 BUILTIN_PRODUCT_UPDATES (Python tuple) 作为内置更新记录,
现在所有版本记录都通过 alembic migration seed 到 product_updates 表,
DB 是唯一数据源. 这一层暂无函数, 保留文件作为占位以便未来加业务逻辑
(例如: 聚合统计、版本间 diff、外部 webhook 等).
"""

from __future__ import annotations
