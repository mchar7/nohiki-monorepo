import { afterEach, beforeEach } from 'vitest';

const unexpectedRequests: Error[] = [];
const blockedFetch: typeof fetch = (input: RequestInfo | URL): Promise<Response> => {
  const target = typeof input === 'string' ? input : 'url' in input ? input.url : input.href;
  const error = new Error(`Unexpected network request in unit test: ${target}`);
  unexpectedRequests.push(error);
  throw error;
};

// Vitest runs setup files before importing each test module. Install at module scope so API
// clients that capture fetch during construction bind the guard instead of the native client.
globalThis.fetch = blockedFetch;
beforeEach(() => {
  unexpectedRequests.length = 0;
  globalThis.fetch = blockedFetch;
});

afterEach(() => {
  const requests = unexpectedRequests.splice(0);
  if (requests.length > 0) {
    throw new AggregateError(
      requests,
      'Unexpected network requests in unit test. Nested stacks identify the calling modules.',
    );
  }
});
