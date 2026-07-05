/**
 * Local template store with IndexedDB persistence.
 * Handles all local template CRUD operations.
 */

import { nanoid } from 'nanoid';
import { create } from 'zustand';
import { subscribeWithSelector } from 'zustand/middleware';
import { templatePersistence } from '@/shared/lib/persistence/index.ts';
import type {
  CreateTemplateInput,
  LocalTemplate,
  TemplateMetadata,
  UpdateTemplateInput,
} from '@/shared/model/template.types.ts';
import { DEFAULT_PAGE_SIZE } from '@/shared/model/template.types.ts';

interface TemplateState {
  templates: LocalTemplate[];
  templateIndex: Map<string, LocalTemplate>;
  selectedTemplateId: string | null;
  isLoading: boolean;
  isInitialized: boolean;
  error: string | null;
}

interface TemplateActions {
  initialize: () => Promise<void>;
  create: (input: CreateTemplateInput) => Promise<LocalTemplate>;
  update: (id: string, input: UpdateTemplateInput) => Promise<LocalTemplate | null>;
  delete: (id: string) => Promise<void>;
  clone: (id: string, newName?: string) => Promise<LocalTemplate | null>;
  select: (id: string | null) => void;
  getById: (id: string) => LocalTemplate | undefined;
  importTemplates: (templates: CreateTemplateInput[]) => Promise<LocalTemplate[]>;
  clearAll: () => Promise<void>;
}

type TemplateStore = TemplateState & TemplateActions;
type SetFn = (
  partial: Partial<TemplateState> | ((state: TemplateState) => Partial<TemplateState>),
) => void;
type GetFn = () => TemplateStore;

const initialState: TemplateState = {
  templates: [],
  templateIndex: new Map(),
  selectedTemplateId: null,
  isLoading: false,
  isInitialized: false,
  error: null,
};

/** Build a new template record from user input. */
function buildTemplate(input: CreateTemplateInput): LocalTemplate {
  const now = new Date().toISOString();
  return {
    id: nanoid(),
    metadata: {
      ...input.metadata,
      pageSize: input.metadata.pageSize ?? DEFAULT_PAGE_SIZE,
    },
    content: input.content,
    schemaId: input.schemaId ?? null,
    createdAt: now,
    updatedAt: now,
    version: 1,
    syncStatus: 'local-only',
  };
}

/** Merge update input into an existing template. */
function applyTemplateUpdate(existing: LocalTemplate, input: UpdateTemplateInput): LocalTemplate {
  return {
    ...existing,
    metadata: input.metadata ? { ...existing.metadata, ...input.metadata } : existing.metadata,
    content: input.content ?? existing.content,
    schemaId: typeof input.schemaId === 'undefined' ? existing.schemaId : input.schemaId,
    updatedAt: new Date().toISOString(),
    version: existing.version + 1,
    syncStatus: existing.remoteId ? 'pending-sync' : 'local-only',
  };
}

/** Immutably add a template to state. */
function addTemplateToState(
  state: TemplateState,
  template: LocalTemplate,
): Pick<TemplateState, 'templates' | 'templateIndex'> {
  const newIndex = new Map(state.templateIndex);
  newIndex.set(template.id, template);
  return { templates: [...state.templates, template], templateIndex: newIndex };
}

/** Immutably replace a single template in the store state. */
function replaceTemplateInState(
  state: TemplateState,
  id: string,
  updated: LocalTemplate,
): Pick<TemplateState, 'templates' | 'templateIndex'> {
  const newIndex = new Map(state.templateIndex);
  newIndex.set(id, updated);
  return {
    templates: state.templates.map((t) => (t.id === id ? updated : t)),
    templateIndex: newIndex,
  };
}

/** Remove a template from state. */
function removeTemplateFromState(
  state: TemplateState,
  id: string,
): Pick<TemplateState, 'templates' | 'templateIndex' | 'selectedTemplateId'> {
  const newIndex = new Map(state.templateIndex);
  newIndex.delete(id);
  return {
    templates: state.templates.filter((t) => t.id !== id),
    templateIndex: newIndex,
    selectedTemplateId: state.selectedTemplateId === id ? null : state.selectedTemplateId,
  };
}

/** Initialize from IndexedDB. */
async function handleInitialize(set: SetFn, get: GetFn): Promise<void> {
  if (get().isInitialized) {
    return;
  }
  set({ isLoading: true, error: null });
  try {
    const templates = await templatePersistence.getAll();
    const templateIndex = new Map(templates.map((t) => [t.id, t]));
    set({ templates, templateIndex, isLoading: false, isInitialized: true });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to load templates';
    set({ error: message, isLoading: false, isInitialized: true });
  }
}

/** Create and persist a new template. */
async function handleCreate(set: SetFn, input: CreateTemplateInput): Promise<LocalTemplate> {
  const template = buildTemplate(input);
  await templatePersistence.set(template);
  set((state) => addTemplateToState(state, template));
  return template;
}

/** Clone a template with an optional new name. */
function handleClone(
  get: GetFn,
  id: string,
  newName?: string,
): Promise<LocalTemplate | null> | null {
  const { templateIndex, create: createTemplate } = get();
  const source = templateIndex.get(id);
  if (!source) {
    return null;
  }
  const clonedMetadata: TemplateMetadata = {
    ...source.metadata,
    name: newName ?? `${source.metadata.name} (Copy)`,
  };
  return createTemplate({
    metadata: clonedMetadata,
    content: source.content,
    schemaId: source.schemaId,
  });
}

const useTemplateStore = create<TemplateStore>()(
  subscribeWithSelector((set, get) => ({
    ...initialState,
    initialize: () => handleInitialize(set, get),
    create: (input: CreateTemplateInput) => handleCreate(set, input),
    update: async (id: string, input: UpdateTemplateInput) => {
      const existing = get().templateIndex.get(id);
      if (!existing) {
        return null;
      }
      const updated = applyTemplateUpdate(existing, input);
      await templatePersistence.set(updated);
      set((state) => replaceTemplateInState(state, id, updated));
      return updated;
    },
    delete: async (id: string) => {
      await templatePersistence.delete(id);
      set((state) => removeTemplateFromState(state, id));
    },
    clone: (id: string, newName?: string) => Promise.resolve(handleClone(get, id, newName)),
    select: (id: string | null) => set({ selectedTemplateId: id }),
    getById: (id: string) => get().templateIndex.get(id),
    importTemplates: (inputs: CreateTemplateInput[]) => {
      const { create: createTemplate } = get();
      return Promise.all(inputs.map((input) => createTemplate(input)));
    },
    clearAll: async () => {
      await templatePersistence.clear();
      set({ templates: [], templateIndex: new Map(), selectedTemplateId: null });
    },
  })),
);

export { useTemplateStore };
