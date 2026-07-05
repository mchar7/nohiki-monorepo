import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { act, renderHook } from '@testing-library/react';
import type { FieldValues, UseFormClearErrors, UseFormReturn, UseFormWatch } from 'react-hook-form';
import type { Mock } from 'vitest';
import { describe, expect, vi } from 'vitest';
import { nonNull } from '@/shared/test-utils';
import { useFormRootErrorClearOnEdit } from '../useFormRootErrorClearOnEdit.ts';

type WatchCallback = (value: unknown, info: { name?: string }) => void;

interface MockSubscription {
  unsubscribe: Mock;
}

/** Creates a minimal mock of UseFormReturn with controllable watch and errors. */
function createMockForm(): {
  form: Parameters<typeof useFormRootErrorClearOnEdit>[0];
  setRootError: (msg: string) => void;
  clearRootError: () => void;
  simulateFieldChange: (name: string) => void;
  simulateAnonymousChange: () => void;
  getSubscriptions: () => MockSubscription[];
} {
  let watchCallback: WatchCallback | null = null;
  const subscriptions: MockSubscription[] = [];

  const errors: { root?: { message: string } } = {};
  const formState = { errors } as UseFormReturn<FieldValues>['formState'];

  const clearErrors = vi.fn((key?: string) => {
    if (key === 'root') {
      errors.root = undefined;
    }
  }) as UseFormClearErrors<FieldValues>;

  const watch = vi.fn((cb: WatchCallback) => {
    watchCallback = cb;
    const subscription: MockSubscription = {
      unsubscribe: vi.fn(() => {
        watchCallback = null;
      }),
    };
    subscriptions.push(subscription);
    return subscription;
  }) as unknown as UseFormWatch<FieldValues>;

  // The hook's parameter type is intentionally narrowed to the three fields
  // used here (see FormRootErrorClearOnEditTarget). Structural typing accepts
  // this object directly without any cast.
  const form: Parameters<typeof useFormRootErrorClearOnEdit>[0] = { formState, clearErrors, watch };

  return {
    form,
    setRootError: (msg: string) => {
      errors.root = { message: msg };
    },
    clearRootError: () => {
      errors.root = undefined;
    },
    simulateFieldChange: (name: string) => {
      watchCallback?.({}, { name });
    },
    simulateAnonymousChange: () => {
      watchCallback?.({}, {});
    },
    getSubscriptions: () => subscriptions,
  };
}

describe('useFormRootErrorClearOnEdit - persistence', () => {
  test('root error persists when no field is edited after error is set', () => {
    const { form, setRootError } = createMockForm();

    const { rerender } = renderHook(() => useFormRootErrorClearOnEdit(form));

    setRootError('Server error');
    rerender();

    expect(form.formState.errors.root).toEqual({ message: 'Server error' });
    expect(form.clearErrors).not.toHaveBeenCalled();
  });

  test('root error does NOT clear when form.watch fires before error is set', () => {
    const { form, simulateFieldChange } = createMockForm();

    renderHook(() => useFormRootErrorClearOnEdit(form));

    act(() => {
      simulateFieldChange('email');
    });

    expect(form.clearErrors).not.toHaveBeenCalled();
  });
});

describe('useFormRootErrorClearOnEdit - clearing', () => {
  test('root error clears when user edits a field AFTER the error appeared', () => {
    const { form, setRootError, simulateFieldChange } = createMockForm();

    const { rerender } = renderHook(() => useFormRootErrorClearOnEdit(form));

    setRootError('Invalid credentials');
    rerender();

    act(() => {
      simulateFieldChange('email');
    });

    expect(form.clearErrors).toHaveBeenCalledWith('root');
  });

  test('root error clears immediately on first field edit, not on subsequent edits (ref resets to false)', () => {
    const { form, setRootError, simulateFieldChange } = createMockForm();

    const { rerender } = renderHook(() => useFormRootErrorClearOnEdit(form));

    setRootError('Error');
    rerender();

    act(() => {
      simulateFieldChange('email');
    });
    expect(form.clearErrors).toHaveBeenCalledTimes(1);

    act(() => {
      simulateFieldChange('password');
    });
    expect(form.clearErrors).toHaveBeenCalledTimes(1);
  });

  test('error clears correctly after mode change + new error cycle (ref resets bidirectionally)', () => {
    const { form, setRootError, clearRootError, simulateFieldChange } = createMockForm();

    const { rerender } = renderHook(() => useFormRootErrorClearOnEdit(form));

    setRootError('First error');
    rerender();

    act(() => {
      simulateFieldChange('email');
    });
    expect(form.clearErrors).toHaveBeenCalledTimes(1);

    clearRootError();
    rerender();

    setRootError('Second error');
    rerender();

    act(() => {
      simulateFieldChange('password');
    });
    expect(form.clearErrors).toHaveBeenCalledTimes(2);
  });
});

describe('useFormRootErrorClearOnEdit - implementation and cleanup', () => {
  test('no setTimeout exists in the implementation', () => {
    const sourcePath = resolve(import.meta.dirname, '..', 'useFormRootErrorClearOnEdit.ts');
    const source = readFileSync(sourcePath, 'utf-8');

    expect(source.match(/setTimeout/gu) ?? []).toHaveLength(0);
  });

  test('subscription is cleaned up on unmount', () => {
    const { form, getSubscriptions } = createMockForm();

    const { unmount } = renderHook(() => useFormRootErrorClearOnEdit(form));

    const subs = getSubscriptions();
    expect(subs).toHaveLength(1);
    expect(nonNull(subs[0]).unsubscribe).not.toHaveBeenCalled();

    unmount();

    expect(nonNull(subs[0]).unsubscribe).toHaveBeenCalledTimes(1);
  });
});
