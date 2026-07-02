import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from '@tanstack/react-router';
import React from 'react';
import ReactDOM from 'react-dom/client';
import { I18nextProvider } from 'react-i18next';
import { LocalStoreInitializer } from './app/LocalStoreInitializer.tsx';
import './app/styles/index.css';
import { type AppRouter, createAppRouter } from '@/app/router.ts';
import { queryClient, setTokenRefreshQueryClient } from '@/shared/api/index.ts';
import { ConnectivityProvider } from '@/shared/lib/contexts/index.ts';
import { i18n } from '@/shared/lib/i18n.ts';
import { ThemeProvider } from '@/shared/lib/theme/theme.ts';

setTokenRefreshQueryClient(queryClient);

const router: AppRouter = createAppRouter(queryClient);

const rootElement: HTMLElement | null = document.getElementById('root');
if (!rootElement) {
  throw new Error('Root element not found');
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider attribute="class" defaultTheme="system" storageKey="vite-ui-theme">
          <LocalStoreInitializer>
            <ConnectivityProvider>
              <RouterProvider router={router} />
            </ConnectivityProvider>
          </LocalStoreInitializer>
        </ThemeProvider>
      </QueryClientProvider>
    </I18nextProvider>
  </React.StrictMode>,
);
