import { toast } from 'sonner';

const SUCCESS_MESSAGES = {
  SAVE_SUCCESS: 'Changes saved successfully',
  CREATE_SUCCESS: 'Created successfully',
  DELETE_SUCCESS: 'Deleted successfully',
  IMPORT_SUCCESS: 'Import completed successfully',
  EXPORT_SUCCESS: 'Export completed successfully',
} as const;

const ERROR_MESSAGES = {
  NETWORK_ERROR: 'Network error occurred. Please try again.',
  VALIDATION_ERROR: 'Please check your input and try again',
  SERVER_ERROR: 'Server error occurred. Please try again later.',
  UNAUTHORIZED: 'You are not authorized to perform this action',
  NOT_FOUND: 'The requested resource was not found',
} as const;

interface ToastOptions {
  duration?: number;
  position?:
    | 'top-left'
    | 'top-right'
    | 'bottom-left'
    | 'bottom-right'
    | 'top-center'
    | 'bottom-center';
  closeButton?: boolean;
  description?: string;
  action?: {
    label: string;
    onClick: () => void;
  };
}

function toSonnerOptions(options: ToastOptions): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  if (options.duration !== undefined) {
    result.duration = options.duration;
  }
  if (options.description !== undefined) {
    result.description = options.description;
  }
  if (options.closeButton !== undefined) {
    result.closeButton = options.closeButton;
  }
  if (options.action !== undefined) {
    result.action = options.action;
  }
  return result;
}

class ToastManager {
  success(message: string, options?: ToastOptions): string | number {
    return toast.success(message, options ? toSonnerOptions(options) : undefined);
  }

  error(message: string, options?: ToastOptions): string | number {
    return toast.error(message, options ? toSonnerOptions(options) : undefined);
  }

  warning(message: string, options?: ToastOptions): string | number {
    return toast.warning(message, options ? toSonnerOptions(options) : undefined);
  }

  info(message: string, options?: ToastOptions): string | number {
    return toast.info(message, options ? toSonnerOptions(options) : undefined);
  }

  loading(message: string, options?: Omit<ToastOptions, 'action'>): string | number {
    return toast.loading(message, options ? toSonnerOptions(options) : undefined);
  }

  promise<T>(
    promise: Promise<T>,
    options: {
      loading: string;
      success: string | ((data: T) => string);
      error: string | ((error: Error) => string);
      description?: string;
    },
  ): string | number {
    const promiseOpts: Record<string, unknown> = {
      loading: options.loading,
      success: options.success,
      error: options.error,
    };
    if (options.description !== undefined) {
      promiseOpts.description = options.description;
    }
    return toast.promise(promise, promiseOpts) as string | number;
  }

  dismiss(toastId?: string | number): void {
    toast.dismiss(toastId);
  }

  saveSuccess(): string | number {
    return this.success(SUCCESS_MESSAGES.SAVE_SUCCESS);
  }

  createSuccess(): string | number {
    return this.success(SUCCESS_MESSAGES.CREATE_SUCCESS);
  }

  updateSuccess(): string | number {
    return this.success(SUCCESS_MESSAGES.SAVE_SUCCESS);
  }

  deleteSuccess(): string | number {
    return this.success(SUCCESS_MESSAGES.DELETE_SUCCESS);
  }

  importSuccess(): string | number {
    return this.success(SUCCESS_MESSAGES.IMPORT_SUCCESS);
  }

  exportSuccess(): string | number {
    return this.success(SUCCESS_MESSAGES.EXPORT_SUCCESS);
  }

  networkError(): string | number {
    return this.error(ERROR_MESSAGES.NETWORK_ERROR);
  }

  validationError(): string | number {
    return this.error(ERROR_MESSAGES.VALIDATION_ERROR);
  }

  serverError(): string | number {
    return this.error(ERROR_MESSAGES.SERVER_ERROR);
  }

  unauthorizedError(): string | number {
    return this.error(ERROR_MESSAGES.UNAUTHORIZED);
  }

  notFoundError(): string | number {
    return this.error(ERROR_MESSAGES.NOT_FOUND);
  }
}

const toastManager: ToastManager = new ToastManager();

export const {
  success: showSuccess,
  error: showError,
  warning: showWarning,
  info: showInfo,
  loading: showLoading,
  promise: showPromise,
  dismiss: dismissToast,
}: ToastManager = toastManager;

export { toastManager };
