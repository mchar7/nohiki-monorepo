import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { JSX } from 'react';
import { describe, expect, vi } from 'vitest';
import { axe } from 'vitest-axe';
import '@/test/axe-setup.ts';
import { ListPagination } from './list-pagination.tsx';

const PAGE_SIZE = 20;
const TOTAL_ITEMS = 55;
const FIRST_PAGE = 1;
const SECOND_PAGE = 2;
const LAST_PAGE = 3;

const RE_PREVIOUS = /previous/iu;
const RE_NEXT = /next/iu;
const RE_SHOWING_RANGE = /21.+40.+55/u;
const RE_PAGE_INDICATOR = /2.+3/u;

function setup(
  page: number,
  total: number,
  onPageChange = vi.fn(),
): { onPageChange: ReturnType<typeof vi.fn> } {
  render(
    (
      <ListPagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={onPageChange} />
    ) as JSX.Element,
  );
  return { onPageChange };
}

describe('ListPagination - rendering', () => {
  test('renders showing text with formatted range', () => {
    setup(SECOND_PAGE, TOTAL_ITEMS);
    expect(screen.getByText(RE_SHOWING_RANGE)).toBeInTheDocument();
  });

  test('renders page indicator', () => {
    setup(SECOND_PAGE, TOTAL_ITEMS);
    expect(screen.getByText(RE_PAGE_INDICATOR)).toBeInTheDocument();
  });

  test('returns null when total fits within a single page', () => {
    const { container } = render(
      (
        <ListPagination
          page={FIRST_PAGE}
          pageSize={PAGE_SIZE}
          total={PAGE_SIZE}
          onPageChange={vi.fn()}
        />
      ) as JSX.Element,
    );
    expect(container).toBeEmptyDOMElement();
  });

  test('returns null when total is zero', () => {
    const { container } = render(
      (
        <ListPagination page={FIRST_PAGE} pageSize={PAGE_SIZE} total={0} onPageChange={vi.fn()} />
      ) as JSX.Element,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe('ListPagination - button states', () => {
  test('disables the Previous button on the first page', () => {
    setup(FIRST_PAGE, TOTAL_ITEMS);
    expect(screen.getByRole('button', { name: RE_PREVIOUS })).toBeDisabled();
  });

  test('enables the Previous button on subsequent pages', () => {
    setup(SECOND_PAGE, TOTAL_ITEMS);
    expect(screen.getByRole('button', { name: RE_PREVIOUS })).toBeEnabled();
  });

  test('disables the Next button on the last page', () => {
    setup(LAST_PAGE, TOTAL_ITEMS);
    expect(screen.getByRole('button', { name: RE_NEXT })).toBeDisabled();
  });

  test('enables the Next button on earlier pages', () => {
    setup(SECOND_PAGE, TOTAL_ITEMS);
    expect(screen.getByRole('button', { name: RE_NEXT })).toBeEnabled();
  });
});

describe('ListPagination - interactions', () => {
  test('calls onPageChange with decremented page when Previous is clicked', async () => {
    const user = userEvent.setup();
    const { onPageChange } = setup(SECOND_PAGE, TOTAL_ITEMS);
    await user.click(screen.getByRole('button', { name: RE_PREVIOUS }));
    expect(onPageChange).toHaveBeenCalledWith(FIRST_PAGE);
  });

  test('calls onPageChange with incremented page when Next is clicked', async () => {
    const user = userEvent.setup();
    const { onPageChange } = setup(SECOND_PAGE, TOTAL_ITEMS);
    await user.click(screen.getByRole('button', { name: RE_NEXT }));
    expect(onPageChange).toHaveBeenCalledWith(LAST_PAGE);
  });
});

describe('ListPagination - accessibility', () => {
  test('Previous button has an aria-label', () => {
    setup(SECOND_PAGE, TOTAL_ITEMS);
    expect(screen.getByRole('button', { name: RE_PREVIOUS })).toHaveAttribute('aria-label');
  });

  test('Next button has an aria-label', () => {
    setup(SECOND_PAGE, TOTAL_ITEMS);
    expect(screen.getByRole('button', { name: RE_NEXT })).toHaveAttribute('aria-label');
  });
});

describe('ListPagination - axe', () => {
  test('has no accessibility violations', async () => {
    const { container } = render(
      (
        <ListPagination
          page={SECOND_PAGE}
          pageSize={PAGE_SIZE}
          total={TOTAL_ITEMS}
          onPageChange={vi.fn()}
        />
      ) as JSX.Element,
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
