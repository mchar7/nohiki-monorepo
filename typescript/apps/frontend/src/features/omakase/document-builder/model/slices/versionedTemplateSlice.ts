import type { StateCreator } from 'zustand';
import type { TemplateFamilyResponse, TemplateResponse } from '@/shared/api';

type SetFn = Parameters<StateCreator<VersionedTemplateSlice, [], [], VersionedTemplateSlice>>[0];

export interface VersionedTemplateSlice {
  templateFamilies: TemplateFamilyResponse[];
  selectedFamilyId: string | null;
  selectedVersionId: string | null;
  currentTemplate: TemplateResponse | null;

  setTemplateFamilies: (families: TemplateFamilyResponse[]) => void;
  addTemplateFamily: (family: TemplateFamilyResponse) => void;
  updateTemplateFamily: (family: TemplateFamilyResponse) => void;
  removeTemplateFamily: (familyId: string) => void;

  setSelectedFamily: (familyId: string | null) => void;
  setSelectedVersion: (versionId: string | null) => void;
  setCurrentTemplate: (template: TemplateResponse | null) => void;

  clearSelection: () => void;
}

export const createVersionedTemplateSlice: StateCreator<
  VersionedTemplateSlice,
  [],
  [],
  VersionedTemplateSlice
> = (set: SetFn): VersionedTemplateSlice => ({
  templateFamilies: [],
  selectedFamilyId: null,
  selectedVersionId: null,
  currentTemplate: null,

  setTemplateFamilies: (families: TemplateFamilyResponse[]): void =>
    set({ templateFamilies: families }),

  addTemplateFamily: (family: TemplateFamilyResponse): void =>
    set((state) => ({
      templateFamilies: [...state.templateFamilies, family],
    })),

  updateTemplateFamily: (family: TemplateFamilyResponse): void =>
    set((state) => ({
      templateFamilies: state.templateFamilies.map((f) => {
        if (f.id === family.id) {
          return family;
        }
        return f;
      }),
    })),

  removeTemplateFamily: (familyId: string): void =>
    set((state) => {
      const isFamilySelected = state.selectedFamilyId === familyId;
      return {
        templateFamilies: state.templateFamilies.filter((f) => f.id !== familyId),
        selectedFamilyId: isFamilySelected ? null : state.selectedFamilyId,
        selectedVersionId: isFamilySelected ? null : state.selectedVersionId,
        currentTemplate: isFamilySelected ? null : state.currentTemplate,
      };
    }),

  setSelectedFamily: (familyId: string | null): void =>
    set({
      selectedFamilyId: familyId,
      selectedVersionId: null,
      currentTemplate: null,
    }),

  setSelectedVersion: (versionId: string | null): void =>
    set({
      selectedVersionId: versionId,
      currentTemplate: null,
    }),

  setCurrentTemplate: (template: TemplateResponse | null): void => {
    set({
      currentTemplate: template,
      selectedVersionId: template?.id !== undefined ? template.id : null,
    });
  },

  clearSelection: (): void =>
    set({
      selectedFamilyId: null,
      selectedVersionId: null,
      currentTemplate: null,
    }),
});
