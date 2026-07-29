/// <reference types="vitest" />

import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';
import type { Plugin } from 'vite';

type AstNode = Record<string, unknown> & { type: string };

function isAstNode(value: unknown): value is AstNode {
  return typeof value === 'object' && value !== null && 'type' in value && typeof value.type === 'string';
}

function visitAst(value: unknown, visit: (node: AstNode) => void): void {
  if (Array.isArray(value)) {
    for (const item of value) {
      visitAst(item, visit);
    }
    return;
  }
  if (!isAstNode(value)) {
    return;
  }
  visit(value);
  for (const child of Object.values(value)) {
    visitAst(child, visit);
  }
}

function mockSpecifier(node: AstNode): string | null | undefined {
  if (node.type !== 'CallExpression' || !isAstNode(node.callee)) {
    return;
  }
  const { callee } = node;
  if (
    callee.type !== 'MemberExpression' ||
    !isAstNode(callee.object) ||
    callee.object.type !== 'Identifier' ||
    callee.object.name !== 'vi' ||
    !isAstNode(callee.property) ||
    callee.property.type !== 'Identifier' ||
    (callee.property.name !== 'mock' && callee.property.name !== 'doMock')
  ) {
    return;
  }
  if (!Array.isArray(node.arguments) || !isAstNode(node.arguments[0])) {
    return null;
  }
  const argument = node.arguments[0];
  if (argument.type === 'Literal' && typeof argument.value === 'string') {
    return argument.value;
  }
  if (
    argument.type === 'ImportExpression' &&
    isAstNode(argument.source) &&
    argument.source.type === 'Literal' &&
    typeof argument.source.value === 'string'
  ) {
    return argument.source.value;
  }
  return null;
}

function rejectUnresolvedTestMocks(): Plugin {
  return {
    name: 'reject-unresolved-test-mocks',
    enforce: 'pre',
    async transform(code, id) {
      if (!/\bvi\s*\.\s*(?:mock|doMock)\s*\(/u.test(code)) {
        return;
      }
      const specifiers: string[] = [];
      const language = id.endsWith('.tsx')
        ? 'tsx'
        : id.endsWith('.ts')
          ? 'ts'
          : id.endsWith('.jsx')
            ? 'jsx'
            : 'js';
      visitAst(this.parse(code, { lang: language }), (node) => {
        const specifier = mockSpecifier(node);
        if (specifier === null) {
          this.error(`vi.mock()/vi.doMock() requires a static module specifier in "${id}"`);
        }
        if (specifier !== undefined) {
          specifiers.push(specifier);
        }
      });
      await Promise.all(
        specifiers.map(async (specifier) => {
          if ((await this.resolve(specifier, id, { skipSelf: true })) === null) {
            this.error(`Cannot resolve mocked module "${specifier}" from "${id}"`);
          }
        }),
      );
    },
  };
}

const domTypeScriptTests = [
  'src/**/use*.test.ts',
  'src/entities/document/api/awaitDocumentReady.test.ts',
  'src/features/attachments/lib/categorize.test.ts',
  'src/features/omakase/document-builder/lib/storage.test.ts',
  'src/shared/api/auth-sync.test.ts',
  'src/shared/api/skills.test.ts',
  'src/shared/config/features.test.ts',
  'src/shared/lib/persistence/index.test.ts',
  'src/shared/lib/theme/theme.test.ts',
  'src/shared/lib/utils/cache.test.ts',
  'src/shared/model/**/*.test.ts',
];

const jsdomTypeScriptTests = ['src/shared/lib/utils/cache.test.ts'];

const jsdomUiTests = [
  // Happy DOM lacks these storage, accessible-name, and iframe-loading semantics.
  'src/features/omakase/document-builder/ui/PreviewPane/PreviewRenderer.test.tsx',
  'src/pages/dashboard/lib/useLastVisit.test.tsx',
  'src/shared/ui/skill-input/SkillInput.test.tsx',
  // axe-core supports jsdom only; Happy DOM also triggers network loads from axe's iframes.
  'src/features/job-matching/ui/ScoreBreakdownCard.test.tsx',
  'src/shared/ui/PageHeader.test.tsx',
  'src/shared/ui/button.test.tsx',
  'src/shared/ui/dialog.test.tsx',
  'src/shared/ui/feature-error-boundary.test.tsx',
  'src/shared/ui/input.test.tsx',
  'src/shared/ui/list-pagination.test.tsx',
  'src/shared/ui/select.test.tsx',
  'src/shared/ui/sort-select.test.tsx',
  'src/widgets/layout/ui/BottomNav.test.tsx',
];

export default defineConfig({
  plugins: [rejectUnresolvedTestMocks(), react()],
  test: {
    execArgv: ['--no-experimental-webstorage'],
    globals: true,
    // Threads measured 7.6% faster than Vitest's default forks pool on two CPUs.
    pool: 'threads',
    exclude: ['**/node_modules/**', '**/e2e/**'],
    projects: [
      {
        extends: true,
        test: {
          name: 'node',
          environment: 'node',
          include: ['scripts/**/*.test.mjs', 'src/**/*.test.ts'],
          exclude: domTypeScriptTests,
          setupFiles: [],
        },
      },
      {
        extends: true,
        test: {
          name: 'dom',
          environment: 'happy-dom',
          include: domTypeScriptTests,
          exclude: jsdomTypeScriptTests,
          setupFiles: ['./src/test/setup.ts'],
        },
      },
      {
        extends: true,
        test: {
          name: 'ui',
          environment: 'happy-dom',
          include: ['src/**/*.test.tsx'],
          exclude: jsdomUiTests,
          setupFiles: ['./src/test/setup.ts', './src/test/i18n-setup.ts'],
        },
      },
      {
        extends: true,
        test: {
          name: 'dom-jsdom',
          environment: 'jsdom',
          include: jsdomTypeScriptTests,
          setupFiles: ['./src/test/setup.ts'],
        },
      },
      {
        extends: true,
        test: {
          name: 'ui-jsdom',
          environment: 'jsdom',
          include: jsdomUiTests,
          setupFiles: ['./src/test/setup.ts', './src/test/i18n-setup.ts'],
        },
      },
    ],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'node_modules/',
        'src/test/',
        '**/*.d.ts',
        '**/*.config.*',
        '**/*.test.{ts,tsx}',
        'dist/',
        '**/index.ts',
        // shadcn/ui components - external boilerplate wrappers around Radix
        'src/shared/ui/alert-dialog.tsx',
        'src/shared/ui/alert.tsx',
        'src/shared/ui/avatar.tsx',
        'src/shared/ui/badge.tsx',
        'src/shared/ui/breadcrumb.tsx',
        'src/shared/ui/button.tsx',
        'src/shared/ui/card.tsx',
        'src/shared/ui/checkbox.tsx',
        'src/shared/ui/collapsible.tsx',
        'src/shared/ui/dialog.tsx',
        'src/shared/ui/dropdown-menu.tsx',
        'src/shared/ui/input.tsx',
        'src/shared/ui/label.tsx',
        'src/shared/ui/pagination.tsx',
        'src/shared/ui/resizable.tsx',
        'src/shared/ui/select.tsx',
        'src/shared/ui/separator.tsx',
        'src/shared/ui/sheet.tsx',
        'src/shared/ui/sidebar.tsx',
        'src/shared/ui/skeleton.tsx',
        'src/shared/ui/sonner.tsx',
        'src/shared/ui/textarea.tsx',
        'src/shared/ui/tooltip.tsx',
      ],
    },
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      '@app': fileURLToPath(new URL('./src/app', import.meta.url)),
      '@pages': fileURLToPath(new URL('./src/pages', import.meta.url)),
      '@widgets': fileURLToPath(new URL('./src/widgets', import.meta.url)),
      '@features': fileURLToPath(new URL('./src/features', import.meta.url)),
      '@shared': fileURLToPath(new URL('./src/shared', import.meta.url)),
    },
  },
});
