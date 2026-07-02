import type { KnipConfig } from 'knip';

const config: KnipConfig = {
  $schema: 'https://unpkg.com/knip@5/schema.json',

  project: ['src/**/*.{ts,tsx,css}', 'e2e/**/*.ts'],

  ignore: [
    // Auto-generated OpenAPI schema types - not directly imported at runtime
    'src/api/schema.d.ts',
    'src/shared/api/types.gen.ts',
    // Thin OpenAPI aliases derived from generated schema output. Application code imports
    // only the aliases it needs through '@/shared/api'; unused schema aliases are not app dead-code.
    'src/shared/api/types.ts',
  ],

  ignoreDependencies: [
    '@feature-sliced/steiger-plugin',
    'steiger',
  ],

  ignoreBinaries: [
    // `lint:ast` intentionally resolves @ast-grep/cli via `npx --package` so
    // `sg` is not a local binary dependency.
    'sg',
  ],

  ignoreFiles: [
    // Reusable Playwright page objects/helpers for flows that are not exercised
    // by every current journey spec but map to active product routes.
    'e2e/pages/matches-detail.page.ts',
    'e2e/pages/template-gallery.page.ts',
    'e2e/utils/document-helpers.ts',
    // Intentional shadcn/design-system primitives kept for future chart and
    // pagination composition. Removing them would force ad-hoc reintroduction.
    'src/shared/ui/chart-legend.tsx',
    'src/shared/ui/pagination.tsx',
  ],

  ignoreIssues: {
    // E2E page object retained with document-helpers for active /documents/generate flows.
    'e2e/pages/generate-wizard.page.ts': ['exports'],
    'e2e/pages/index.ts': ['exports'],

    // Omakase template API wrappers map to active BFF endpoints and expected template authoring flows.
    'src/features/omakase/document-builder/api/hooks.ts': ['exports'],

    // shadcn/Radix component modules intentionally expose complete slot families;
    // the individual unused slots below are standard composition points, not stale app code.
    'src/shared/ui/avatar.tsx': ['exports'],
    'src/shared/ui/chart.tsx': ['exports'],
    'src/shared/ui/command.tsx': ['exports'],
    'src/shared/ui/dialog.tsx': ['exports'],
    'src/shared/ui/dropdown-menu.tsx': ['exports'],
    'src/shared/ui/popover.tsx': ['exports'],
    'src/shared/ui/select.tsx': ['exports'],
    'src/shared/ui/sheet.tsx': ['exports'],
    'src/shared/ui/sidebar.tsx': ['exports'],
    'src/shared/ui/sidebar-menu.tsx': ['exports'],
    'src/shared/ui/sidebar-sections.tsx': ['exports'],
    'src/shared/ui/skeleton-layouts.tsx': ['exports'],
    'src/shared/ui/table.tsx': ['exports'],
    'src/shared/ui/section-icon.tsx': ['exports'],
  },

  paths: {
    '@/*': ['src/*'],
  },

  vite: {
    entry: ['vite.config.ts'],
  },

  vitest: {
    entry: [
      'vitest.config.ts',
      'src/test/vitest-axe.d.ts',
      'src/**/*.test.{ts,tsx}',
      'src/**/*.spec.{ts,tsx}',
    ],
  },

  playwright: {
    entry: ['e2e/**/*.spec.ts', 'e2e/global-setup.ts', 'e2e/playwright.config.ts'],
  },

  rules: {
    binaries: 'error',
    classMembers: 'error',
    dependencies: 'error',
    devDependencies: 'error',
    duplicates: 'error',
    enumMembers: 'error',
    exports: 'error',
    files: 'error',
    nsExports: 'error',
    nsTypes: 'error',
    types: 'error',
    unlisted: 'error',
    unresolved: 'error',
  },
};

export default config;
