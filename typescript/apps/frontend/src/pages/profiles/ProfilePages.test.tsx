import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, vi } from 'vitest';
import { ProfileCreate } from './ProfileCreate.tsx';
import { ProfileDetail } from './ProfileDetail.tsx';

vi.mock('@tanstack/react-router', () => ({
  useParams: () => ({ profileId: 'p-1' }),
  Link: ({ children }: { children: ReactNode }) => <a href="/">{children}</a>,
}));
vi.mock('@/shared/lib/index.ts', () => ({
  useDocumentTitle: () => undefined,
  useUnsavedChanges: () => ({ status: 'idle', proceed: undefined, reset: undefined }),
  useIsMobileLayout: () => false,
}));
vi.mock('@/shared/ui/unsaved-changes-dialog.tsx', () => ({ UnsavedChangesDialog: () => null }));
vi.mock('@/shared/ui/PageHeader.tsx', () => ({
  PageHeader: ({ title }: { title: string }) => <h1>{title}</h1>,
}));
vi.mock('@/widgets/layout/index.ts', () => ({
  PageLayout: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));
vi.mock('@/shared/ui/form.tsx', () => ({
  Form: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));
vi.mock('@/features/profile-management/index.ts', () => ({
  useProfileCreateForm: () => ({
    form: { formState: { isDirty: false }, handleSubmit: (fn: () => void) => fn, control: {} },
    onSubmit: vi.fn(),
    isPending: false,
  }),
  useProfile: () => ({ data: { pref_name: 'Test Profile' }, isLoading: false, error: null }),
  useProfileDelete: () => ({
    showDialog: false,
    openDialog: vi.fn(),
    closeDialog: vi.fn(),
    isPending: false,
    confirmDelete: vi.fn(),
  }),
  useProfileEditForm: () => ({
    isEditing: false,
    form: { formState: { isDirty: false }, handleSubmit: (fn: () => void) => fn, control: {} },
    startEditing: vi.fn(),
    cancelEditing: vi.fn(),
    onSubmit: vi.fn(),
    isPending: false,
  }),
  ProfileNameCard: () => null,
  KeywordsCard: () => null,
  SkillsCard: () => null,
  ExperienceCard: () => null,
  SalaryCard: () => null,
  WorkArrangementsCard: () => null,
  RelocationCard: () => null,
  ThresholdsCard: () => null,
  ProfileViewCard: () => null,
  FeatureImportanceSection: () => null,
  ProfileDetailActions: () => null,
  ProfileDetailSkeleton: () => null,
  ProfileNotFound: () => null,
  ProfileEditActions: () => null,
}));
vi.mock('./ui/DeleteConfirmDialog.tsx', () => ({ DeleteConfirmDialog: () => null }));
vi.mock('./ui/ProfileDetailActions.tsx', () => ({ ProfileDetailActions: () => null }));
vi.mock('./ui/ProfileDetailStates.tsx', () => ({
  ProfileDetailSkeleton: () => null,
  ProfileNotFound: () => null,
}));
vi.mock('./ui/ProfileEditActions.tsx', () => ({ ProfileEditActions: () => null }));

describe('profile pages', () => {
  test('renders create page', () => {
    render(<ProfileCreate />);
    expect(screen.getByText('Create Job Target')).toBeInTheDocument();
  });

  test('renders detail page', () => {
    render(<ProfileDetail />);
    expect(screen.getByText('Test Profile')).toBeInTheDocument();
  });
});
