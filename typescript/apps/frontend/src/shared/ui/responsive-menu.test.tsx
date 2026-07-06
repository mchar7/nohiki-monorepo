import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, vi } from 'vitest';
import { ResponsiveMenu, ResponsiveMenuItem, ResponsiveMenuSeparator } from './responsive-menu.tsx';

const mockUseIsMobileLayout = vi.fn<() => boolean>().mockReturnValue(false);

vi.mock('@/shared/lib/index.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/index.ts')>();
  return {
    ...actual,
    useIsMobileLayout: () => mockUseIsMobileLayout(),
  };
});

afterEach(() => {
  vi.clearAllMocks();
});

const TRIGGER_LABEL = 'Open menu';
const SHEET_TITLE = 'Actions';
const ITEM_TEXT = 'Delete item';

function renderMenu(
  isMobile: boolean,
  open = false,
  onOpenChange = vi.fn(),
): ReturnType<typeof vi.fn> {
  mockUseIsMobileLayout.mockReturnValue(isMobile);
  const handleClick = vi.fn();
  render(
    <ResponsiveMenu
      open={open}
      onOpenChange={onOpenChange}
      title={SHEET_TITLE}
      trigger={
        <button type="button" aria-label={TRIGGER_LABEL}>
          Trigger
        </button>
      }
    >
      <ResponsiveMenuItem onClick={handleClick}>{ITEM_TEXT}</ResponsiveMenuItem>
      <ResponsiveMenuSeparator />
    </ResponsiveMenu>,
  );
  return handleClick;
}

describe('ResponsiveMenu - desktop', () => {
  test('renders the trigger button', () => {
    renderMenu(false);
    expect(screen.getByRole('button', { name: TRIGGER_LABEL })).toBeInTheDocument();
  });

  test('wraps trigger in DropdownMenuTrigger', () => {
    renderMenu(false);
    expect(document.querySelector('[data-slot="dropdown-menu-trigger"]')).toBeInTheDocument();
  });

  test('shows items as DropdownMenuItem when open', () => {
    renderMenu(false, true);
    expect(screen.getByText(ITEM_TEXT)).toBeInTheDocument();
  });

  test('does not render BottomSheet', () => {
    renderMenu(false);
    expect(screen.queryByText(SHEET_TITLE)).not.toBeInTheDocument();
  });
});

describe('ResponsiveMenu - mobile', () => {
  test('renders the trigger button', () => {
    renderMenu(true);
    expect(screen.getByRole('button', { name: TRIGGER_LABEL })).toBeInTheDocument();
  });

  test('does not render DropdownMenu wrapper', () => {
    renderMenu(true);
    expect(document.querySelector('[data-slot="dropdown-menu"]')).not.toBeInTheDocument();
  });

  test('shows items as full-width buttons when open', () => {
    renderMenu(true, true);
    expect(screen.getByText(ITEM_TEXT)).toBeInTheDocument();
  });

  test('shows sheet title when open', () => {
    renderMenu(true, true);
    expect(screen.getByText(SHEET_TITLE)).toBeInTheDocument();
  });

  test('calls onOpenChange(true) when trigger is clicked', async () => {
    const onOpenChange = vi.fn();
    renderMenu(true, false, onOpenChange);
    await userEvent.click(screen.getByRole('button', { name: TRIGGER_LABEL }));
    expect(onOpenChange).toHaveBeenCalledWith(true);
  });
});

describe('ResponsiveMenuItem', () => {
  test('calls onClick handler when clicked on desktop', async () => {
    const handleClick = renderMenu(false, true);
    await userEvent.click(screen.getByText(ITEM_TEXT));
    expect(handleClick).toHaveBeenCalledOnce();
  });

  test('renders with destructive variant styling on mobile', () => {
    mockUseIsMobileLayout.mockReturnValue(true);
    const handleClick = vi.fn();
    render(
      <ResponsiveMenu
        open={true}
        onOpenChange={vi.fn()}
        title="Test"
        trigger={<button type="button">T</button>}
      >
        <ResponsiveMenuItem onClick={handleClick} variant="destructive">
          Delete
        </ResponsiveMenuItem>
      </ResponsiveMenu>,
    );
    const btn = screen.getByText('Delete').closest('button');
    expect(btn?.className).toContain('text-destructive');
  });

  test('renders with disabled state', () => {
    mockUseIsMobileLayout.mockReturnValue(false);
    const handleClick = vi.fn();
    render(
      <ResponsiveMenu
        open={true}
        onOpenChange={vi.fn()}
        title="Test"
        trigger={<button type="button">T</button>}
      >
        <ResponsiveMenuItem onClick={handleClick} disabled={true}>
          Disabled Action
        </ResponsiveMenuItem>
      </ResponsiveMenu>,
    );
    expect(screen.getByText('Disabled Action')).toBeInTheDocument();
  });
});
