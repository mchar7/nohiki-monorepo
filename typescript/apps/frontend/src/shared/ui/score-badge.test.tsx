import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { ScoreBadge } from './score-badge.tsx';

describe('ScoreBadge', () => {
  test('renders fit scores as points out of 100', () => {
    render(<ScoreBadge score={85} />);

    expect(screen.getByText('85 / 100')).toBeInTheDocument();
    expect(screen.queryByText('85%')).not.toBeInTheDocument();
  });

  test('rounds fractional fit scores before rendering', () => {
    render(<ScoreBadge score={84.6} />);

    expect(screen.getByText('85 / 100')).toBeInTheDocument();
  });
});
