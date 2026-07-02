import 'fake-indexeddb/auto';

import '@testing-library/jest-dom/vitest';
import { IDBFactory } from 'fake-indexeddb';
import i18next from 'i18next';
import { initReactI18next } from 'react-i18next';
import { beforeEach, vi } from 'vitest';

vi.mock('zustand');
beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
});

import accountEn from '../../public/locales/en/account.json' with { type: 'json' };
import attachmentsEn from '../../public/locales/en/attachments.json' with { type: 'json' };
import authEn from '../../public/locales/en/auth.json' with { type: 'json' };
import commonEn from '../../public/locales/en/common.json' with { type: 'json' };
import dashboardEn from '../../public/locales/en/dashboard.json' with { type: 'json' };
import documentsEn from '../../public/locales/en/documents.json' with { type: 'json' };
import jobsEn from '../../public/locales/en/jobs.json' with { type: 'json' };
import legalEn from '../../public/locales/en/legal.json' with { type: 'json' };
import navigationEn from '../../public/locales/en/navigation.json' with { type: 'json' };
import omakaseEditorEn from '../../public/locales/en/omakase.editor.json' with { type: 'json' };
import omakasePreviewEn from '../../public/locales/en/omakase.preview.json' with { type: 'json' };
import omakaseTemplateStudioEn from '../../public/locales/en/omakase.templateStudio.json' with {
  type: 'json',
};
import profilesEn from '../../public/locales/en/profiles.json' with { type: 'json' };
import settingsEn from '../../public/locales/en/settings.json' with { type: 'json' };
import validationEn from '../../public/locales/en/validation.json' with { type: 'json' };
import { MockFile } from './mocks/file-mock.ts';

const i18n: ReturnType<typeof i18next.createInstance> = i18next.createInstance();

i18n.use(initReactI18next).init({
  lng: 'en',
  fallbackLng: 'en',
  ns: [
    'common',
    'auth',
    'navigation',
    'settings',
    'validation',
    'legal',
    'omakase.editor',
    'omakase.preview',
    'omakase.templateStudio',
    'dashboard',
    'account',
    'attachments',
    'documents',
    'jobs',
    'profiles',
  ],
  defaultNS: 'common',
  resources: {
    en: {
      common: commonEn,
      auth: authEn,
      navigation: navigationEn,
      settings: settingsEn,
      validation: validationEn,
      legal: legalEn,
      'omakase.editor': omakaseEditorEn,
      'omakase.preview': omakasePreviewEn,
      'omakase.templateStudio': omakaseTemplateStudioEn,
      dashboard: dashboardEn,
      account: accountEn,
      attachments: attachmentsEn,
      documents: documentsEn,
      jobs: jobsEn,
      profiles: profilesEn,
    },
  },
  interpolation: {
    escapeValue: false,
  },
  react: {
    useSuspense: false,
  },
});

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

export { i18n };
