import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { parse } from '@babel/parser';

test('workspace consumes canonical controls instead of raw primitives', () => {
  const source = parse(readFileSync(new URL('../src/main.tsx', import.meta.url), 'utf8'), { sourceType: 'module', plugins: ['typescript', 'jsx'] });
  const violations = [];
  function visit(node) {
    if (node.type === 'JSXOpeningElement') {
      const name = node.name.name;
      if (['button', 'input', 'select', 'textarea'].includes(name)) violations.push(name);
    }
    if (node.type === 'ImportDeclaration') {
      const path = node.source.value;
      if (path.includes('/components/ui') || path.startsWith('@radix-ui/')) violations.push(path);
    }
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) value.forEach(child => { if (child?.type) visit(child); });
      else if (value?.type) visit(value);
    }
  }
  visit(source);
  assert.deepEqual(violations, []);
});

test('feature stylesheet contains only design-system and framework imports', () => {
  const css = readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8');
  assert.equal(css.replace(/^@import .*;$/gm, '').trim(), '');
});
