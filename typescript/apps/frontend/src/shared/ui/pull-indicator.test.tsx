import { render } from '@testing-library/react';
import { describe, expect } from 'vitest';
import { PULL_THRESHOLD_PX } from '@/shared/lib/index.ts';
import { PullIndicator } from './pull-indicator.tsx';

const HALF_THRESHOLD: number = PULL_THRESHOLD_PX / 2;
const EXPECTED_HALF_OPACITY: number = 0.5;
const OPACITY_PRECISION_DIGITS: number = 1;

describe('PullIndicator', () => {
  test('renders nothing when pullDistance is 0 and not refreshing', () => {
    const { container } = render(<PullIndicator pullDistance={0} isRefreshing={false} />);
    expect(container.firstChild).toBeNull();
  });

  test('renders icon when pullDistance > 0', () => {
    const { container } = render(
      <PullIndicator pullDistance={HALF_THRESHOLD} isRefreshing={false} />,
    );
    expect(container.querySelector('svg')).toBeInTheDocument();
  });

  test('shows proportional opacity at half threshold', () => {
    const { container } = render(
      <PullIndicator pullDistance={HALF_THRESHOLD} isRefreshing={false} />,
    );
    const svg = container.querySelector('svg');
    expect(svg).toBeTruthy();
    const opacity = Number(svg?.style.opacity);
    expect(opacity).toBeCloseTo(EXPECTED_HALF_OPACITY, OPACITY_PRECISION_DIGITS);
  });

  test('caps opacity at 1 when pullDistance exceeds threshold', () => {
    const { container } = render(
      <PullIndicator pullDistance={PULL_THRESHOLD_PX * 2} isRefreshing={false} />,
    );
    const svg = container.querySelector('svg');
    const opacity = Number(svg?.style.opacity);
    expect(opacity).toBe(1);
  });

  test('applies rotation proportional to pull distance', () => {
    const FULL_ROTATION_DEG = 360;
    const { container } = render(
      <PullIndicator pullDistance={HALF_THRESHOLD} isRefreshing={false} />,
    );
    const svg = container.querySelector('svg');
    const expectedDeg = (HALF_THRESHOLD / PULL_THRESHOLD_PX) * FULL_ROTATION_DEG;
    expect(svg?.style.transform).toBe(`rotate(${String(expectedDeg)}deg)`);
  });

  test('shows spinning animation when refreshing', () => {
    const { container } = render(<PullIndicator pullDistance={0} isRefreshing={true} />);
    const svg = container.querySelector('svg');
    expect(svg?.classList.contains('animate-spin')).toBe(true);
  });

  test('has aria-hidden on the wrapper', () => {
    const { container } = render(
      <PullIndicator pullDistance={HALF_THRESHOLD} isRefreshing={false} />,
    );
    expect(container.firstElementChild?.getAttribute('aria-hidden')).toBe('true');
  });
});
