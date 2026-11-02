import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import ts from 'typescript';
import { expect, it } from 'vitest';

// Panel 是无内边距底板。后台调用方必须显式安排内容留白，或声明
// overflow-hidden / p-0 以交由表格、列表及弹窗的内部区域管理。
it('后台 Panel 必须显式选择留白或满幅布局，避免内容无意贴边', () => {
  const missing: string[] = [];
  function scan(dir: string) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) { scan(path); continue; }
      if (!path.endsWith('.tsx') || path.endsWith('.test.tsx')) continue;
      const source = ts.createSourceFile(path, readFileSync(path, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
      function visit(node: ts.Node) {
        if ((ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) && node.tagName.getText(source) === 'Panel') {
          const attr = node.attributes.properties.find(p => ts.isJsxAttribute(p) && p.name.getText(source) === 'className');
          const classes = attr?.getText(source) ?? '';
          if (!/(?:\bp-[\d[]|\bpx-[\d[]|\bpy-[\d[]|\boverflow-hidden\b)/.test(classes)) {
            missing.push(`${path}:${source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1}`);
          }
        }
        ts.forEachChild(node, visit);
      }
      visit(source);
    }
  }
  scan(join(process.cwd(), 'src/app/admin'));
  expect(missing).toEqual([]);
});
