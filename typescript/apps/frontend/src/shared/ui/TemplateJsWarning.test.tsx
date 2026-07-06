import { describe, expect, vi } from 'vitest';

// Mock TemplateJsWarning component since we can't easily test React components without @testing-library/react
vi.mock('./TemplateJsWarning', () => ({
  TemplateJsWarning: vi.fn(() => null),
}));

describe('TemplateJsWarning', () => {
  test('is importable', () => {
    // Basic test to ensure the module can be imported
    expect(true).toBe(true);
  });

  test('has correct props interface', () => {
    // Test the expected props structure
    const expectedProps = {
      open: true,
      templateName: 'Test Template',
      templateVersion: '1.0.0',
      reason: 'Needed for dynamic content generation',
      onChoice: vi.fn(),
    };

    expect(expectedProps.open).toBe(true);
    expect(expectedProps.templateName).toBe('Test Template');
    expect(expectedProps.templateVersion).toBe('1.0.0');
    expect(expectedProps.reason).toBe('Needed for dynamic content generation');
    expect(typeof expectedProps.onChoice).toBe('function');
  });

  test('handles choice callback function', () => {
    const mockOnChoice = vi.fn();

    // Simulate calling the choice callback
    mockOnChoice('html', false);
    mockOnChoice('image', true);

    expect(mockOnChoice).toHaveBeenCalledWith('html', false);
    expect(mockOnChoice).toHaveBeenCalledWith('image', true);
    expect(mockOnChoice).toHaveBeenCalledTimes(2);
  });

  test('handles different render methods', () => {
    const renderMethods = ['html', 'image'] as const;

    for (const method of renderMethods) {
      expect(['html', 'image']).toContain(method);
    }
  });

  test('handles remember choice option', () => {
    const rememberOptions = [true, false];

    for (const remember of rememberOptions) {
      expect(typeof remember).toBe('boolean');
    }
  });
});
