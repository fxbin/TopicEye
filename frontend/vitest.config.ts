import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

// 固定时区，保证 datetime 相关断言在本地（macOS）与 CI（ubuntu）一致。
// 放在 defineConfig 之前，确保 worker 初始化 Date 前就已生效。
process.env.TZ = process.env.TZ || 'UTC';

export default defineConfig({
  resolve: {
    // 复用 tsconfig 的 `@/* -> ./src/*` 别名，让被测模块内部的 `@/lib/...` 能解析。
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    // 纯逻辑测试无需 DOM，node 环境启动更快。
    environment: 'node',
    globals: false,
    include: ['src/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      // 门禁只统计已写测试的纯逻辑模块，避免 100+ 个未测文件把阈值拖到 0。
      // 与后端 CI 的“渐进式 lint”同理：先立稳基线，新增测试后再把模块加进来逐步抬高。
      // Vitest 4 已移除 coverage.all，include 命中的文件默认全部计入（未覆盖也算 0）。
      include: [
        'src/lib/recommendation.ts',
        'src/lib/navigation.ts',
        'src/lib/utils.ts',
        'src/lib/datetime.ts',
      ],
      reporter: ['text', 'html', 'lcov'],
      reportsDirectory: './coverage',
      thresholds: {
        // 锁定当前实测水平（stmts/lines ~95、branch ~92、funcs 100）并留 ~5-7% 缓冲，
        // 让门禁真正拦得住回归；新增测试后可继续上调。
        lines: 90,
        functions: 90,
        statements: 90,
        branches: 85,
      },
    },
  },
});
