import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@shared/ui/alert-dialog.tsx';
import { AlertCircle, AlertTriangle, Info } from 'lucide-react';
import type { JSX } from 'react';

interface ConfirmDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  variant?: 'danger' | 'warning' | 'info';
}

export function ConfirmDialog({
  isOpen,
  onClose,
  onConfirm,
  title,
  message,
  confirmText = 'Confirm',
  cancelText = 'Cancel',
  variant = 'danger',
}: ConfirmDialogProps): JSX.Element {
  const actionClassName: string =
    variant === 'danger' ? 'bg-destructive hover:bg-destructive/90' : '';

  const handleConfirm = (): void => {
    onConfirm();
    // AlertDialogAction's default behavior closes the dialog via onOpenChange
  };

  const getIcon = (): JSX.Element => {
    switch (variant) {
      case 'danger':
        return <AlertTriangle className="size-6 text-destructive" />;
      case 'warning':
        return <AlertTriangle className="size-6 text-warning" />;
      case 'info':
        return <Info className="size-6 text-primary" />;
      default:
        return <AlertCircle className="size-6 text-destructive" />;
    }
  };

  return (
    <AlertDialog open={isOpen} onOpenChange={onClose}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <div className="flex items-start gap-4">
            <div className="shrink-0">{getIcon()}</div>
            <div className="flex-1">
              <AlertDialogTitle>{title}</AlertDialogTitle>
              <AlertDialogDescription className="mt-2">{message}</AlertDialogDescription>
            </div>
          </div>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{cancelText}</AlertDialogCancel>
          <AlertDialogAction onClick={handleConfirm} className={actionClassName}>
            {confirmText}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
