import 'fake-indexeddb/auto';

import '@testing-library/jest-dom/vitest';
import { IDBFactory } from 'fake-indexeddb';
import { afterEach, beforeEach, vi } from 'vitest';

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
afterEach(() => {
  const requests = unexpectedRequests.splice(0);
  if (requests.length > 0) {
    throw new AggregateError(
      requests,
      'Unexpected network requests in unit test. Nested stacks identify the calling modules.',
    );
  }
});

vi.mock('zustand');
beforeEach(() => {
  unexpectedRequests.length = 0;
  globalThis.fetch = blockedFetch;
  globalThis.indexedDB = new IDBFactory();
});

import { MockFile } from './mocks/file-mock.ts';

// jsdom lacks canvas support without the native `canvas` npm package;
// returning null is safe since tests never assert on actual pixel output.
HTMLCanvasElement.prototype.getContext = vi.fn().mockReturnValue(null);

// Suppress jsdom "Not implemented: getComputedStyle with pseudo-elements"
// warnings emitted when Radix/Tailwind inspect ::before/::after styles.
// Stripping the pseudo-element arg returns the element's own styles instead,
// which is accurate enough for test assertions (jsdom can't resolve pseudo styles anyway).
const _origGetComputedStyle: typeof globalThis.getComputedStyle = globalThis.getComputedStyle;
globalThis.getComputedStyle = ((_elt: Element, _pseudoElt?: string | null) =>
  _origGetComputedStyle(_elt)) as typeof globalThis.getComputedStyle;

// Mock matchMedia for tests
Object.defineProperty(globalThis, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// Mock ResizeObserver as a proper class for floating-ui compatibility
(globalThis as Record<string, unknown>).ResizeObserver = class ResizeObserver {
  callback: ResizeObserverCallback;
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
  }
};

// Mock IntersectionObserver
(globalThis as Record<string, unknown>).IntersectionObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}));

// Mock File API for testing file uploads
(globalThis as Record<string, unknown>).File = MockFile;

// Mock URL.createObjectURL for file downloads
(
  globalThis as { URL: { createObjectURL: unknown; revokeObjectURL: unknown } }
).URL.createObjectURL = vi.fn(() => 'mock-url');
(
  globalThis as { URL: { createObjectURL: unknown; revokeObjectURL: unknown } }
).URL.revokeObjectURL = vi.fn();

// Mock document.createElement for download links
const originalCreateElement: typeof document.createElement = document.createElement.bind(document);
document.createElement = vi.fn().mockImplementation((tagName: string) => {
  if (tagName === 'a') {
    // Create a proper element that extends HTMLElement
    const element = originalCreateElement('a');
    element.href = '';
    element.download = '';
    element.click = vi.fn();
    return element;
  }
  return originalCreateElement(tagName);
});

// Radix Presence checks getComputedStyle().animationName to decide whether
// to wait for animationend. Clearing animation-name forces immediate unmount;
// zeroing durations guards against any future parser that fires the events.
const animStyle: HTMLStyleElement = originalCreateElement('style');
animStyle.textContent = [
  '*, *::before, *::after {',
  '  animation-name: none !important;',
  '  animation-duration: 0s !important;',
  '  transition-duration: 0s !important;',
  '}',
].join('\n');
document.head.appendChild(animStyle);
