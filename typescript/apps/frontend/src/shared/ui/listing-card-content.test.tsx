import { render, screen } from '@testing-library/react';
import { describe, expect, vi } from 'vitest';
import { ListingCardContent } from './listing-card-content';

type ListingCardContentProps = Parameters<typeof ListingCardContent>[0];

const LANGUAGE_ARIA_LABEL_REGEX = /languageAriaLabel/u;

const DEFAULT_PROPS: ListingCardContentProps = {
  title: 'T',
  companyName: 'Co',
  locationRaw: null,
  workArrangement: null,
  requiredSkills: [],
  postedAt: null,
  language: null,
};

function renderListingCardContent(props: Partial<ListingCardContentProps> = {}): void {
  render(<ListingCardContent {...DEFAULT_PROPS} {...props} />);
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts?.count !== undefined ? `${key}:${opts.count}` : key,
    i18n: { resolvedLanguage: 'en', language: 'en' },
  }),
}));

describe('ListingCardContent — happy path', () => {
  test('renders title and company name', () => {
    renderListingCardContent({
      title: 'Senior Python Engineer',
      companyName: 'Acme',
      locationRaw: 'Remote',
      workArrangement: 'REMOTE',
      requiredSkills: ['Python'],
      postedAt: '2026-04-15T12:00:00Z',
      language: 'en',
    });

    expect(screen.getByText('Senior Python Engineer')).toBeInTheDocument();
    expect(screen.getByText('Acme')).toBeInTheDocument();
  });

  test('renders location and work arrangement on the meta row', () => {
    renderListingCardContent({
      locationRaw: 'Berlin, DE',
      workArrangement: 'HYBRID',
      postedAt: '2026-04-10T00:00:00Z',
      language: 'en',
    });

    expect(screen.getByText('Berlin, DE')).toBeInTheDocument();
    expect(screen.getByText('HYBRID')).toBeInTheDocument();
  });
});

describe('ListingCardContent — skills', () => {
  test('renders every supplied skill as a badge', () => {
    renderListingCardContent({ requiredSkills: ['Python', 'FastAPI', 'Postgres'] });

    expect(screen.getByText('Python')).toBeInTheDocument();
    expect(screen.getByText('FastAPI')).toBeInTheDocument();
    expect(screen.getByText('Postgres')).toBeInTheDocument();
  });
  test('renders duplicate skills without duplicate React keys', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    try {
      renderListingCardContent({ requiredSkills: ['Python', 'Python', 'FastAPI'] });

      expect(screen.getAllByText('Python')).toHaveLength(2);
      expect(screen.getByText('FastAPI')).toBeInTheDocument();
      expect(consoleError).not.toHaveBeenCalled();
    } finally {
      consoleError.mockRestore();
    }
  });

  test('collapses overflow skills into a "+N more" badge (MAX_VISIBLE=5)', () => {
    renderListingCardContent({
      requiredSkills: ['Alpha', 'Bravo', 'Charlie', 'Delta', 'Echo', 'Foxtrot', 'Golf'],
    });

    for (const skill of ['Alpha', 'Bravo', 'Charlie', 'Delta', 'Echo']) {
      expect(screen.getByText(skill)).toBeInTheDocument();
    }
    expect(screen.queryByText('Foxtrot')).not.toBeInTheDocument();
    expect(screen.queryByText('Golf')).not.toBeInTheDocument();
    expect(screen.getByText('card.moreSkills:2')).toBeInTheDocument();
  });
});

describe('ListingCardContent — null / empty edge cases', () => {
  test('renders fallback company label when companyName is empty', () => {
    renderListingCardContent({ companyName: '' });

    expect(screen.getByText('card.company')).toBeInTheDocument();
  });

  test('omits the location segment when locationRaw is null', () => {
    renderListingCardContent({ workArrangement: 'REMOTE' });

    expect(screen.queryByText('null')).not.toBeInTheDocument();
    expect(screen.getByText('REMOTE')).toBeInTheDocument();
  });

  test('omits the work-arrangement segment when workArrangement is null', () => {
    renderListingCardContent({ locationRaw: 'NYC' });

    expect(screen.getByText('NYC')).toBeInTheDocument();
  });
});

describe('ListingCardContent — footer behavior', () => {
  test('renders no skills footer when requiredSkills is empty', () => {
    const { container } = render(<ListingCardContent {...DEFAULT_PROPS} />);

    expect(container.querySelectorAll('[data-slot="badge"]').length).toBe(0);
  });

  test('suppresses the language badge when listing language matches UI locale', () => {
    renderListingCardContent({ language: 'en' });

    expect(screen.queryByLabelText(LANGUAGE_ARIA_LABEL_REGEX)).not.toBeInTheDocument();
  });
});
