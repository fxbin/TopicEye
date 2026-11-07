import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import ts from 'typescript';
import { AdminPageShell } from './admin-ui';
import { StatTile } from './StatTile';

describe('工作台视觉合同', () => {
  it('后台外壳固定宽度和页面级间距，宽表格在内部滚动', () => {
    const html = renderToStaticMarkup(<AdminPageShell><h1>标题</h1></AdminPageShell>);
    expect(html).toContain('max-w-[1200px]');
    expect(html).toContain('space-y-5');
    expect(html).toContain('admin-workspace');
  });
  it('统计卡保留长指标名称和说明，不用截断掩盖挤压', () => {
    const html = renderToStaticMarkup(<StatTile label="模型请求成功率与超时统计" value="92.4%" hint="13778 次成功 / 884 次失败" tone="teal" />);
    expect(html).toContain('模型请求成功率与超时统计');
    expect(html).toContain('13778 次成功 / 884 次失败');
    expect(html).not.toContain('truncate');
    expect(html).toContain('tabular-nums');
  });
  it('前台工作台主标题使用同一字号入口', () => {
    const files = ['_home-feed.tsx', 'stats/page.tsx', 'trending/page.tsx', 'today-picks/page.tsx', 'my-topics/page.tsx', 'my-topics/config/page.tsx', 'content-check/page.tsx', 'plans/page.tsx', 'profile/page.tsx', 'changelog/page.tsx', 'weread/page.tsx', 'sources/me/page.tsx', 'novel/page.tsx', 'favorites/_components.tsx', 'algorithm/components.tsx'];
    for (const file of files) {
      const text = readFileSync(join(process.cwd(), 'src/app', file), 'utf8');
      for (const heading of text.matchAll(/<h1 className="([^"]*)"/g)) {
        expect(heading[1], file).toContain('page-title');
        expect(heading[1], file).not.toMatch(/font-black|text-\[\d+px\]/);
      }
    }
  });
  it('页面不得重新引入私有宽度、重复指标卡或把主标题藏进卡片', () => {
    const errors: string[] = [];
    function scan(dir: string) {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const file = join(dir, entry.name);
        if (entry.isDirectory()) { scan(file); continue; }
        if (!file.endsWith('.tsx') || file.endsWith('.test.tsx')) continue;
        const text = readFileSync(file, 'utf8');
        const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
        const visit = (node: ts.Node) => {
          if ((ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) && node.tagName.getText(source) === 'AdminPageShell' && node.attributes.properties.some(p => ts.isJsxAttribute(p) && p.name.getText(source) === 'maxWidth')) errors.push(file + ': custom shell width');
          if (ts.isFunctionDeclaration(node) && ['Surface', 'StatTile', 'SummaryCard', 'KpiCard'].includes(node.name?.text ?? '')) errors.push(file + ': duplicate visual primitive');
          if (ts.isJsxElement(node) && node.openingElement.tagName.getText(source) === 'Panel' && /<AdminPageHeader\b/.test(node.getText(source))) errors.push(file + ': page header inside panel');
          ts.forEachChild(node, visit);
        };
        visit(source);
      }
    }
    scan(join(process.cwd(), 'src/app/admin'));
    expect(errors).toEqual([]);
  });
});
