/// <reference types="vitest" />

import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

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

export default defineConfig({
  plugins: [react()],
  test: {
    execArgv: ['--no-experimental-webstorage'],
    globals: true,
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
          environment: 'jsdom',
          include: domTypeScriptTests,
          setupFiles: ['./src/test/setup.ts'],
        },
      },
      {
        extends: true,
        test: {
          name: 'ui',
          environment: 'jsdom',
          include: ['src/**/*.test.tsx'],
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
