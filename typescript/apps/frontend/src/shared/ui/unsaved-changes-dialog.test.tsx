import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, vi } from 'vitest';
import { UnsavedChangesDialog } from './unsaved-changes-dialog.tsx';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('./alert-dialog.tsx', () => ({
  AlertDialog: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  AlertDialogAction: ({ children, onClick }: { children: ReactNode; onClick?: () => void }) => (
    <button type="button" onClick={onClick}>
      {children}
    </button>
  ),
  AlertDialogCancel: ({ children, onClick }: { children: ReactNode; onClick?: () => void }) => (
    <button type="button" onClick={onClick}>
      {children}
    </button>
  ),
  AlertDialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  AlertDialogDescription: ({ children }: { children: ReactNode }) => <p>{children}</p>,
  AlertDialogFooter: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  AlertDialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  AlertDialogTitle: ({ children }: { children: ReactNode }) => <h1>{children}</h1>,
}));

describe('UnsavedChangesDialog', () => {
  test('renders translated dialog actions', () => {
    render(<UnsavedChangesDialog open={true} onConfirm={undefined} onCancel={undefined} />);

    expect(screen.getByText('unsavedChanges.title')).toBeInTheDocument();
    expect(screen.getByText('unsavedChanges.leave')).toBeInTheDocument();
    expect(screen.getByText('unsavedChanges.stay')).toBeInTheDocument();
  });
});
