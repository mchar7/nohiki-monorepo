import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, vi } from 'vitest';
import { ThemeProvider } from '@/shared/lib/index.ts';
import { wrapWithRouter } from '@/shared/test-utils/index.ts';
import { BaseLayout } from './BaseLayout.tsx';

const BREADCRUMB_RE = /breadcrumb/iu;

vi.mock('@features/account', () => ({
  useAccount: () => ({ data: null }),
}));

// Mock i18n - return the key as the translation
vi.mock('react-i18next', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-i18next')>();
  return {
    ...actual,
    useTranslation: () => ({
      t: (key: string) => {
        const translations: Record<string, string> = {
          appName: 'Nohiki',
          appTagline: 'Your job search, organized.',
          'common:appName': 'Nohiki',
          'modules.platform.title': 'Platform',
          'modules.platform.description': 'Jobs Platform',
          'features.settings': 'Settings',
          'features.accountSettings': 'Account Settings',
        };
        return translations[key] ?? key;
      },
      i18n: { changeLanguage: vi.fn() },
    }),
    Trans: ({ children }: { children: React.ReactNode }) => children,
  };
});

// Mock the sidebar components that have complex state
vi.mock('@/shared/ui/sidebar', async () => {
  const actual = await vi.importActual('@/shared/ui/sidebar');
  return {
    ...actual,
    useSidebar: () => ({ isMobile: false }),
  };
});

const queryClient: QueryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false },
    mutations: { retry: false },
  },
});

async function renderLayout(): Promise<ReturnType<typeof render>> {
  return render(
    await wrapWithRouter(
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <BaseLayout />
        </ThemeProvider>
      </QueryClientProvider>,
    ),
  );
}

describe('BaseLayout', () => {
  test('renders navigation with app title', async () => {
    await renderLayout();
    expect(screen.getAllByText('Nohiki').length).toBeGreaterThan(0);
  });

  test('renders sidebar with navigation structure', async () => {
    await renderLayout();
    expect(screen.getByRole('navigation', { name: BREADCRUMB_RE })).toBeDefined();
  });

  test('renders sidebar content area', async () => {
    await renderLayout();
    const sidebarContent = document.querySelector('[data-sidebar="content"]');
    expect(sidebarContent).toBeDefined();
  });
});
