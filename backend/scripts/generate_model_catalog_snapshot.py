#!/usr/bin/env python3
"""生成 models.dev 模型目录内置快照。

从 https://models.dev/api.json（MIT 许可，OpenCode 社区维护）拉取全量目录，
裁剪到应用需要的字段后写入 backend/app/data/model_catalog_snapshot.json，
作为应用冷启动（无外网/目录表为空）时的种子数据。

用法：
    python scripts/generate_model_catalog_snapshot.py              # 在线拉取
    python scripts/generate_model_catalog_snapshot.py --input /tmp/api.json
                                                    # 复用已下载的全量 JSON

快照只在模型目录字段变化明显时手动重新生成（价格/上下文窗口不是高频
变动数据），避免 git 历史被大文件反复膨胀。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

MODELS_DEV_API_URL = "https://models.dev/api.json"
BACKEND_DIR = Path(__file__).resolve().parent.parent
SNAPSHOT_PATH = BACKEND_DIR / "app" / "data" / "model_catalog_snapshot.json"

# 每个模型条目保留的字段（其余如 description/reasoning_options/knowledge
# 等对预填无价值，裁掉以控制快照体积）。
_KEEP_MODEL_FIELDS = (
    "name",
    "limit",
    "cost",
    "tool_call",
    "structured_output",
    "reasoning",
    "modalities",
    "open_weights",
    "status",
    "release_date",
    "last_updated",
)
_KEEP_LIMIT_KEYS = ("context", "output")
_KEEP_COST_KEYS = ("input", "output", "cache_read")
_KEEP_MODALITY_KEYS = ("input", "output")


def _trim_model(raw: dict) -> dict:
    trimmed: dict = {}
    for key in _KEEP_MODEL_FIELDS:
        if key not in raw:
            continue
        value = raw[key]
        if key == "limit" and isinstance(value, dict):
            value = {k: value[k] for k in _KEEP_LIMIT_KEYS if value.get(k) is not None}
        elif key == "cost" and isinstance(value, dict):
            value = {k: value[k] for k in _KEEP_COST_KEYS if value.get(k) is not None}
        elif key == "modalities" and isinstance(value, dict):
            value = {k: value[k] for k in _KEEP_MODALITY_KEYS if value.get(k) is not None}
        if value not in ({}, None):
            trimmed[key] = value
    return trimmed


def build_snapshot(catalog: dict) -> dict:
    providers: dict = {}
    model_count = 0
    for provider_id, provider in sorted(catalog.items()):
        if not isinstance(provider, dict):
            continue
        models = provider.get("models")
        if not isinstance(models, dict) or not models:
            continue
        trimmed_models = {}
        for model_id, raw_model in models.items():
            if isinstance(raw_model, dict):
                trimmed_models[model_id] = _trim_model(raw_model)
        if not trimmed_models:
            continue
        providers[provider_id] = {
            "name": provider.get("name") or provider_id,
            "models": trimmed_models,
        }
        model_count += len(trimmed_models)
    return {
        "source": MODELS_DEV_API_URL,
        "license": "MIT (https://github.com/sst/models.dev)",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "provider_count": len(providers),
        "model_count": model_count,
        "catalog": providers,
    }


def load_catalog(input_path: str | None) -> dict:
    if input_path:
        with open(input_path, encoding="utf-8") as f:
            return json.load(f)
    with urllib.request.urlopen(MODELS_DEV_API_URL, timeout=120) as resp:  # noqa: S310
        return json.load(resp)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", help="已下载的 api.json 路径（离线复用）", default=None)
    args = parser.parse_args()

    catalog = load_catalog(args.input)
    if not isinstance(catalog, dict) or not catalog:
        print("ERROR: catalog payload is empty or not an object", file=sys.stderr)
        return 1

    snapshot = build_snapshot(catalog)
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    size_kb = SNAPSHOT_PATH.stat().st_size / 1024
    print(
        f"snapshot written: {SNAPSHOT_PATH}\n"
        f"providers={snapshot['provider_count']} models={snapshot['model_count']} size={size_kb:.0f}KB"
    )
    if size_kb > 3 * 1024:
        print("WARNING: snapshot exceeds 3MB — consider regenerating less frequently", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
