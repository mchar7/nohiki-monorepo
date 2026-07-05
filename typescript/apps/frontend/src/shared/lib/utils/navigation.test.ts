import { beforeEach, describe, expect, test, vi } from 'vitest';

vi.mock('./logger.ts', () => ({
  logger: { error: vi.fn() },
}));

import { logger } from './logger.ts';
import { handleNavigationPromise } from './navigation.ts';

const mockLogError = vi.mocked(logger.error);

async function flushPromiseHandlers(): Promise<void> {
  await Promise.resolve();
}

describe('handleNavigationPromise', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('does nothing when navigation resolves', async () => {
    handleNavigationPromise(Promise.resolve());
    await flushPromiseHandlers();

    expect(mockLogError).not.toHaveBeenCalled();
  });

  test('consumes an aborted navigation without logging', async () => {
    handleNavigationPromise(Promise.reject(new DOMException('Superseded', 'AbortError')));
    await flushPromiseHandlers();

    expect(mockLogError).not.toHaveBeenCalled();
  });

  test('logs an unexpected navigation failure exactly once', async () => {
    const error = new Error('Router failed');
    handleNavigationPromise(Promise.reject(error));
    await flushPromiseHandlers();

    expect(mockLogError).toHaveBeenCalledOnce();
    expect(mockLogError).toHaveBeenCalledWith('Navigation failed', error);
  });
});
