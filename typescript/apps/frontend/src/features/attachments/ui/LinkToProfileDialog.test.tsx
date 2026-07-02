import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, vi } from 'vitest';
import type { ProfileResponse } from '@/shared/api';
import { LinkToProfileDialog } from './LinkToProfileDialog.tsx';

let mockIsMobile = false;

vi.mock('@/shared/lib/index.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/index.ts')>();
  return {
    ...actual,
    useIsMobileLayout: () => mockIsMobile,
  };
});

const mockMutate: ReturnType<typeof vi.fn> = vi.fn();
vi.mock('../api/index.ts', () => ({
  useLinkAttachmentToProfile: () => ({
    mutate: mockMutate,
    isPending: false,
  }),
}));

const mockProfiles: readonly ProfileResponse[] = [
  { id: 'pref-1', pref_name: 'Frontend Developer', user_id: 'u1' } as ProfileResponse,
  { id: 'pref-2', pref_name: 'Backend Engineer', user_id: 'u1' } as ProfileResponse,
];

describe('LinkToProfileDialog rendering', () => {
  const defaultProps = {
    open: true,
    onOpenChange: vi.fn(),
    uploadId: 'upload-1',
    profiles: mockProfiles,
    isLoadingProfiles: false,
  };

  afterEach(() => {
    vi.clearAllMocks();
    mockIsMobile = false;
  });

  test('renders dialog with title and description on desktop', () => {
    render(<LinkToProfileDialog {...defaultProps} />);
    expect(screen.getByText('Link to Profile')).toBeInTheDocument();
    expect(
      screen.getByText('Select a profile to associate this attachment with.'),
    ).toBeInTheDocument();
  });

  test('renders profile list with profile names', () => {
    render(<LinkToProfileDialog {...defaultProps} />);
    expect(screen.getByText('Frontend Developer')).toBeInTheDocument();
    expect(screen.getByText('Backend Engineer')).toBeInTheDocument();
  });

  test('renders bottom sheet on mobile', () => {
    mockIsMobile = true;
    render(<LinkToProfileDialog {...defaultProps} />);
    expect(screen.getByText('Link to Profile')).toBeInTheDocument();
    expect(screen.getByText('Frontend Developer')).toBeInTheDocument();
  });

  test('does not render when closed', () => {
    render(<LinkToProfileDialog {...defaultProps} open={false} />);
    expect(screen.queryByText('Link to Profile')).not.toBeInTheDocument();
  });
});

describe('LinkToProfileDialog interactions', () => {
  const defaultProps = {
    open: true,
    onOpenChange: vi.fn(),
    uploadId: 'upload-1',
    profiles: mockProfiles,
    isLoadingProfiles: false,
  };

  afterEach(() => {
    vi.clearAllMocks();
    mockIsMobile = false;
  });

  test('calls link mutation when a profile is selected', async () => {
    render(<LinkToProfileDialog {...defaultProps} />);
    await userEvent.click(screen.getByText('Frontend Developer'));
    expect(mockMutate).toHaveBeenCalledWith(
      { params: { path: { pref_id: 'pref-1', upload_id: 'upload-1' } } },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });

  test('renders empty message when no profiles exist', () => {
    render(<LinkToProfileDialog {...defaultProps} profiles={[]} />);
    expect(screen.getByText('No profiles available. Create a profile first.')).toBeInTheDocument();
  });

  test('renders skeletons while profiles are loading', () => {
    render(<LinkToProfileDialog {...defaultProps} isLoadingProfiles={true} />);
    expect(screen.queryByText('Frontend Developer')).not.toBeInTheDocument();
  });
});
