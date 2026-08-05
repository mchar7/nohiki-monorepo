/// <reference types="vitest" />

import { readFileSync } from 'node:fs';
import { availableParallelism } from 'node:os';
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

function positiveInt(raw: string | undefined): number | undefined {
  const value = Number.parseInt(raw ?? '', 10);
  return Number.isSafeInteger(value) && value > 0 ? value : undefined;
}

function readOrUndefined(path: string): string | undefined {
  try {
    return readFileSync(path, 'utf8');
  } catch {
    return undefined;
  }
}

/**
 * This process's OWN cgroup v2 `memory.max`, or undefined when it declares none.
 *
 * Deliberately not a walk up the chain, which is what `scripts/dev/test-run.sh` does for
 * `cpu.max` and what this first did. A quota anywhere above you throttles you, so walking is
 * right for `cpu.max`; a memory fence on an enclosing slice is somebody else's runaway guard
 * and says nothing about this process's share of the machine. Measured 2026-08-05: walking the
 * chain found a `memory.max` on an enclosing systemd slice that had nothing to do with this
 * process's share, and cut a local run from 19 workers to 6 for no reason a developer could see.
 *
 * A container's own fence lands on its own cgroup, which is the leaf here under the private
 * cgroup namespace containers get on cgroup v2 (`/proc/self/cgroup` reads `0::/`), so the leaf
 * is both narrower and more correct. The bare-mount fallback covers a host cgroup namespace,
 * where the leaf path is not mounted at the path it names.
 */
function cgroupMemoryLimitBytes(): number | undefined {
  const own =
    readOrUndefined('/proc/self/cgroup')
      ?.split('\n')
      .find((line) => line.startsWith('0::'))
      ?.slice(3)
      .trim() ?? '';
  return (
    positiveInt(readOrUndefined(`/sys/fs/cgroup${own}/memory.max`)) ??
    positiveInt(readOrUndefined('/sys/fs/cgroup/memory.max'))
  );
}

function hostMemoryTotalBytes(): number | undefined {
  const kib = positiveInt(
    readOrUndefined('/proc/meminfo')
      ?.split('\n')
      .find((line) => line.startsWith('MemTotal:'))
      ?.split(/\s+/)[1],
  );
  return kib === undefined ? undefined : kib * 1024;
}

/**
 * Worker count for one test run, as a share of the host this process is actually on.
 *
 * Exported for `scripts/worker-bound.test.mjs`, which pins the host shapes this has to stay
 * correct on. Pure: every environment read happens in the callers above.
 *
 * The share is the container's own memory fence over the host's total memory. That is the only
 * declaration of "how much of this machine is mine" that a container can actually read, and it
 * costs nothing to be wrong about on a host that declares none.
 */
export function resolveMaxWorkers(
  visibleCpus: number,
  memoryLimitBytes: number | undefined,
  hostMemoryBytes: number | undefined,
): number {
  const share =
    memoryLimitBytes !== undefined && hostMemoryBytes !== undefined && memoryLimitBytes < hostMemoryBytes
      ? memoryLimitBytes / hostMemoryBytes
      : 1;
  // One main thread plus the workers, so a slot never claims more of the host than its share.
  return Math.max(1, Math.floor(share * visibleCpus) - 1);
}

// Concurrent test slots can share one host that fences their memory but not their CPU: no
// cpuset, no `cpu.max`, only a per-container memory limit. Node takes its worker count from
// scheduler affinity via libuv's `uv_available_parallelism()` and never from a cgroup CPU
// quota, so a slot in that shape sizes its pool against every thread on the host and concurrent
// slots oversubscribe it once per slot. `maxWorkers` here used to be bounded only when
// NOHIKI_GATE_CPUS was set, which only the pre-push gate does, so that was every other lane.
//
// A container cannot see its siblings, so the number of slots is not derivable from inside one.
// Its own memory fence is, so the bound is that fence as a share of the host: a slot fenced to
// half the host's memory takes half the threads it can see. No slot count, no host names, no
// out-of-band configuration and no coefficient to go stale, and a host that fences nothing
// keeps every thread it can see, so unfenced runners and developer machines are untouched.
//
// It reproduces whatever overcommit the memory fences already declare rather than targeting
// none, because removing an overcommit is a provisioning decision and not this file's to make.
const maxWorkers = resolveMaxWorkers(
  positiveInt(process.env.NOHIKI_GATE_CPUS) ?? availableParallelism(),
  cgroupMemoryLimitBytes(),
  hostMemoryTotalBytes(),
);

export default defineConfig({
  envDir: false,
  plugins: [rejectUnresolvedTestMocks(), react()],
  test: {
    execArgv: ['--no-experimental-webstorage'],
    globals: true,
    // Threads measured 7.6% faster than Vitest's default forks pool on two CPUs.
    pool: 'threads',
    maxWorkers,
    exclude: ['**/node_modules/**', '**/e2e/**'],
    projects: [
      {
        extends: true,
        test: {
          name: 'node',
          environment: 'node',
          include: ['scripts/**/*.test.mjs', 'src/**/*.test.ts'],
          exclude: domTypeScriptTests,
          setupFiles: ['./src/test/network-guard.ts'],
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
