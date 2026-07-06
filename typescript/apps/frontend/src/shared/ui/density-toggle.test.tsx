import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { JSX } from 'react';
import { afterEach, describe, expect } from 'vitest';
import { useAppStore } from '@/shared/model/appStore.ts';
import { DensityToggle } from './density-toggle.tsx';

const DENSITY_OPTION_COUNT = 3;
/** Translated label for compact density (from en/common.json density.compact) */
const RE_COMPACT = /compact/iu;
/** Translated label for spacious density (from en/common.json density.spacious) */
const RE_SPACIOUS = /spacious/iu;
/** Translated label for comfortable density (from en/common.json density.comfortable) */
const RE_COMFORTABLE = /comfortable/iu;

afterEach(() => {
  useAppStore.setState({ density: 'comfortable' });
});

/** Renders DensityToggle; the component reads/writes the store internally. */
function TestDensityToggle({ className }: { className?: string }): JSX.Element {
  return <DensityToggle className={className} />;
}

function setup(className?: string): void {
  render((<TestDensityToggle className={className} />) as JSX.Element);
}

describe('DensityToggle - rendering', () => {
  test('renders without any props', () => {
    setup();
    expect(screen.getByRole('radiogroup', { name: /display density/iu })).toBeInTheDocument();
  });

  test('renders buttons for all three density options', () => {
    setup();
    expect(screen.getAllByRole('radio')).toHaveLength(DENSITY_OPTION_COUNT);
  });

  test('renders a compact, comfortable, and spacious button', () => {
    setup();
    expect(screen.getByRole('radio', { name: RE_COMPACT })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: RE_COMFORTABLE })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: RE_SPACIOUS })).toBeInTheDocument();
  });
});

describe('DensityToggle - store integration', () => {
  test('comfortable button is selected by default', () => {
    setup();
    const comfortableBtn = screen.getByRole('radio', { name: RE_COMFORTABLE });
    // Radix ToggleGroup type="single" marks the selected item with aria-checked="true"
    expect(comfortableBtn).toHaveAttribute('aria-checked', 'true');
  });

  test('updates the store when compact is selected', async () => {
    const user = userEvent.setup();
    setup();
    await user.click(screen.getByRole('radio', { name: RE_COMPACT }));
    expect(useAppStore.getState().density).toBe('compact');
  });

  test('updates the store when spacious is selected', async () => {
    const user = userEvent.setup();
    setup();
    await user.click(screen.getByRole('radio', { name: RE_SPACIOUS }));
    expect(useAppStore.getState().density).toBe('spacious');
  });

  test('accepts an optional className without error', () => {
    setup('ml-2');
    expect(screen.getByRole('radiogroup', { name: /display density/iu })).toHaveClass('ml-2');
  });
});
