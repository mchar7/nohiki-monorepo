import { logger } from './logger.ts';

function handleNavigationPromise(promise: Promise<unknown>): void {
  promise
    .catch((error: unknown): void => {
      if (error instanceof DOMException && error.name === 'AbortError') {
        return;
      }

      logger.error('Navigation failed', error);
    })
    .catch(() => undefined);
}

export { handleNavigationPromise };
