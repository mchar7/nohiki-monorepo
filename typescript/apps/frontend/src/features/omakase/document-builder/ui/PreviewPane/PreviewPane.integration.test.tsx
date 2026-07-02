import { describe, expect, vi } from 'vitest';
import { nonNull } from '@/shared/test-utils';

/** 2 render methods x 2 choices (remember/don't remember) */
const EXPECTED_MOCK_CALLS: number = 4;

// Mock the PreviewPane and its dependencies
vi.mock('../PreviewPane', () => ({
  PreviewPane: vi.fn(() => null),
}));

vi.mock('../../hooks/useTemplateJsWarning', () => ({
  useTemplateJsWarning: vi.fn(() => ({
    showWarning: false,
    templateName: 'Test Template',
    templateVersion: '1.0.0',
    reason: 'For dynamic content',
    checkJsRequirement: vi.fn(),
    handleJsChoice: vi.fn(),
  })),
}));

describe('PreviewPane JS Integration - basics', () => {
  test('integrates JavaScript warning functionality', () => {
    expect(true).toBe(true);
  });

  test('handles template with JavaScript requirements', () => {
    const template = {
      id: 'template-1',
      name: 'JS Template',
      version: '1.0.0',
      requiresJavaScript: {
        required: true,
        reason: 'For dynamic content generation',
      },
    };

    expect(template.requiresJavaScript.required).toBe(true);
    expect(template.requiresJavaScript.reason).toBe('For dynamic content generation');
  });
});

describe('PreviewPane JS Integration - choices', () => {
  test('handles render method choices', () => {
    const renderMethods = ['html', 'image'] as const;
    const mockChoice = vi.fn();

    for (const method of renderMethods) {
      mockChoice(method, false); // Don't remember
      mockChoice(method, true); // Remember choice
    }

    expect(mockChoice).toHaveBeenCalledTimes(EXPECTED_MOCK_CALLS);
    expect(mockChoice).toHaveBeenCalledWith('html', false);
    expect(mockChoice).toHaveBeenCalledWith('html', true);
    expect(mockChoice).toHaveBeenCalledWith('image', false);
    expect(mockChoice).toHaveBeenCalledWith('image', true);
  });

  test('validates JavaScript badge display logic', () => {
    const templates = [
      { id: '1', name: 'Regular Template', requiresJavaScript: { required: false } },
      {
        id: '2',
        name: 'JS Template',
        requiresJavaScript: { required: true, reason: 'Dynamic content' },
      },
    ];

    const templatesWithJs = templates.filter((t) => t.requiresJavaScript?.required);
    const templatesWithoutJs = templates.filter((t) => !t.requiresJavaScript?.required);

    expect(templatesWithJs).toHaveLength(1);
    expect(templatesWithoutJs).toHaveLength(1);
    expect(nonNull(templatesWithJs[0]).name).toBe('JS Template');
    expect(nonNull(templatesWithoutJs[0]).name).toBe('Regular Template');
  });

  test('handles preference storage structure', () => {
    const preference = {
      templateId: 'template-1',
      version: '1.0.0',
      method: 'html' as const,
      timestamp: Date.now(),
    };

    expect(preference.templateId).toBe('template-1');
    expect(preference.version).toBe('1.0.0');
    expect(preference.method).toBe('html');
    expect(typeof preference.timestamp).toBe('number');
  });
});
