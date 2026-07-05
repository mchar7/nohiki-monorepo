import { fireEvent, type RenderResult, render, screen } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { beforeEach, describe, expect, vi } from 'vitest';
import { i18n } from '@/test/setup.ts';
import { ApiEndpointSettings } from './ApiEndpointSettings.tsx';

function renderWithProviders(ui: React.ReactElement): RenderResult {
  return render(<I18nextProvider i18n={i18n}>{ui}</I18nextProvider>);
}

// Mock state that can be updated per test
let mockSettings = {
  endpoint: 'http://localhost:8000',
  isCustomEndpoint: false,
};

const mockSetEndpoint: ReturnType<typeof vi.fn> = vi.fn();
const mockResetToDefault: ReturnType<typeof vi.fn> = vi.fn();
const mockSaveEndpoint: ReturnType<typeof vi.fn> = vi.fn();

vi.mock('@features/omakase/document-builder/index.ts', () => ({
  useApiEndpointSettings: () => ({
    ...mockSettings,
    setEndpoint: mockSetEndpoint,
    resetToDefault: mockResetToDefault,
    saveEndpoint: mockSaveEndpoint,
  }),
  useApiEndpointHealthCheck: () => ({
    healthCheck: { state: 'idle' },
    validateUrl: (url: string) => {
      try {
        const parsed = new URL(url);
        return parsed.protocol === 'http:' || parsed.protocol === 'https:';
      } catch {
        return false;
      }
    },
    testConnection: vi.fn(),
    resetHealthCheck: vi.fn(),
  }),
}));

describe('ApiEndpointSettings rendering', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSettings = {
      endpoint: 'http://localhost:8000',
      isCustomEndpoint: false,
    };
  });

  test('renders the component with default endpoint', () => {
    renderWithProviders(<ApiEndpointSettings />);

    expect(screen.getByText('API Endpoint Configuration')).toBeInTheDocument();
    expect(screen.getByDisplayValue('http://localhost:8000')).toBeInTheDocument();
    expect(screen.getByText('Default')).toBeInTheDocument();
  });

  test('shows custom badge when using custom endpoint', () => {
    mockSettings = {
      endpoint: 'http://custom-api.com',
      isCustomEndpoint: true,
    };

    renderWithProviders(<ApiEndpointSettings />);

    expect(screen.getByText('Custom')).toBeInTheDocument();
  });

  test('validates URL format', () => {
    renderWithProviders(<ApiEndpointSettings />);

    const input = screen.getByLabelText('API Endpoint URL');
    fireEvent.change(input, { target: { value: 'invalid-url' } });

    expect(screen.getByText('Please enter a valid HTTP or HTTPS URL')).toBeInTheDocument();
  });
});

describe('ApiEndpointSettings interactions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSettings = {
      endpoint: 'http://localhost:8000',
      isCustomEndpoint: false,
    };
  });

  test('disables save button when no changes', () => {
    renderWithProviders(<ApiEndpointSettings />);

    const saveButton = screen.getByText('Save Endpoint');
    expect(saveButton).toBeDisabled();
  });

  test('enables save button when input changes', async () => {
    renderWithProviders(<ApiEndpointSettings />);

    const input = screen.getByLabelText('API Endpoint URL');
    fireEvent.change(input, { target: { value: 'http://new-endpoint.com' } });

    const saveButton = screen.getByText('Save Endpoint');
    await expect(saveButton).not.toBeDisabled();
  });

  test('shows reset button for custom endpoints', () => {
    mockSettings = {
      endpoint: 'http://custom-api.com',
      isCustomEndpoint: true,
    };

    renderWithProviders(<ApiEndpointSettings />);

    expect(screen.getByText('Reset to Default')).toBeInTheDocument();
  });
});
