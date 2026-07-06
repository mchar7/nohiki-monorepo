import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, vi } from 'vitest';
import type { SkillSearchResponse } from '@/shared/api/index.ts';
import { nonNull } from '@/shared/test-utils';
import { SkillInput } from './SkillInput.tsx';

// i18next initialized in setup.ts, but we use the real one, no need to mock react-i18next

// Mock fetchClient.GET via the client module so $api (created from fetchClient) uses the mock.
// Must mock @/shared/api/client (not index.ts) so $api is re-created with the mocked client.
const {
  mockGet,
}: {
  mockGet: ReturnType<typeof vi.fn>;
} = vi.hoisted(() => ({
  mockGet: vi.fn(),
}));

vi.mock('@/shared/api/client', async () => {
  const { default: createQueryClient } =
    await vi.importActual<typeof import('openapi-react-query')>('openapi-react-query');
  const client = {
    GET: mockGet,
    POST: vi.fn(),
    DELETE: vi.fn(),
    PATCH: vi.fn(),
    PUT: vi.fn(),
  };
  return {
    fetchClient: client,
    $api: createQueryClient(client as never),
    createDevClient: vi.fn(),
  };
});

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

const mockSkills: SkillSearchResponse['skills'] = [
  { id: '1', name: 'react', display_name: 'React', category: 'Frontend' },
  { id: '2', name: 'typescript', display_name: 'TypeScript', category: 'Language' },
  { id: '3', name: 'node', display_name: 'Node.js', category: 'Backend' },
];

describe('SkillInput', () => {
  const mockOnChange = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('renders badges for each skill in value array', () => {
    render(
      <SkillInput
        value={[nonNull(mockSkills[0]), nonNull(mockSkills[1])]}
        onChange={mockOnChange}
      />,
      {
        wrapper: createWrapper(),
      },
    );
    expect(screen.getByText('React')).toBeInTheDocument();
    expect(screen.getByText('TypeScript')).toBeInTheDocument();
    expect(screen.queryByText('Node.js')).not.toBeInTheDocument();
  });

  test('Remove button click calls onChange without the removed skill', async () => {
    render(
      <SkillInput
        value={[nonNull(mockSkills[0]), nonNull(mockSkills[1])]}
        onChange={mockOnChange}
      />,
      {
        wrapper: createWrapper(),
      },
    );
    const removeButtons = screen.getAllByRole('button', { name: /Delete/iu });
    await userEvent.click(nonNull(removeButtons[0]));
    expect(mockOnChange).toHaveBeenCalledWith([nonNull(mockSkills[1])]);
  });

  test('Remove button has accessible aria-label', () => {
    render(<SkillInput value={[nonNull(mockSkills[0])]} onChange={mockOnChange} />, {
      wrapper: createWrapper(),
    });
    const removeButton = screen.getByRole('button', { name: 'Delete React' });
    expect(removeButton).toBeInTheDocument();
    expect(removeButton).toHaveAttribute('aria-label', 'Delete React');
  });

  test('Search input triggers API call at >= 2 characters', async () => {
    mockGet.mockResolvedValue({
      data: { skills: [nonNull(mockSkills[2])] },
      error: undefined,
      response: new Response(),
    });
    render(<SkillInput value={[]} onChange={mockOnChange} />, { wrapper: createWrapper() });

    // Open popover
    await userEvent.click(screen.getByRole('button'));

    const searchInput = screen.getByPlaceholderText('Search skills...');

    // Type 1 char - shouldn't trigger
    await userEvent.type(searchInput, 'n');
    expect(mockGet).not.toHaveBeenCalled();

    // Type 2nd char - should trigger
    await userEvent.type(searchInput, 'o');
    await waitFor(() => {
      // $api.useQuery injects an AbortSignal via TanStack Query; use objectContaining to
      // assert the relevant params without coupling to the signal internals.
      expect(mockGet).toHaveBeenCalledWith(
        '/api/v1/skills/search',
        expect.objectContaining({ params: { query: { q: 'no', limit: 10 } } }),
      );
    });
  });

  test('Selecting a skill from results calls onChange with skill appended', async () => {
    mockGet.mockResolvedValue({
      data: { skills: [nonNull(mockSkills[2])] },
      error: undefined,
      response: new Response(),
    });
    render(<SkillInput value={[nonNull(mockSkills[0])]} onChange={mockOnChange} />, {
      wrapper: createWrapper(),
    });

    await userEvent.click(screen.getByText('React'));
    const searchInput = screen.getByPlaceholderText('Search skills...');
    await userEvent.type(searchInput, 'no');

    const nodeItem = await screen.findByRole('option', { name: /Node.js/iu });
    await userEvent.click(nodeItem);

    expect(mockOnChange).toHaveBeenCalledWith([nonNull(mockSkills[0]), nonNull(mockSkills[2])]);
  });

  test('maxSkills boundary: when at max, new selection is ignored and input shows max message', async () => {
    mockGet.mockResolvedValue({
      data: { skills: [nonNull(mockSkills[2])] },
      error: undefined,
      response: new Response(),
    });
    render(
      <SkillInput
        value={[nonNull(mockSkills[0]), nonNull(mockSkills[1])]}
        onChange={mockOnChange}
        maxSkills={2}
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByText('Maximum of 2 skills reached')).toBeInTheDocument();

    // Still can't select more if opened
    await userEvent.click(screen.getByText('React'));
    const searchInput = screen.getByPlaceholderText('Search skills...');
    await userEvent.type(searchInput, 'no');

    const nodeItem = await screen.findByRole('option', { name: /Node.js/iu });
    await userEvent.click(nodeItem);

    // Should NOT have been called with the 3rd skill
    expect(mockOnChange).not.toHaveBeenCalled();
  });

  test('disabled prop disables all interaction', async () => {
    render(
      <SkillInput value={[nonNull(mockSkills[0])]} onChange={mockOnChange} disabled={true} />,
      {
        wrapper: createWrapper(),
      },
    );

    const trigger = screen.getByText('React').closest('button');
    expect(trigger).toBeDisabled();

    const removeButton = screen.getByRole('button', { name: 'Delete React' });
    expect(removeButton).toBeDisabled();

    // Clicking trigger doesn't open popover
    if (trigger) {
      await userEvent.click(trigger);
    }
    expect(screen.queryByPlaceholderText('Search skills...')).not.toBeInTheDocument();
  });

  test('Placeholder text shown when no skills selected', () => {
    render(<SkillInput value={[]} onChange={mockOnChange} placeholder="Custom placeholder" />, {
      wrapper: createWrapper(),
    });

    expect(screen.getByText('Custom placeholder')).toBeInTheDocument();
  });

  test('Duplicate skills cannot be added (dedup prevention)', async () => {
    // Return React as a search result, even though it's already selected
    mockGet.mockResolvedValue({
      data: { skills: [nonNull(mockSkills[0])] },
      error: undefined,
      response: new Response(),
    });
    render(<SkillInput value={[nonNull(mockSkills[0])]} onChange={mockOnChange} />, {
      wrapper: createWrapper(),
    });

    await userEvent.click(screen.getByText('React'));
    const searchInput = screen.getByPlaceholderText('Search skills...');
    await userEvent.type(searchInput, 're');

    // The query completes but React shouldn't be listed as it's already selected
    // It filters it out locally: searchResults?.skills.filter(s => !selectedIds.has(s.id))
    await waitFor(() => {
      expect(mockGet).toHaveBeenCalled();
    });

    // Should show "No skills found" since React is filtered out
    expect(screen.getByText('No skills found')).toBeInTheDocument();
  });

  test('Empty search results show appropriate message', async () => {
    mockGet.mockResolvedValue({
      data: { skills: [] },
      error: undefined,
      response: new Response(),
    });
    render(<SkillInput value={[]} onChange={mockOnChange} />, { wrapper: createWrapper() });

    await userEvent.click(screen.getByRole('button'));
    const searchInput = screen.getByPlaceholderText('Search skills...');
    await userEvent.type(searchInput, 'xyz');

    await waitFor(() => {
      expect(screen.getByText('No skills found')).toBeInTheDocument();
    });
  });
});
