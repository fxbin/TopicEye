# Agent Note: 迁移往返测试要写显式 revision，不能用 "-1"

Status: implemented — #179 加 web_vitals 迁移时踩到并修复

## Problem

`tests/test_migrations.py::test_mute_rules_migration_roundtrip` 原本这样写：

```python
command.upgrade(cfg, "head")
assert "mute_rules" in _tables()
command.downgrade(cfg, "-1")          # ← 指当前 head 的上一版
assert "mute_rules" not in _tables()
```

`"-1"` 的语义是「当前 head 的上一版」，不是「被测的那条迁移」。#171 时 mute_rules 恰好是最新迁移，断言成立；#179 新增 web_vitals 迁移后 head 变成 web_vitals，`downgrade -1` 退掉的是 web_vitals，mute_rules 纹丝不动 → 用例红了。

也就是说：**这条测试断言的不是它想断言的东西，它断言的是「我恰好是最新迁移」**。任何后来新增迁移的人都会踩到，而且症状看起来像是自己的迁移有问题，实际是被测对象漂移了。

## Decision

往返测试一律降级到**被测迁移自己的父 revision**，写死 revision id，不写 `-1`：

- `MUTE_RULES_PARENT_REVISION = "c7a4e9f21b86"`（mute_rules 的父）
- `WEB_VITALS_PARENT_REVISION = "d2b7f9a41c05"`（web_vitals 的父）

注意是**父**而不是自己：降到被测迁移自己，那张表还在，降不下去。

新增迁移时同步加一条自己的往返测试（表建出来 → 约束齐全 → 降到父 revision 表消失 → 再 upgrade 重建），不要指望上一条迁移的往返测试顺带覆盖。

## Why

教训必须机器化：断言要钉住**被测对象**，而不是当时恰好成立的事实。「我恰好是最新」是随时间漂移的隐含前提，写进断言就等于埋雷。

## 边界

- revision id 是写死的常量（文件顶部），迁移被 rebase 或 squash 后需要同步改——这是故意的：改了就得看一眼，改成动态推导等于把「被测对象漂移」这个坑重新埋回去。
- 本地一次性 PG 上验证过：upgrade head → downgrade 到父 revision → 表与约束随迁移增删 → 再 upgrade 重建。
