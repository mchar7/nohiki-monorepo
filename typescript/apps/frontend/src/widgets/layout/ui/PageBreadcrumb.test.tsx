import { useMatches } from '@tanstack/react-router';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, vi } from 'vitest';
import { type BreadcrumbRouteMatch, makeBreadcrumbMatches, nonNull } from '@/shared/test-utils';
import { PageBreadcrumb } from './PageBreadcrumb.tsx';

// Mock useIsMobileLayout
let mockIsMobile = false;
vi.mock('@/shared/lib/index.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/index.ts')>();
  return {
    ...actual,
    useIsMobileLayout: () => mockIsMobile,
  };
});

// Mock TanStack Router's useMatches
vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>();
  return {
    ...actual,
    useMatches: vi.fn(),
  };
});

afterEach(() => {
  vi.clearAllMocks();
  mockIsMobile = false;
});

const mockMatches: readonly BreadcrumbRouteMatch[] = [
  {
    pathname: '/dashboard',
    staticData: { breadcrumb: 'navigation:sidebar.dashboard' },
  },
  {
    pathname: '/jobs',
    staticData: { breadcrumb: 'navigation:sidebar.jobs.title' },
  },
  {
    pathname: '/jobs/123',
    staticData: { breadcrumb: 'navigation:sidebar.jobs.matches' },
  },
];

describe('PageBreadcrumb', () => {
  describe('Desktop rendering', () => {
    test('renders full breadcrumb trail with all items on desktop', () => {
      mockIsMobile = false;
      vi.mocked(useMatches).mockReturnValue(makeBreadcrumbMatches(mockMatches));

      render(<PageBreadcrumb />);

      // Desktop should show all items: App Name + 3 route items = 4 total
      const breadcrumbItems = screen.getAllByRole('listitem');
      expect(breadcrumbItems).toHaveLength(4);

      // Verify all breadcrumb items are rendered
      expect(screen.getByText('Nohiki')).toBeInTheDocument();
      expect(screen.getByText('Dashboard')).toBeInTheDocument();
      expect(screen.getByText('Jobs')).toBeInTheDocument();
      expect(screen.getByText('My Matches')).toBeInTheDocument();

      // Last item should be a BreadcrumbPage (not a link)
      const lastItem = nonNull(breadcrumbItems[3], 'expected 4 breadcrumb items');
      expect(within(lastItem).queryByRole('link')).not.toBeInTheDocument();
      expect(within(lastItem).getByText('My Matches')).toBeInTheDocument();
    });

    test('renders breadcrumb with correct navigation structure', () => {
      mockIsMobile = false;
      vi.mocked(useMatches).mockReturnValue(makeBreadcrumbMatches(mockMatches));

      render(<PageBreadcrumb />);

      // Verify navigation element with breadcrumb role
      expect(screen.getByRole('navigation', { name: /breadcrumb/iu })).toBeInTheDocument();

      // Verify list structure
      const list = screen.getByRole('list');
      expect(list).toBeInTheDocument();

      // Verify links are present for non-active items
      const links = screen.getAllByRole('link');
      expect(links.length).toBeGreaterThan(0);
    });
  });

  describe('Mobile rendering', () => {
    test('truncates to last item and shows ellipsis when threshold exceeded on mobile', () => {
      mockIsMobile = true;
      // Threshold is 3 items. Total items will be App Name + 3 matches = 4 items.
      vi.mocked(useMatches).mockReturnValue(makeBreadcrumbMatches(mockMatches));

      render(<PageBreadcrumb />);

      // Mobile rendering for 3+ items should show ellipsis button
      const ellipsisButton = screen.getByRole('button');
      expect(ellipsisButton).toBeInTheDocument();

      // Last item should be visible
      expect(screen.getByText('My Matches')).toBeInTheDocument();
    });

    test('shows collapsed breadcrumb items in BottomSheet when ellipsis is clicked', async () => {
      const user = userEvent.setup();
      mockIsMobile = true;
      vi.mocked(useMatches).mockReturnValue(makeBreadcrumbMatches(mockMatches));

      render(<PageBreadcrumb />);

      // Click ellipsis button to open BottomSheet
      const ellipsisButton = screen.getByRole('button');
      await user.click(ellipsisButton);

      // BottomSheet title should be visible
      expect(screen.getByText('More pages')).toBeInTheDocument();

      // Collapsed items (Dashboard, Jobs) should be in the BottomSheet as navigation buttons
      const dashboardLink = screen.getByRole('link', { name: 'Dashboard' });
      const jobsLink = screen.getByRole('link', { name: 'Jobs' });

      expect(dashboardLink).toBeInTheDocument();
      expect(jobsLink).toBeInTheDocument();
      expect(dashboardLink).toHaveAttribute('href', '/dashboard');
      expect(jobsLink).toHaveAttribute('href', '/jobs');
    });
  });

  describe('Accessibility', () => {
    test('renders breadcrumb items with correct ARIA labels and roles', () => {
      mockIsMobile = false;
      vi.mocked(useMatches).mockReturnValue(makeBreadcrumbMatches(mockMatches));

      render(<PageBreadcrumb />);

      // Navigation element should have breadcrumb role
      const nav = screen.getByRole('navigation', { name: /breadcrumb/iu });
      expect(nav).toBeInTheDocument();

      // List should be present
      const list = screen.getByRole('list');
      expect(list).toBeInTheDocument();

      // All list items should be present
      const listItems = screen.getAllByRole('listitem');
      expect(listItems.length).toBeGreaterThan(0);
    });

    test('marks last breadcrumb item as current page (not a link)', () => {
      mockIsMobile = false;
      vi.mocked(useMatches).mockReturnValue(makeBreadcrumbMatches(mockMatches));

      render(<PageBreadcrumb />);

      // Last item should be a BreadcrumbPage (aria-current="page")
      const breadcrumbItems = screen.getAllByRole('listitem');
      const lastItem = nonNull(breadcrumbItems.at(-1), 'expected at least one breadcrumb item');

      // Last item should not contain a link
      expect(within(lastItem).queryByRole('link')).not.toBeInTheDocument();
      // Last item should contain the current page text
      expect(within(lastItem).getByText('My Matches')).toBeInTheDocument();
    });
  });

  describe('Edge cases', () => {
    test('renders correctly with no route breadcrumbs (only app name)', () => {
      mockIsMobile = false;
      vi.mocked(useMatches).mockReturnValue(makeBreadcrumbMatches([]));

      render(<PageBreadcrumb />);

      // Should render only the app name when no route breadcrumbs available
      const breadcrumbItems = screen.getAllByRole('listitem');
      expect(breadcrumbItems).toHaveLength(1);
      expect(screen.getByText('Nohiki')).toBeInTheDocument();
    });

    test('renders correctly with single breadcrumb item', () => {
      mockIsMobile = false;
      const [firstMatch] = mockMatches;
      vi.mocked(useMatches).mockReturnValue(
        makeBreadcrumbMatches(firstMatch === undefined ? [] : [firstMatch]),
      );

      render(<PageBreadcrumb />);

      // Should have App Name + 1 route item = 2 items
      const breadcrumbItems = screen.getAllByRole('listitem');
      expect(breadcrumbItems).toHaveLength(2);

      expect(screen.getByText('Nohiki')).toBeInTheDocument();
      expect(screen.getByText('Dashboard')).toBeInTheDocument();
    });
  });
});
