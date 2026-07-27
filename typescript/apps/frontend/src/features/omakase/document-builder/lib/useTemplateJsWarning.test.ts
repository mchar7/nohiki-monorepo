import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, vi } from 'vitest';
import { useTemplateJsWarning } from './useTemplateJsWarning.ts';

type RenderMethod = 'html' | 'image';

const JS_TEMPLATE = '<div><script>alert(1)</script></div>';
const PLAIN_TEMPLATE = '<div>Hello</div>';

interface CurrentTemplate {
  id: string;
  display_name: string;
  version: string;
}

// Mirrors templateRenderPrefsSlice: one entry per template, read only hits on a version match.
const prefs = new Map<string, { version: string; method: RenderMethod }>();

const mockState = {
  currentTemplate: undefined as CurrentTemplate | undefined,
  getTemplateRenderPref: (templateId: string, version: string): RenderMethod | null => {
    const pref = prefs.get(templateId);
    return pref && pref.version === version ? pref.method : null;
  },
  setTemplateRenderPref: (templateId: string, version: string, method: RenderMethod): void => {
    prefs.set(templateId, { version, method });
  },
};

vi.mock('../model/index.ts', () => ({
  useDocumentBuilderStore: (selector: (state: typeof mockState) => unknown) => selector(mockState),
}));

/** Renders the hook for a template and returns its handle plus the render-choice spy. */
function setup(template: CurrentTemplate) {
  mockState.currentTemplate = template;
  const onRenderChoice = vi.fn();
  const { result } = renderHook(() => useTemplateJsWarning(template.id, onRenderChoice));
  return { result, onRenderChoice };
}

beforeEach(() => {
  prefs.clear();
  mockState.currentTemplate = undefined;
});

describe('useTemplateJsWarning', () => {
  test('warns once for a JavaScript template, then honours the remembered choice', () => {
    const { result, onRenderChoice } = setup({
      id: 'tpl-remember',
      display_name: 'Chart',
      version: '2.1',
    });

    let warned = false;
    act(() => {
      warned = result.current.checkJsRequirement(undefined, JS_TEMPLATE);
    });
    expect(warned).toBe(true);
    expect(result.current.showWarning).toBe(true);
    expect(result.current.templateName).toBe('Chart');
    expect(result.current.templateVersion).toBe('2.1');

    act(() => {
      result.current.handleJsChoice('image', true);
    });
    expect(result.current.showWarning).toBe(false);

    act(() => {
      warned = result.current.checkJsRequirement(undefined, JS_TEMPLATE);
    });
    expect(warned).toBe(false);
    expect(onRenderChoice).toHaveBeenLastCalledWith('image');
  });

  // The stored version is a key component. Writing it under a normalised default while
  // reading it under the raw value silently loses every remembered choice.
  test('honours a remembered choice for a template with an empty version string', () => {
    const { result, onRenderChoice } = setup({
      id: 'tpl-empty-version',
      display_name: 'Legacy',
      version: '',
    });

    act(() => {
      result.current.checkJsRequirement(undefined, JS_TEMPLATE);
    });
    act(() => {
      result.current.handleJsChoice('html', true);
    });

    let warned = true;
    act(() => {
      warned = result.current.checkJsRequirement(undefined, JS_TEMPLATE);
    });
    expect(warned).toBe(false);
    expect(onRenderChoice).toHaveBeenLastCalledWith('html');
  });

  test('re-prompts when the remembered choice belongs to a different version', () => {
    const { result } = setup({ id: 'tpl-versioned', display_name: 'Chart', version: '1.0' });

    act(() => {
      result.current.checkJsRequirement(undefined, JS_TEMPLATE);
    });
    act(() => {
      result.current.handleJsChoice('image', true);
    });

    const bumped = setup({ id: 'tpl-versioned', display_name: 'Chart', version: '2.0' });
    let warned = false;
    act(() => {
      warned = bumped.result.current.checkJsRequirement(undefined, JS_TEMPLATE);
    });
    expect(warned).toBe(true);
    expect(bumped.onRenderChoice).not.toHaveBeenCalled();
  });

  test('suppresses the warning for a session-only choice without persisting it', () => {
    const { result } = setup({ id: 'tpl-session', display_name: 'Chart', version: '1.0' });

    act(() => {
      result.current.checkJsRequirement(undefined, JS_TEMPLATE);
    });
    act(() => {
      result.current.handleJsChoice('html', false);
    });

    expect(prefs.has('tpl-session')).toBe(false);

    let warned = true;
    act(() => {
      warned = result.current.checkJsRequirement(undefined, JS_TEMPLATE);
    });
    expect(warned).toBe(false);
  });

  test('keeps remembered choices separate per template', () => {
    const first = setup({ id: 'tpl-a', display_name: 'A', version: '1.0' });
    act(() => {
      first.result.current.checkJsRequirement(undefined, JS_TEMPLATE);
    });
    act(() => {
      first.result.current.handleJsChoice('image', true);
    });

    const second = setup({ id: 'tpl-b', display_name: 'B', version: '1.0' });
    let warned = false;
    act(() => {
      warned = second.result.current.checkJsRequirement(undefined, JS_TEMPLATE);
    });
    expect(warned).toBe(true);
    expect(second.onRenderChoice).not.toHaveBeenCalled();
  });

  test('does not warn for a template without JavaScript', () => {
    const { result } = setup({ id: 'tpl-plain', display_name: 'Plain', version: '1.0' });

    let warned = true;
    act(() => {
      warned = result.current.checkJsRequirement(undefined, PLAIN_TEMPLATE);
    });
    expect(warned).toBe(false);
    expect(result.current.showWarning).toBe(false);
  });

  test('reports no requirement when no template is loaded', () => {
    mockState.currentTemplate = undefined;
    const { result } = renderHook(() => useTemplateJsWarning('tpl-missing'));

    let warned = true;
    act(() => {
      warned = result.current.checkJsRequirement(undefined, JS_TEMPLATE);
    });
    expect(warned).toBe(false);
  });
});
