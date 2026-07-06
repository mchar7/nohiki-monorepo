interface UnsavedChangesDialogProps {
  readonly open: boolean;
  /** Called when user clicks "Discard Changes": proceeds with navigation. */
  readonly onConfirm: (() => void) | undefined;
  /** Called when user clicks "Keep Editing": cancels navigation and stays on page. */
  readonly onCancel: (() => void) | undefined;
}

export type { UnsavedChangesDialogProps };
