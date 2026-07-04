import { render, screen } from '@testing-library/react';
import { describe, expect, vi } from 'vitest';
import type { AuthListingItem } from '../model';
import { AuthListingCard } from './AuthListingCard';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts?.count !== undefined ? `${key}:${opts.count}` : key,
    i18n: { resolvedLanguage: 'en', language: 'en' },
  }),
}));

const SAMPLE: AuthListingItem = {
  title: 'Senior Python Engineer',
  company_name: 'Acme Corp',
  location_raw: 'San Francisco, CA',
  work_arrangement: 'REMOTE',
  required_skills: ['Python', 'FastAPI', 'Postgres', 'Kafka'],
  posted_at: '2026-04-15T12:00:00Z',
  language: 'en',
};

describe('AuthListingCard — accessibility guardrails', () => {
  test('renders the outer wrapper with aria-hidden="true"', () => {
    const { container } = render(<AuthListingCard listing={SAMPLE} />);

    const wrapper = container.firstElementChild;
    expect(wrapper).not.toBeNull();
    expect(wrapper?.getAttribute('aria-hidden')).toBe('true');
  });

  test('applies pointer-events-none and select-none classes', () => {
    const { container } = render(<AuthListingCard listing={SAMPLE} />);

    const wrapper = container.firstElementChild as HTMLElement | null;
    expect(wrapper?.className).toContain('pointer-events-none');
    expect(wrapper?.className).toContain('select-none');
  });

  test('applies tabIndex={-1} so the decorative card is not keyboard-reachable', () => {
    const { container } = render(<AuthListingCard listing={SAMPLE} />);

    const wrapper = container.firstElementChild as HTMLElement | null;
    expect(wrapper?.tabIndex).toBe(-1);
  });

  test('contains no anchor, button, or other interactive elements', () => {
    const { container } = render(<AuthListingCard listing={SAMPLE} />);

    expect(container.querySelectorAll('a').length).toBe(0);
    expect(container.querySelectorAll('button').length).toBe(0);
    expect(container.querySelectorAll('input').length).toBe(0);
    expect(container.querySelectorAll('[role="button"]').length).toBe(0);
    expect(container.querySelectorAll('[role="link"]').length).toBe(0);
    expect(container.querySelectorAll('[onclick]').length).toBe(0);
  });

  test('forwards the provided className so the canvas can size the card', () => {
    const { container } = render(<AuthListingCard listing={SAMPLE} className="w-[320px]" />);

    const wrapper = container.firstElementChild as HTMLElement | null;
    expect(wrapper?.className).toContain('w-[320px]');
  });
});

describe('AuthListingCard — content rendering', () => {
  test('renders the listing title', () => {
    render(<AuthListingCard listing={SAMPLE} />);

    expect(screen.getByText('Senior Python Engineer')).toBeInTheDocument();
  });

  test('renders the company name', () => {
    render(<AuthListingCard listing={SAMPLE} />);

    expect(screen.getByText('Acme Corp')).toBeInTheDocument();
  });

  test('renders the location when provided', () => {
    render(<AuthListingCard listing={SAMPLE} />);

    expect(screen.getByText('San Francisco, CA')).toBeInTheDocument();
  });

  test('limits skills shown to MAX_DECORATIVE_SKILLS (3) for visual density', () => {
    render(<AuthListingCard listing={SAMPLE} />);

    expect(screen.getByText('Python')).toBeInTheDocument();
    expect(screen.getByText('FastAPI')).toBeInTheDocument();
    expect(screen.getByText('Postgres')).toBeInTheDocument();
    expect(screen.queryByText('Kafka')).not.toBeInTheDocument();
  });

  test('handles a null location without crashing', () => {
    const withoutLocation: AuthListingItem = { ...SAMPLE, location_raw: null };

    render(<AuthListingCard listing={withoutLocation} />);

    expect(screen.queryByText('San Francisco, CA')).not.toBeInTheDocument();
    expect(screen.getByText('Senior Python Engineer')).toBeInTheDocument();
  });
});
