import type { RenderResult } from '@testing-library/react';
import { fireEvent, render, screen } from '@testing-library/react';
import type React from 'react';
import { I18nextProvider } from 'react-i18next';
import { beforeEach, describe, expect, vi } from 'vitest';
import { i18n } from '@/test/setup.ts';
import type { Dataset } from '../../model/index.ts';
import { useDocumentBuilderStore } from '../../model/index.ts';
import { ExportJSON } from './ExportJSON.tsx';

function renderWithProviders(ui: React.ReactElement): RenderResult {
  return render(<I18nextProvider i18n={i18n}>{ui}</I18nextProvider>);
}

const mockDatasets: Dataset[] = [
  {
    id: 'dataset-1',
    name: 'John Doe Resume',
    templateVersionId: 'version-1',
    data: {
      full_name: 'John Doe',
      professional_title: 'Software Engineer',
      contact: {
        email: 'john@example.com',
        phone: '+1-555-123-4567',
        location: 'San Francisco, CA',
        website: 'https://johndoe.dev',
      },
      skills: {
        label: 'Technical Skills',
        categories: [
          {
            category: 'Programming',
            items: ['JavaScript', 'TypeScript', 'Python'],
          },
        ],
      },
      experience: {
        label: 'Professional Experience',
        entries: [
          {
            title: 'Senior Developer',
            organization: 'Tech Corp',
            location: 'San Francisco, CA',
            period: ['2020', 'Present'],
            bullets: ['Built scalable web applications'],
          },
        ],
      },
      education: { label: 'Education', entries: [] },
      certifications: { label: 'Certifications', entries: [] },
      projects: { label: 'Projects', entries: [] },
      hobbies: { label: 'Hobbies', items: [] },
    },
    createdAt: new Date('2024-01-01').toISOString(),
    updatedAt: new Date('2024-01-01').toISOString(),
  },
  {
    id: 'dataset-2',
    name: 'Jane Smith Resume',
    templateVersionId: 'version-2',
    data: {
      full_name: 'Jane Smith',
      professional_title: 'Product Manager',
      contact: {
        email: 'jane@example.com',
        phone: '+1-555-987-6543',
        location: 'San Francisco, CA',
        website: 'https://janesmith.dev',
      },
      skills: {
        label: 'Skills',
        categories: [
          {
            category: 'Product',
            items: ['Product Strategy', 'User Research', 'Analytics'],
          },
        ],
      },
      experience: {
        label: 'Professional Experience',
        entries: [
          {
            title: 'Product Manager',
            organization: 'Product Corp',
            location: 'San Francisco, CA',
            period: ['2019', 'Present'],
            bullets: ['Led product development initiatives'],
          },
        ],
      },
      education: { label: 'Education', entries: [] },
      certifications: { label: 'Certifications', entries: [] },
      projects: { label: 'Projects', entries: [] },
      hobbies: { label: 'Hobbies', items: [] },
    },
    createdAt: new Date('2024-01-01').toISOString(),
    updatedAt: new Date('2024-01-01').toISOString(),
  },
];

const defaultProps: React.ComponentProps<typeof ExportJSON> = {
  isOpen: true,
  onClose: vi.fn<() => void>(),
};

const getCheckboxByDatasetId = (datasetId: string): HTMLElement =>
  screen.getByRole('checkbox', {
    name: new RegExp(datasetId === 'dataset-1' ? 'John Doe Resume' : 'Jane Smith Resume', 'iu'),
  });

describe('ExportJSON - rendering', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDocumentBuilderStore.setState({ datasets: mockDatasets });
  });

  test('renders the modal when open', () => {
    renderWithProviders(<ExportJSON {...defaultProps} />);

    expect(screen.getByText('Export JSON Datasets')).toBeInTheDocument();
    expect(screen.getByText('John Doe Resume')).toBeInTheDocument();
    expect(screen.getByText('Jane Smith Resume')).toBeInTheDocument();
  });

  test('does not render when closed', () => {
    renderWithProviders(<ExportJSON {...defaultProps} isOpen={false} />);

    expect(screen.queryByText('Export JSON Datasets')).not.toBeInTheDocument();
  });

  test('shows empty state when no datasets available', () => {
    useDocumentBuilderStore.setState({ datasets: [] });

    renderWithProviders(<ExportJSON {...defaultProps} />);

    expect(screen.getByText('No datasets available for export')).toBeInTheDocument();
  });
});

describe('ExportJSON - individual selection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDocumentBuilderStore.setState({ datasets: mockDatasets });
  });

  test('allows selecting and deselecting datasets', () => {
    renderWithProviders(<ExportJSON {...defaultProps} />);

    const johnCheckbox = getCheckboxByDatasetId('dataset-1');
    const janeCheckbox = getCheckboxByDatasetId('dataset-2');

    expect(johnCheckbox).not.toBeChecked();
    expect(janeCheckbox).not.toBeChecked();

    fireEvent.click(johnCheckbox);
    expect(johnCheckbox).toBeChecked();
    expect(screen.getByText('Select datasets to export (1 selected)')).toBeInTheDocument();

    fireEvent.click(janeCheckbox);
    expect(janeCheckbox).toBeChecked();
    expect(screen.getByText('Select datasets to export (2 selected)')).toBeInTheDocument();

    fireEvent.click(johnCheckbox);
    expect(johnCheckbox).not.toBeChecked();
    expect(screen.getByText('Select datasets to export (1 selected)')).toBeInTheDocument();
  });

  test('respects preselected datasets', () => {
    renderWithProviders(<ExportJSON {...defaultProps} preselectedDatasets={['dataset-1']} />);

    const johnCheckbox = getCheckboxByDatasetId('dataset-1');
    const janeCheckbox = getCheckboxByDatasetId('dataset-2');

    expect(johnCheckbox).toBeChecked();
    expect(janeCheckbox).not.toBeChecked();
    expect(screen.getByText('Select datasets to export (1 selected)')).toBeInTheDocument();
  });
});

describe('ExportJSON - bulk selection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDocumentBuilderStore.setState({ datasets: mockDatasets });
  });

  test('handles Select All functionality', () => {
    renderWithProviders(<ExportJSON {...defaultProps} />);

    fireEvent.click(screen.getByText(i18n.t('common:actions.selectAll')));

    expect(getCheckboxByDatasetId('dataset-1')).toBeChecked();
    expect(getCheckboxByDatasetId('dataset-2')).toBeChecked();
    expect(screen.getByText('Select datasets to export (2 selected)')).toBeInTheDocument();
  });

  test('handles Select None functionality', () => {
    renderWithProviders(
      <ExportJSON {...defaultProps} preselectedDatasets={['dataset-1', 'dataset-2']} />,
    );

    expect(screen.getByText('Select datasets to export (2 selected)')).toBeInTheDocument();

    fireEvent.click(screen.getByText(i18n.t('common:actions.deselectAll')));

    expect(getCheckboxByDatasetId('dataset-1')).not.toBeChecked();
    expect(getCheckboxByDatasetId('dataset-2')).not.toBeChecked();
    expect(screen.getByText('Select datasets to export (0 selected)')).toBeInTheDocument();
  });
});
