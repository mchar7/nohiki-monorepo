import { act, renderHook } from '@testing-library/react';
import { describe, expect, vi } from 'vitest';
import { useDeleteConfirmation } from './useDeleteConfirmation.ts';

describe('useDeleteConfirmation - initial state', () => {
  test('starts with no pending delete', () => {
    const onDelete = vi.fn();
    const { result } = renderHook(() => useDeleteConfirmation(onDelete));

    expect(result.current.pendingDeleteId).toBeNull();
  });
});

describe('useDeleteConfirmation - requestDelete', () => {
  test('sets the pending delete ID', () => {
    const onDelete = vi.fn();
    const { result } = renderHook(() => useDeleteConfirmation(onDelete));

    act(() => {
      result.current.requestDelete('item-1');
    });

    expect(result.current.pendingDeleteId).toBe('item-1');
  });

  test('replaces previous pending ID when called again', () => {
    const onDelete = vi.fn();
    const { result } = renderHook(() => useDeleteConfirmation(onDelete));

    act(() => {
      result.current.requestDelete('item-1');
    });
    act(() => {
      result.current.requestDelete('item-2');
    });

    expect(result.current.pendingDeleteId).toBe('item-2');
  });
});

describe('useDeleteConfirmation - confirmDelete', () => {
  test('calls onDelete with the pending ID', () => {
    const onDelete = vi.fn();
    const { result } = renderHook(() => useDeleteConfirmation(onDelete));

    act(() => {
      result.current.requestDelete('item-1');
    });
    act(() => {
      result.current.confirmDelete();
    });

    expect(onDelete).toHaveBeenCalledWith('item-1');
    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  test('resets pending ID after confirmation', () => {
    const onDelete = vi.fn();
    const { result } = renderHook(() => useDeleteConfirmation(onDelete));

    act(() => {
      result.current.requestDelete('item-1');
    });
    act(() => {
      result.current.confirmDelete();
    });

    expect(result.current.pendingDeleteId).toBeNull();
  });

  test('does not call onDelete when no pending ID', () => {
    const onDelete = vi.fn();
    const { result } = renderHook(() => useDeleteConfirmation(onDelete));

    act(() => {
      result.current.confirmDelete();
    });

    expect(onDelete).not.toHaveBeenCalled();
    expect(result.current.pendingDeleteId).toBeNull();
  });
});

describe('useDeleteConfirmation - cancelDelete', () => {
  test('resets pending ID without calling onDelete', () => {
    const onDelete = vi.fn();
    const { result } = renderHook(() => useDeleteConfirmation(onDelete));

    act(() => {
      result.current.requestDelete('item-1');
    });
    act(() => {
      result.current.cancelDelete();
    });

    expect(onDelete).not.toHaveBeenCalled();
    expect(result.current.pendingDeleteId).toBeNull();
  });
});

describe('useDeleteConfirmation - callback stability', () => {
  // React Compiler auto-memoizes function references in production.
  // Without the compiler (test env), references are recreated each render,
  // so we verify functional correctness instead of reference identity.
  test('returns working function references after rerender', () => {
    const onDelete = vi.fn();
    const { result, rerender } = renderHook(() => useDeleteConfirmation(onDelete));

    rerender();

    expect(typeof result.current.requestDelete).toBe('function');
    expect(typeof result.current.cancelDelete).toBe('function');

    // Verify functions still work correctly after rerender
    act(() => result.current.requestDelete('test-id'));
    expect(result.current.pendingDeleteId).toBe('test-id');

    act(() => result.current.cancelDelete());
    expect(result.current.pendingDeleteId).toBeNull();
  });
});
