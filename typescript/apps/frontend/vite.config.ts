import babel from '@rolldown/plugin-babel';
import tailwindcss from '@tailwindcss/vite';
import { tanstackRouter } from '@tanstack/router-plugin/vite';
import react, { reactCompilerPreset } from '@vitejs/plugin-react';
import { visualizer } from 'rollup-plugin-visualizer';
import { defineConfig } from 'vite';

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    tanstackRouter({
      target: 'react',
      autoCodeSplitting: true,
      routesDirectory: './src/app/routes',
      generatedRouteTree: './src/routeTree.gen.ts',
      quoteStyle: 'single',
    }),
    react(),
    babel({ presets: [reactCompilerPreset()] }),
    tailwindcss(),
    ...(process.env.ANALYZE === 'true'
      ? [visualizer({ open: true, gzipSize: true, brotliSize: true, filename: 'dist/bundle-analysis.html' })]
      : []),
  ],
  resolve: {
    tsconfigPaths: true,
  },
  build: {
    target: 'esnext',
    rollupOptions: {
      output: {
        // Function form so submodules (e.g. react-dom/client) are matched by package directory.
        manualChunks(id: string): string | undefined {
          if (!id.includes('node_modules')) {
            return undefined;
          }
          if (
            id.includes('/react-dom/') ||
            id.includes('/react/') ||
            id.includes('/scheduler/') ||
            id.includes('/use-sync-external-store/') ||
            id.includes('/@tanstack/react-router/') ||
            id.includes('/@tanstack/router-core/') ||
            id.includes('/@tanstack/react-store/') ||
            id.includes('/@tanstack/store/') ||
            id.includes('/@tanstack/history/')
          ) {
            return 'vendor-react';
          }
          if (id.includes('/zustand/') || id.includes('/@tanstack/react-query/')) {
            return 'vendor-state';
          }
          if (id.includes('/@dnd-kit/')) {
            return 'vendor-dnd';
          }
          if (
            id.includes('/clsx/') ||
            id.includes('/tailwind-merge/') ||
            id.includes('/class-variance-authority/') ||
            id.includes('/nanoid/') ||
            id.includes('/lucide-react/') ||
            id.includes('/sonner/')
          ) {
            return 'vendor-utils';
          }
          // Heavy optional-feature chunks - only loaded on Omakase/Dashboard routes
          if (id.includes('/recharts/')) {
            return 'vendor-recharts';
          }
          if (
            id.includes('/@codemirror/state/') ||
            id.includes('/@codemirror/view/') ||
            id.includes('/@codemirror/language/')
          ) {
            return 'vendor-codemirror-core';
          }
          if (id.includes('/@codemirror/lang-')) {
            return 'vendor-codemirror-lang';
          }
          if (
            id.includes('/@codemirror/autocomplete/') ||
            id.includes('/@codemirror/commands/') ||
            id.includes('/@codemirror/lint/') ||
            id.includes('/@codemirror/search/') ||
            id.includes('/@codemirror/theme-one-dark/')
          ) {
            return 'vendor-codemirror-features';
          }
          if (id.includes('/react-resizable-panels/')) {
            return 'vendor-resizable-panels';
          }
          return undefined;
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      },
    },
  },
});
