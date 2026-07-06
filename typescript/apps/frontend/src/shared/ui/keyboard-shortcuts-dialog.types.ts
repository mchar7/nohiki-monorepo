interface KeyboardShortcutsDialogProps {
  /** Whether the dialog is open. */
  readonly open: boolean;
  /** Callback when the dialog open state changes. */
  readonly onOpenChange: (open: boolean) => void;
}

export type { KeyboardShortcutsDialogProps };
