"""一次性幂等脚本：把 llm_models.api_key 的明文值加密为 enc:v1: 格式。

背景：MP-P0-T2 之前 LlmModel.api_key 以明文落库。现已接线
secret_store.encrypt_secret/decrypt_secret，本脚本把存量明文行加密回填，
让 DB 不再保存任何明文凭据。

用法（在 backend/ 目录下，容器内或本地 venv）：
    python scripts/migrate_llm_api_keys.py            # dry-run，只打印统计，不写库
    python scripts/migrate_llm_api_keys.py --apply    # 真写库

前置（必须）：
    1. 配好 INTEGRATION_SECRET_KEY（见 docs/SECRET_MANAGEMENT.md）。
       生产环境若用默认 key，secret_store 会直接 raise RuntimeError。
    2. 备份数据库：
       ./scripts/backup_db.sh
    迁移是单向的（明文→加密），回滚只能靠备份恢复。

特性：
- 幂等：已是 enc:v1: 的行跳过，可安全重复运行。
- 只改 api_key 字段，不动其他列、不改 enabled/status。
- 分批 commit（每 BATCH_SIZE 行一次）。
- 不打印任何 key 原值，只打印行 id 与「明文/已加密」计数。
"""

from __future__ import annotations  # noqa: E402

import argparse  # noqa: E402
import asyncio  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402

# 脚本运行时 sys.path[0] 是 scripts/ 目录，需把项目根（/app 或 backend/）加入
# 才能 import app.*。兼容容器内（/app）和本地 venv（backend/）两种场景。
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sqlalchemy import select  # noqa: E402

from app.core.database import async_session  # noqa: E402
from app.models.llm_model import LlmModel  # noqa: E402
from app.services.secret_store import encrypt_secret, is_encrypted_secret  # noqa: E402

logger = logging.getLogger("migrate_llm_api_keys")
logging.basicConfig(level=logging.INFO, format="%(message)s")

BATCH_SIZE = 20


async def _migrate(*, apply: bool) -> None:
    plaintext_rows: list[LlmModel] = []
    encrypted_count = 0
    async with async_session() as db:
        result = await db.execute(select(LlmModel))
        all_models = result.scalars().all()

        for model in all_models:
            if not model.api_key:
                continue
            if is_encrypted_secret(model.api_key):
                encrypted_count += 1
            else:
                plaintext_rows.append(model)

        total = encrypted_count + len(plaintext_rows)
        logger.info("=" * 60)
        logger.info("LLM api_key 加密迁移扫描结果")
        logger.info("=" * 60)
        logger.info("总行数（含 api_key）:    %d", total)
        logger.info("已加密 (enc:v1:):       %d  ← 跳过", encrypted_count)
        logger.info("明文待迁移:             %d", len(plaintext_rows))
        if plaintext_rows:
            logger.info("明文行 id: %s", [m.id for m in plaintext_rows])

        if not plaintext_rows:
            logger.info("无需迁移，所有 api_key 均已加密。")
            return

        if not apply:
            logger.info("-" * 60)
            logger.info("【DRY-RUN】未写库。确认无误后加 --apply 执行迁移。")
            logger.info("迁移前请先备份: ./scripts/backup_db.sh")
            return

        # --apply：真写库
        logger.info("-" * 60)
        logger.info("【APPLY】开始加密写入（分批 %d 行/次）…", BATCH_SIZE)
        migrated = 0
        for model in plaintext_rows:
            # is_encrypted_secret 守卫：防御性，防止并发写入已加密值后被二次加密。
            if is_encrypted_secret(model.api_key):
                continue
            model.api_key = encrypt_secret(model.api_key)
            migrated += 1
            if migrated % BATCH_SIZE == 0:
                await db.commit()
                logger.info("  已迁移 %d / %d", migrated, len(plaintext_rows))
        await db.commit()
        logger.info("完成：迁移 %d 行，跳过 %d 行（已加密）。", migrated, encrypted_count)
        logger.info("建议：用 GET /models 确认 api_key_set 仍为 true，并跑一次 /models/{id}/test。")


def main() -> None:
    parser = argparse.ArgumentParser(description="把 llm_models.api_key 明文加密为 enc:v1:")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真写库（默认 dry-run，只扫描不写）",
    )
    args = parser.parse_args()
    asyncio.run(_migrate(apply=args.apply))


if __name__ == "__main__":
    main()
