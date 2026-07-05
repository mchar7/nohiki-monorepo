import { toast } from 'sonner';
import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import {
  dismissToast,
  showError,
  showInfo,
  showLoading,
  showPromise,
  showSuccess,
  showWarning,
  toastManager,
} from './toast.ts';

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
    loading: vi.fn(),
    promise: vi.fn(),
    dismiss: vi.fn(),
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.resetAllMocks();
});

describe('toastManager - core methods', () => {
  test('calls success toast', () => {
    toastManager.success('Success message');
    expect(toast.success).toHaveBeenCalledWith('Success message', undefined);
  });

  test('calls error toast', () => {
    toastManager.error('Error message');
    expect(toast.error).toHaveBeenCalledWith('Error message', undefined);
  });

  test('calls warning toast', () => {
    toastManager.warning('Warning message');
    expect(toast.warning).toHaveBeenCalledWith('Warning message', undefined);
  });

  test('calls info toast', () => {
    toastManager.info('Info message');
    expect(toast.info).toHaveBeenCalledWith('Info message', undefined);
  });

  test('calls loading toast', () => {
    toastManager.loading('Loading...');
    expect(toast.loading).toHaveBeenCalledWith('Loading...', undefined);
  });

  test('passes options to toast', () => {
    toastManager.success('Message', {
      duration: 5000,
      description: 'Description',
      closeButton: true,
    });

    expect(toast.success).toHaveBeenCalledWith('Message', {
      duration: 5000,
      description: 'Description',
      closeButton: true,
      action: undefined,
    });
  });

  test('handles promise toast', () => {
    const promise = Promise.resolve('data');
    toastManager.promise(promise, {
      loading: 'Loading...',
      success: 'Done!',
      error: 'Failed',
    });

    expect(toast.promise).toHaveBeenCalledWith(promise, expect.any(Object));
  });

  test('dismisses toast by ID', () => {
    toastManager.dismiss('toast-123');
    expect(toast.dismiss).toHaveBeenCalledWith('toast-123');
  });
});

describe('toastManager - convenience methods', () => {
  test('saveSuccess shows success message', () => {
    toastManager.saveSuccess();
    expect(toast.success).toHaveBeenCalledWith('Changes saved successfully', undefined);
  });

  test('createSuccess shows success message', () => {
    toastManager.createSuccess();
    expect(toast.success).toHaveBeenCalledWith('Created successfully', undefined);
  });

  test('deleteSuccess shows success message', () => {
    toastManager.deleteSuccess();
    expect(toast.success).toHaveBeenCalledWith('Deleted successfully', undefined);
  });

  test('importSuccess shows success message', () => {
    toastManager.importSuccess();
    expect(toast.success).toHaveBeenCalledWith('Import completed successfully', undefined);
  });

  test('exportSuccess shows success message', () => {
    toastManager.exportSuccess();
    expect(toast.success).toHaveBeenCalledWith('Export completed successfully', undefined);
  });

  test('networkError shows error message', () => {
    toastManager.networkError();
    expect(toast.error).toHaveBeenCalledWith(
      'Network error occurred. Please try again.',
      undefined,
    );
  });

  test('validationError shows error message', () => {
    toastManager.validationError();
    expect(toast.error).toHaveBeenCalledWith('Please check your input and try again', undefined);
  });

  test('serverError shows error message', () => {
    toastManager.serverError();
    expect(toast.error).toHaveBeenCalledWith(
      'Server error occurred. Please try again later.',
      undefined,
    );
  });

  test('unauthorizedError shows error message', () => {
    toastManager.unauthorizedError();
    expect(toast.error).toHaveBeenCalledWith(
      'You are not authorized to perform this action',
      undefined,
    );
  });

  test('notFoundError shows error message', () => {
    toastManager.notFoundError();
    expect(toast.error).toHaveBeenCalledWith('The requested resource was not found', undefined);
  });
});

describe('exported toast functions', () => {
  test('showSuccess calls success toast', () => {
    showSuccess('Success');
    expect(toast.success).toHaveBeenCalled();
  });

  test('showError calls error toast', () => {
    showError('Error');
    expect(toast.error).toHaveBeenCalled();
  });

  test('showWarning calls warning toast', () => {
    showWarning('Warning');
    expect(toast.warning).toHaveBeenCalled();
  });

  test('showInfo calls info toast', () => {
    showInfo('Info');
    expect(toast.info).toHaveBeenCalled();
  });

  test('showLoading calls loading toast', () => {
    showLoading('Loading...');
    expect(toast.loading).toHaveBeenCalled();
  });

  test('showPromise calls promise toast', () => {
    showPromise(Promise.resolve(), {
      loading: 'Loading',
      success: 'Done',
      error: 'Error',
    });
    expect(toast.promise).toHaveBeenCalled();
  });

  test('dismissToast calls dismiss', () => {
    dismissToast();
    expect(toast.dismiss).toHaveBeenCalled();
  });
});
