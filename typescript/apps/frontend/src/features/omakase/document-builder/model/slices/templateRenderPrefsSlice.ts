import type { StateCreator } from 'zustand';

export type RenderMethod = 'html' | 'image';

export interface TemplateRenderPref {
  version: string;
  method: RenderMethod;
}

export interface TemplateRenderPrefsSlice {
  templateRenderPrefs: Record<string, TemplateRenderPref>;
  setTemplateRenderPref: (templateId: string, version: string, method: RenderMethod) => void;
  getTemplateRenderPref: (templateId: string, version: string) => RenderMethod | null;
  clearTemplateRenderPref: (templateId: string) => void;
  clearAllTemplateRenderPrefs: () => void;
}

export const createTemplateRenderPrefsSlice: StateCreator<
  TemplateRenderPrefsSlice,
  [],
  [],
  TemplateRenderPrefsSlice
> = (
  set: Parameters<StateCreator<TemplateRenderPrefsSlice, [], [], TemplateRenderPrefsSlice>>[0],
  get: Parameters<StateCreator<TemplateRenderPrefsSlice, [], [], TemplateRenderPrefsSlice>>[1],
): TemplateRenderPrefsSlice => ({
  templateRenderPrefs: {},

  setTemplateRenderPref: (templateId: string, version: string, method: RenderMethod): void => {
    set((state) => ({
      templateRenderPrefs: {
        ...state.templateRenderPrefs,
        [templateId]: {
          version,
          method,
        },
      },
    }));
  },

  getTemplateRenderPref: (templateId: string, version: string): RenderMethod | null => {
    const pref = get().templateRenderPrefs[templateId];
    if (!pref) {
      return null;
    }

    // Only return the preference if the version matches
    if (pref.version === version) {
      return pref.method;
    }

    return null;
  },

  clearTemplateRenderPref: (templateId: string): void => {
    set((state) => {
      const newPrefs = { ...state.templateRenderPrefs };
      delete newPrefs[templateId];
      return {
        templateRenderPrefs: newPrefs,
      };
    });
  },

  clearAllTemplateRenderPrefs: (): void => {
    set({ templateRenderPrefs: {} });
  },
});
