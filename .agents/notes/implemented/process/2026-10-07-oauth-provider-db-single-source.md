# Agent Note: 第三方登录凭据改 DB 单一事实源，不留 env 兼容路径

Status: implemented — #94：oauth_providers 表 + 后台配置 + 迁移一次性导入 env 旧值，config.py 旧字段已删

## Problem

OAuth（Google / GitHub）凭据走 `.env`：`app/core/oauth.py` 在 import 时按 `settings` 注册 provider，
`ENABLED_PROVIDERS` 是进程级常量。改凭据 = 改配置文件 + 重启；而且「同一份配置」分散在
env 文件与运行进程两处，谁也不能在线改。后台已有邮件 / webhook / LLM 密钥的 DB 配置先例，
唯独登录凭据还留在文件里。

## Decision

1. **DB 单一事实源，直接删 env 路径**（delete，不是 compat）：`oauth_providers` 表存
   client_id / Fernet 密文 / enabled，`config.py` 的 4 个 `OAUTH_*_CLIENT_*` 字段与
   `oauth_enabled_providers` 属性一并删除。迁移升级时把旧 env 值一次性导入库，之后 env 变量失效。
2. **请求期解析，不做缓存**：登录 / 回调 / 按钮列表都是低频端点，每次读库构造 authlib client
   （全新 `OAuth()` 实例 + `register`，不复用全局注册表）。后台改凭据即时生效是需求本体，
   缓存只会引入失效 bug。
3. **协议细节留在代码里**：endpoint / scope 属于 `PROVIDER_SPECS` 常量（固定 google / github
   两档），DB 只存凭据与开关——凭据是环境差异，协议是代码版本。
4. `OAUTH_FRONTEND_REDIRECT_URL` / `SITE_BASE_URL` 维持 env：部署级常量，不是凭据，混进
   后台配置反而让「换个环境」需要登录后台。

## Alternatives considered

- **env 保留为 fallback（双源）。** 否决：两处真源必然漂移——后台改了 secret、env 里还是旧值，
  重启后凭空回滚，这种静默不一致比「重启后必须先配后台」更危险。反熵原则选 delete。
- **全局注册表 + 配置变更时 re-register。** 否决：authlib 的 `OAuth()` 注册表跨请求缓存 client，
  并发写有竞态；请求级全新实例成本可忽略（登录是低频端点），换来无状态可测。
- **复用 `app_settings` KV 表存 JSON。** 否决：凭据需要列级加密与独立更新语义，KV JSON 把
  两个 provider 拴在一个 key 上，改一个写整个对象，还绕开了 upsert 主键约束。

## Consequences

- 生产升级前置条件：`INTEGRATION_SECRET_KEY`（或自定义 `APP_SECRET_KEY`）必须已设置，否则
  迁移 seed 时 `encrypt_secret` fail-closed 抛错——与 LLM api_key / 邮件密码同一把钥匙同一约束。
- secret 解密失败（密钥轮换）会让登录 500 而非静默隐藏按钮：部署级错误要显式暴露。
- 新增 provider = `SUPPORTED_OAUTH_PROVIDERS` 加名字 + `PROVIDER_SPECS` 加 spec + 迁移，
  不再只是「填两个 env 变量」——两档固定是当前边界，泛化到自定义 OIDC 时再议。

## Verification

- `tests/test_oauth_provider_admin_api.py`：admin 权限 / 加密落库 / 留空保留 / 启用校验 /
  即时生效（含真实 authlib client 302 + state cookie）/ 密文解密闭环
- 迁移：带 env 升级 seed（enc:v1: + enabled）、无 env 升级空表、`downgrade -1` 删表，均实测
- `tests_oauth_patch/` 全量适配新 seam（`_resolve_provider_client` 单点替换）
