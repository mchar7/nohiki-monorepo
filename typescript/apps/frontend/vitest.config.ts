/// <reference types="vitest" />

import babel from '@rolldown/plugin-babel';
import { fileURLToPath } from 'node:url';
import react, { reactCompilerPreset } from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [
    react(),
    babel({ presets: [reactCompilerPreset()] }),
  ],
  test: {
    execArgv: ['--no-experimental-webstorage'],
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts', './src/test/axe-setup.ts'],
    exclude: ['**/node_modules/**', '**/e2e/**'],
    css: true,
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
