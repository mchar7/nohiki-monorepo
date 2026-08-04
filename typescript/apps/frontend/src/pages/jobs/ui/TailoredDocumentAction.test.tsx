import type * as TanStackReactRouter from '@tanstack/react-router';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, vi } from 'vitest';
import type * as DocumentGeneration from '@/features/document-generation';
import { useDocumentSSE, useGenerateTailoredDocument } from '@/features/document-generation';
import { useTemplateFamilies } from '@/features/omakase/document-builder';
import { TailoredDocumentAction } from './TailoredDocumentAction.tsx';

vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof TanStackReactRouter>();
  return {
    ...actual,
    Link: ({ children, to, ...props }: { children: ReactNode; to: string }) => (
      <a href={to} {...props}>
        {children}
      </a>
    ),
  };
});

vi.mock('@/features/document-generation/api/useDocumentSSE.ts', () => ({
  useDocumentSSE: vi.fn(),
}));
vi.mock('@/features/document-generation', async (importOriginal) => ({
  ...(await importOriginal<typeof DocumentGeneration>()),
  useGenerateTailoredDocument: vi.fn(),
}));
vi.mock('@/features/omakase/document-builder', () => ({
  useTemplateFamilies: vi.fn(),
}));

Object.defineProperties(HTMLElement.prototype, {
  hasPointerCapture: { configurable: true, value: vi.fn(() => false) },
  releasePointerCapture: { configurable: true, value: vi.fn() },
  scrollIntoView: { configurable: true, value: vi.fn() },
  setPointerCapture: { configurable: true, value: vi.fn() },
});

const refetch = vi.fn();
const reset = vi.fn();
const mutate = vi.fn();

const activeFamily = {
  id: 'family-modern',
  name: 'Modern Resume',
  namespace: 'resume',
  description: 'A focused resume',
  latest_version: { id: 'version-1' },
};
const inactiveFamily = {
  id: 'family-draft',
  name: 'Draft Template',
  namespace: 'resume',
  description: null,
  latest_version: null,
};

function templateResult(overrides: Record<string, unknown> = {}): never {
  return {
    data: {
      items: [activeFamily, inactiveFamily],
      total: 2,
      page: 1,
      page_size: 100,
      total_pages: 1,
      has_next: false,
      has_prev: false,
    },
    isLoading: false,
    error: null,
    refetch,
    ...overrides,
  } as never;
}

function mutationResult(overrides: Record<string, unknown> = {}): never {
  return {
    mutate,
    reset,
    isPending: false,
    error: null,
    ...overrides,
  } as never;
}

function sseResult(overrides: Record<string, unknown> = {}): never {
  return {
    status: 'connecting',
    downloadUrl: null,
    error: null,
    progress: 0,
    disconnect: vi.fn(),
    isConnected: false,
    ...overrides,
  } as never;
}

async function openAction(): Promise<ReturnType<typeof userEvent.setup>> {
  const user = userEvent.setup();
  render(
    <TailoredDocumentAction
      correlationId="correlation-42"
      jobTitle="Senior Engineer"
      company="Acme"
    />,
  );
  await user.click(screen.getByRole('button', { name: 'Tailor a document' }));
  return user;
}

async function chooseTemplate(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.click(screen.getByRole('combobox', { name: 'Template' }));
  await user.click(screen.getByRole('option', { name: 'Modern Resume' }));
}

describe('TailoredDocumentAction', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useTemplateFamilies).mockReturnValue(templateResult());
    vi.mocked(useGenerateTailoredDocument).mockReturnValue(mutationResult());
    vi.mocked(useDocumentSSE).mockReturnValue(sseResult());
  });

  test('loads templates only after opening and exposes accessible controls', async () => {
    vi.mocked(useTemplateFamilies).mockReturnValue(
      templateResult({ data: undefined, isLoading: true }),
    );

    const user = await openAction();

    expect(useTemplateFamilies).toHaveBeenCalledWith({ page: 1, page_size: 100 });
    const loading = screen.getByText('Loading document templates').parentElement;
    expect(loading).toHaveAttribute('aria-busy', 'true');
    expect(loading).toHaveAttribute('aria-live', 'polite');
    await user.click(screen.getByRole('button', { name: 'Close tailored document options' }));
    expect(screen.getByRole('button', { name: 'Tailor a document' })).toBeVisible();
  });

  test('shows template errors in an assertive live region and retries loading', async () => {
    vi.mocked(useTemplateFamilies).mockReturnValue(
      templateResult({ data: undefined, error: new Error('Templates unavailable') }),
    );

    const user = await openAction();

    const alert = screen.getByRole('alert');
    expect(alert).toHaveAttribute('aria-live', 'assertive');
    expect(within(alert).getByText('Templates unavailable')).toBeVisible();
    await user.click(within(alert).getByRole('button', { name: 'Try again' }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  test('shows an empty state when no visible template family has an active version', async () => {
    vi.mocked(useTemplateFamilies).mockReturnValue(
      templateResult({
        data: {
          items: [inactiveFamily],
          total: 1,
          page: 1,
          page_size: 100,
          total_pages: 1,
          has_next: false,
          has_prev: false,
        },
      }),
    );

    await openAction();

    expect(screen.getByText('No templates available')).toBeVisible();
    expect(screen.queryByRole('combobox', { name: 'Template' })).not.toBeInTheDocument();
  });

  test('selects a visible template and format and submits the exact tailored request', async () => {
    const user = await openAction();
    const generate = screen.getByRole('button', { name: 'Generate document' });
    expect(generate).toBeDisabled();

    await chooseTemplate(user);
    expect(screen.queryByRole('option', { name: 'Draft Template' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('combobox', { name: 'Format' }));
    await user.click(screen.getByRole('option', { name: 'HTML' }));
    await user.click(generate);

    expect(mutate).toHaveBeenCalledWith(
      {
        body: {
          job_correlation_id: 'correlation-42',
          template_id: 'family-modern',
          output_format: 'html',
        },
      },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });

  test('disables the form and announces pending generation', async () => {
    vi.mocked(useGenerateTailoredDocument).mockReturnValue(mutationResult({ isPending: true }));

    await openAction();

    expect(screen.getByRole('combobox', { name: 'Template' })).toBeDisabled();
    expect(screen.getByRole('combobox', { name: 'Format' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Starting…' })).toBeDisabled();
    expect(screen.getByText('Starting your tailored document…')).toHaveAttribute(
      'aria-live',
      'polite',
    );
  });

  test('shows generation errors in an assertive live region and retries the selected request', async () => {
    vi.mocked(useGenerateTailoredDocument).mockReturnValue(
      mutationResult({ error: new Error('Generation unavailable') }),
    );
    const user = await openAction();
    await chooseTemplate(user);

    const alert = screen.getByRole('alert');
    expect(alert).toHaveAttribute('aria-live', 'assertive');
    expect(within(alert).getByText('Generation unavailable')).toBeVisible();
    await user.click(within(alert).getByRole('button', { name: 'Try again' }));

    expect(mutate).toHaveBeenCalledWith(
      {
        body: {
          job_correlation_id: 'correlation-42',
          template_id: 'family-modern',
          output_format: 'pdf',
        },
      },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });

  test.each([
    {
      state: 'completed',
      sse: { status: 'completed', downloadUrl: '/api/v1/documents/download/result.pdf' },
      expected: 'Document ready',
    },
    {
      state: 'failed',
      sse: { status: 'failed', error: 'Rendering failed' },
      expected: 'Generation failed',
    },
  ])(
    'shows existing GenerationProgress in the $state terminal state',
    async ({ sse, expected }) => {
      vi.mocked(useDocumentSSE).mockReturnValue(sseResult(sse));
      mutate.mockImplementation((_variables, options) => {
        options.onSuccess({ request_id: 'request-99', status: 'accepted' });
      });
      const user = await openAction();
      await chooseTemplate(user);
      await user.click(screen.getByRole('button', { name: 'Generate document' }));

      await waitFor(() => expect(useDocumentSSE).toHaveBeenCalledWith('request-99'));
      expect(screen.getByText(expected)).toBeVisible();
    },
  );
});
