import type { RenderResult } from '@testing-library/react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type React from 'react';
import { I18nextProvider } from 'react-i18next';
import { beforeEach, describe, expect, vi } from 'vitest';
import type { TemplateFamilyResponse } from '@/shared/api';
import { i18n } from '@/test/i18n-setup.ts';
import type { Dataset } from '../../model/index.ts';
import { DatasetCard } from './DatasetCard.tsx';

const DATASET_RE = /dataset/iu;
const CACHED_RE = /cached/iu;

const mockTemplateFamily: TemplateFamilyResponse = {
  id: 'family-1',
  namespace: 'resume',
  name: 'resume_template',
  display_name: 'Resume Template',
};

const mockDataset: Dataset = {
  id: 'dataset-1',
  name: 'My Resume',
  templateVersionId: 'version-1',
  data: { full_name: 'John Doe' },
  createdAt: '2024-01-01T00:00:00.000Z',
  updatedAt: '2024-01-02T00:00:00.000Z',
};

const mockDatasetWithHtml: Dataset = {
  ...mockDataset,
  id: 'dataset-2',
  cachedHtmlData: '<html>cached</html>',
};

function renderCard(props: Partial<React.ComponentProps<typeof DatasetCard>> = {}): RenderResult {
  const defaultProps = {
    dataset: mockDataset,
    template: mockTemplateFamily,
  };
  return render(
    <I18nextProvider i18n={i18n}>
      <DatasetCard {...defaultProps} {...props} />
    </I18nextProvider>,
  );
}

function getCardElement(): HTMLElement {
  return screen.getByRole('button', { name: DATASET_RE });
}

describe('DatasetCard - rendering', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('renders dataset name', () => {
    renderCard();
    expect(screen.getByText('My Resume')).toBeInTheDocument();
  });

  test('renders template badge when template provided', () => {
    renderCard({ template: mockTemplateFamily });
    expect(screen.getByText('Resume Template')).toBeInTheDocument();
  });

  test('renders without template badge when no template', () => {
    renderCard({ template: undefined });
    expect(screen.queryByText('Resume Template')).not.toBeInTheDocument();
  });

  test('renders created date', () => {
    renderCard();
    const dateStr = new Date('2024-01-01T00:00:00.000Z').toLocaleDateString();
    expect(screen.getByText(dateStr)).toBeInTheDocument();
  });

  test('renders cached HTML badge when dataset has cached HTML', () => {
    renderCard({ dataset: mockDatasetWithHtml });
    expect(screen.getByText(CACHED_RE)).toBeInTheDocument();
  });

  test('applies selected styles when isSelected is true', () => {
    renderCard({ isSelected: true });
    const card = getCardElement();
    expect(card).toHaveAttribute('aria-pressed', 'true');
  });

  test('has correct aria-label', () => {
    renderCard();
    const card = getCardElement();
    expect(card).toHaveAttribute('aria-label');
    expect(card.getAttribute('aria-label')).toContain('My Resume');
  });
});

describe('DatasetCard - interactions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('calls onEdit when card is clicked', async () => {
    const onEdit = vi.fn();
    const user = userEvent.setup();
    renderCard({ onEdit });

    await user.click(getCardElement());
    expect(onEdit).toHaveBeenCalledWith(mockDataset);
  });

  test('calls onEdit when Enter is pressed on card', async () => {
    const onEdit = vi.fn();
    const user = userEvent.setup();
    renderCard({ onEdit });

    const card = getCardElement();
    card.focus();
    await user.keyboard('{Enter}');
    expect(onEdit).toHaveBeenCalledWith(mockDataset);
  });

  test('calls onEdit when Space is pressed on card', async () => {
    const onEdit = vi.fn();
    const user = userEvent.setup();
    renderCard({ onEdit });

    const card = getCardElement();
    card.focus();
    await user.keyboard(' ');
    expect(onEdit).toHaveBeenCalledWith(mockDataset);
  });

  test('keeps the actions trigger outside the card activation button and independently focusable', async () => {
    const onEdit = vi.fn();
    const user = userEvent.setup();
    renderCard({ onEdit });
    const card = getCardElement();
    const actions = screen.getByRole('button', { name: /more/iu });

    expect(card).not.toContainElement(actions);
    card.focus();
    await user.tab();
    expect(actions).toHaveFocus();

    await user.keyboard('{Enter}');
    expect(onEdit).not.toHaveBeenCalled();
  });
});

describe('DatasetCard - accessibility', () => {
  test('has proper ARIA attributes', () => {
    renderCard({ isSelected: false });
    const card = getCardElement();
    // Native <button> has implicit tabIndex=0 - no explicit attribute needed
    expect(card.tagName).toBe('BUTTON');
    expect(card).toHaveAttribute('aria-pressed', 'false');
  });
});
