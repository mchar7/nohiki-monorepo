import type { RenderResult } from '@testing-library/react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type React from 'react';
import { I18nextProvider } from 'react-i18next';
import { beforeEach, describe, expect, vi } from 'vitest';
import type { TemplateFamilyResponse } from '@/shared/api';
import { i18n } from '@/test/setup.ts';
import type { Dataset } from '../../model/index.ts';
import { DatasetCard } from './DatasetCard.tsx';

const mockUseIsMobileLayout = vi.fn<() => boolean>().mockReturnValue(false);

vi.mock('@/shared/lib/index.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/index.ts')>();
  return {
    ...actual,
    useIsMobileLayout: () => mockUseIsMobileLayout(),
  };
});

const MORE_RE = /more/iu;
const EDIT_DATASET_RE = /edit dataset/iu;
const DUPLICATE_RE = /duplicate/iu;
const DOWNLOAD_RE = /download/iu;
const DELETE_RE = /delete/iu;
const RENAME_RE = /rename/iu;
const SAVE_RE = /save/iu;
const CANCEL_RE = /cancel/iu;

const mockTemplateFamily: TemplateFamilyResponse = {
  id: 'family-1',
  namespace: 'resume',
  name: 'Resume Template',
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

function getMenuButton(): HTMLElement {
  return screen.getByRole('button', { name: MORE_RE });
}

describe('DatasetCard - dropdown open and edit', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('opens dropdown menu when menu button is clicked', async () => {
    const user = userEvent.setup();
    renderCard();

    await user.click(getMenuButton());

    await waitFor(() => {
      expect(screen.getByText(EDIT_DATASET_RE)).toBeInTheDocument();
    });
  });

  test('calls onEdit from dropdown menu', async () => {
    const onEdit = vi.fn();
    const user = userEvent.setup();
    renderCard({ onEdit });

    await user.click(getMenuButton());

    const editItem = await screen.findByText(EDIT_DATASET_RE);
    await user.click(editItem);

    expect(onEdit).toHaveBeenCalledWith(mockDataset);
  });
});

describe('DatasetCard - dropdown actions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('calls onDuplicate from dropdown menu', async () => {
    const onDuplicate = vi.fn();
    const user = userEvent.setup();
    renderCard({ onDuplicate });

    await user.click(getMenuButton());

    const duplicateItem = await screen.findByText(DUPLICATE_RE);
    await user.click(duplicateItem);

    expect(onDuplicate).toHaveBeenCalledWith(mockDataset);
  });

  test('calls onDownload from dropdown menu', async () => {
    const onDownload = vi.fn();
    const user = userEvent.setup();
    renderCard({ onDownload });

    await user.click(getMenuButton());

    const downloadItem = await screen.findByText(DOWNLOAD_RE);
    await user.click(downloadItem);

    expect(onDownload).toHaveBeenCalledWith(mockDataset);
  });

  test('calls onDelete from dropdown menu', async () => {
    const onDelete = vi.fn();
    const user = userEvent.setup();
    renderCard({ onDelete });

    await user.click(getMenuButton());

    const deleteItem = await screen.findByText(DELETE_RE);
    await user.click(deleteItem);

    expect(onDelete).toHaveBeenCalledWith(mockDataset);
  });
});

describe('DatasetCard - rename open and submit', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('opens rename dialog when rename is clicked', async () => {
    const onRename = vi.fn();
    const user = userEvent.setup();
    renderCard({ onRename });

    await user.click(getMenuButton());
    const renameItem = await screen.findByText(RENAME_RE);
    await user.click(renameItem);

    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    await expect(screen.getByRole('textbox')).toHaveValue('My Resume');
  });

  test('calls onRename when save button is clicked', async () => {
    const onRename = vi.fn();
    const user = userEvent.setup();
    renderCard({ onRename });

    await user.click(getMenuButton());
    await user.click(await screen.findByText(RENAME_RE));

    const input = await screen.findByRole('textbox');
    await user.clear(input);
    await user.type(input, 'New Name');

    await user.click(screen.getByRole('button', { name: SAVE_RE }));

    expect(onRename).toHaveBeenCalledWith(mockDataset, 'New Name');
  });

  test('calls onRename when Enter is pressed in input', async () => {
    const onRename = vi.fn();
    const user = userEvent.setup();
    renderCard({ onRename });

    await user.click(getMenuButton());
    await user.click(await screen.findByText(RENAME_RE));

    const input = await screen.findByRole('textbox');
    await user.clear(input);
    await user.type(input, 'New Name{Enter}');

    expect(onRename).toHaveBeenCalledWith(mockDataset, 'New Name');
  });
});

describe('DatasetCard - rename cancel and edge cases', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('closes dialog when cancel is clicked', async () => {
    const onRename = vi.fn();
    const user = userEvent.setup();
    renderCard({ onRename });

    await user.click(getMenuButton());
    await user.click(await screen.findByText(RENAME_RE));

    await user.click(screen.getByRole('button', { name: CANCEL_RE }));

    expect(onRename).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  test('does not call onRename if name is unchanged', async () => {
    const onRename = vi.fn();
    const user = userEvent.setup();
    renderCard({ onRename });

    await user.click(getMenuButton());
    await user.click(await screen.findByText(RENAME_RE));

    await user.click(await screen.findByRole('button', { name: SAVE_RE }));

    expect(onRename).not.toHaveBeenCalled();
  });

  test('does not call onRename if name is empty', async () => {
    const onRename = vi.fn();
    const user = userEvent.setup();
    renderCard({ onRename });

    await user.click(getMenuButton());
    await user.click(await screen.findByText(RENAME_RE));

    const input = await screen.findByRole('textbox');
    await user.clear(input);

    await user.click(screen.getByRole('button', { name: SAVE_RE }));

    expect(onRename).not.toHaveBeenCalled();
  });

  test('does not render dialog when onRename is not provided', () => {
    renderCard({ onRename: undefined });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});

describe('DatasetCard - mobile', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseIsMobileLayout.mockReturnValue(true);
  });

  test('renders BottomSheet with actions and correct title', async () => {
    const user = userEvent.setup();
    renderCard();

    await user.click(getMenuButton());

    await waitFor(() => {
      expect(screen.getByText(EDIT_DATASET_RE)).toBeInTheDocument();
      expect(screen.getByText(DUPLICATE_RE)).toBeInTheDocument();
      expect(screen.getByText(DOWNLOAD_RE)).toBeInTheDocument();
      expect(screen.getByText(DELETE_RE)).toBeInTheDocument();
    });
  });

  test('calls onEdit correctly in mobile mode', async () => {
    const onEdit = vi.fn();
    const user = userEvent.setup();
    renderCard({ onEdit });

    await user.click(getMenuButton());

    const editItem = await screen.findByText(EDIT_DATASET_RE);
    await user.click(editItem);

    expect(onEdit).toHaveBeenCalledWith(mockDataset);
  });

  test('calls onDelete correctly in mobile mode', async () => {
    const onDelete = vi.fn();
    const user = userEvent.setup();
    renderCard({ onDelete });

    await user.click(getMenuButton());

    const deleteItem = await screen.findByText(DELETE_RE);
    await user.click(deleteItem);

    expect(onDelete).toHaveBeenCalledWith(mockDataset);
  });
});
