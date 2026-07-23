import type { RenderResult } from '@testing-library/react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type React from 'react';
import { I18nextProvider } from 'react-i18next';
import { beforeEach, describe, expect, vi } from 'vitest';
import type { TemplateFamilyResponse } from '@/shared/api';
import { wrapWithRouter } from '@/shared/test-utils/index.ts';
import { i18n } from '@/test/i18n-setup.ts';
import type { Dataset, DatasetData } from '../../model/index.ts';
import { useDocumentBuilderStore } from '../../model/index.ts';
import { DatasetCard } from './DatasetCard.tsx';

const mockNavigate: ReturnType<typeof vi.fn> = vi.fn();
vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const mockCreateDataset = vi
  .fn<
    <TData extends DatasetData>(
      dataset: Omit<Dataset<TData>, 'id' | 'createdAt' | 'updatedAt'>,
    ) => string
  >()
  .mockReturnValue('new-dataset-id');
const mockUpdateDataset =
  vi.fn<<TData extends DatasetData>(id: string, updates: Partial<Dataset<TData>>) => void>();
const mockDeleteDataset = vi.fn<(id: string) => void>();
const mockSetActiveDataset = vi.fn<(id: string | null) => void>();

const mockTemplateFamily: TemplateFamilyResponse = {
  id: 'version-1',
  name: 'Resume Template',
  display_name: 'Resume Template',
  namespace: 'resume',
};

const mockDataset: Dataset = {
  id: 'dataset-1',
  name: 'My Resume',
  templateVersionId: 'version-1',
  data: { full_name: 'John Doe' },
  createdAt: '2024-01-01T00:00:00.000Z',
  updatedAt: '2024-01-02T00:00:00.000Z',
};

const mockDatasets: Dataset[] = [mockDataset];
const mockDatasetIndex: Map<string, Dataset> = new Map(mockDatasets.map((d) => [d.id, d]));

async function renderInWrapper(children: React.ReactNode): Promise<RenderResult> {
  return render(await wrapWithRouter(<I18nextProvider i18n={i18n}>{children}</I18nextProvider>));
}

describe('DatasetCard (integration)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDocumentBuilderStore.setState({
      datasets: mockDatasets,
      templateFamilies: [mockTemplateFamily],
      createDataset: mockCreateDataset,
      updateDataset: mockUpdateDataset,
      deleteDataset: mockDeleteDataset,
      setActiveDataset: mockSetActiveDataset,
      datasetIndex: mockDatasetIndex,
      getDataset: (id: string) => mockDatasetIndex.get(id),
    });
  });

  test('renders dataset information correctly', async () => {
    await renderInWrapper(<DatasetCard dataset={mockDataset} template={mockTemplateFamily} />);
    expect(screen.getByText('My Resume')).toBeInTheDocument();
  });

  test('passes the dataset to edit from both card and menu actions', async () => {
    const user = userEvent.setup();
    const onEdit = vi.fn();
    await renderInWrapper(
      <DatasetCard dataset={mockDataset} template={mockTemplateFamily} onEdit={onEdit} />,
    );

    await user.click(screen.getByRole('button', { name: /Dataset: My Resume/u }));
    expect(onEdit).toHaveBeenCalledWith(mockDataset);

    onEdit.mockClear();
    await user.click(screen.getByRole('button', { name: 'More options' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Edit Dataset' }));
    expect(onEdit).toHaveBeenCalledOnce();
    expect(onEdit).toHaveBeenCalledWith(mockDataset);
  });

  test('passes the dataset to the delete menu action', async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn();
    await renderInWrapper(
      <DatasetCard dataset={mockDataset} template={mockTemplateFamily} onDelete={onDelete} />,
    );

    await user.click(screen.getByRole('button', { name: 'More options' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Delete' }));

    expect(onDelete).toHaveBeenCalledOnce();
    expect(onDelete).toHaveBeenCalledWith(mockDataset);
  });

  test('passes the dataset to the duplicate menu action', async () => {
    const user = userEvent.setup();
    const onDuplicate = vi.fn();
    await renderInWrapper(
      <DatasetCard dataset={mockDataset} template={mockTemplateFamily} onDuplicate={onDuplicate} />,
    );

    await user.click(screen.getByRole('button', { name: 'More options' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Duplicate' }));

    expect(onDuplicate).toHaveBeenCalledOnce();
    expect(onDuplicate).toHaveBeenCalledWith(mockDataset);
  });
});
