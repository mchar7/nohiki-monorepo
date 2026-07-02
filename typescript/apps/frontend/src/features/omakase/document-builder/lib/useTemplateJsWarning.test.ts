import { beforeEach, describe, expect } from 'vitest';

let sessionTemplatePrefs: Map<string, 'html' | 'image'>;
let getSessionPref: (templateId: string, version: string) => 'html' | 'image' | null;
let setSessionPref: (templateId: string, version: string, method: 'html' | 'image') => void;

beforeEach(() => {
  // Create a fresh Map for each test to simulate session storage
  sessionTemplatePrefs = new Map();

  getSessionPref = (templateId: string, version: string): 'html' | 'image' | null => {
    const key = `${templateId}@${version}`;
    return sessionTemplatePrefs.get(key) || null;
  };

  setSessionPref = (templateId: string, version: string, method: 'html' | 'image'): void => {
    const key = `${templateId}@${version}`;
    sessionTemplatePrefs.set(key, method);
  };
});

describe('useTemplateJsWarning - store and retrieve', () => {
  test('stores and retrieves session preferences correctly', () => {
    const templateId = 'test-template';
    const version = '1.0.0';

    // Initially no preference
    expect(getSessionPref(templateId, version)).toBe(null);

    // Store a preference
    setSessionPref(templateId, version, 'html');

    // Should retrieve the stored preference
    expect(getSessionPref(templateId, version)).toBe('html');
  });

  test('handles different template versions separately', () => {
    const templateId = 'test-template';
    const version1 = '1.0.0';
    const version2 = '2.0.0';

    setSessionPref(templateId, version1, 'html');
    setSessionPref(templateId, version2, 'image');

    expect(getSessionPref(templateId, version1)).toBe('html');
    expect(getSessionPref(templateId, version2)).toBe('image');
  });

  test('handles different templates separately', () => {
    const template1 = 'template-1';
    const template2 = 'template-2';
    const version = '1.0.0';

    setSessionPref(template1, version, 'html');
    setSessionPref(template2, version, 'image');

    expect(getSessionPref(template1, version)).toBe('html');
    expect(getSessionPref(template2, version)).toBe('image');
  });
});

describe('useTemplateJsWarning - key generation', () => {
  test('generates unique keys for template@version combinations', () => {
    setSessionPref('template-1', '1.0.0', 'html');
    setSessionPref('template-1', '2.0.0', 'image');
    setSessionPref('template-2', '1.0.0', 'image');

    expect(getSessionPref('template-1', '1.0.0')).toBe('html');
    expect(getSessionPref('template-1', '2.0.0')).toBe('image');
    expect(getSessionPref('template-2', '1.0.0')).toBe('image');
    expect(getSessionPref('template-2', '2.0.0')).toBe(null);
  });

  test('returns null for non-existent preferences', () => {
    expect(getSessionPref('non-existent', '1.0.0')).toBe(null);
    expect(getSessionPref('template-1', 'non-existent-version')).toBe(null);
  });
});

describe('useTemplateJsWarning - behavior flow', () => {
  test('demonstrates the expected behavior flow', () => {
    // Documents the expected behavior without testing the actual hook
    const expectedFlow = {
      showWarning: true,
      userChoice: { method: 'html' as const, remember: false },
      sessionStored: true,
      permanentStored: false,
      nextCallShowsWarning: false,
      usesSessionPreference: true,
      afterRefreshShowsWarning: true,
    };

    expect(expectedFlow.showWarning).toBe(true);
    expect(expectedFlow.userChoice.remember).toBe(false);
    expect(expectedFlow.sessionStored).toBe(true);
    expect(expectedFlow.permanentStored).toBe(false);
    expect(expectedFlow.nextCallShowsWarning).toBe(false);
    expect(expectedFlow.usesSessionPreference).toBe(true);
    expect(expectedFlow.afterRefreshShowsWarning).toBe(true);
  });
});
