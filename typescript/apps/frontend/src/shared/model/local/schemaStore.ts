/**
 * Local schema store with IndexedDB persistence.
 * Handles all local schema CRUD operations.
 */

import { nanoid } from 'nanoid';
import { create } from 'zustand';
import { subscribeWithSelector } from 'zustand/middleware';
import { schemaPersistence } from '@/shared/lib/persistence/index.ts';
import type {
  CreateSchemaInput,
  JSONSchemaDefinition,
  LocalSchema,
  SchemaMetadata,
  UpdateSchemaInput,
} from '@/shared/model/schema.types.ts';

interface SchemaState {
  schemas: LocalSchema[];
  schemaIndex: Map<string, LocalSchema>;
  selectedSchemaId: string | null;
  isLoading: boolean;
  isInitialized: boolean;
  error: string | null;
}

interface SchemaActions {
  initialize: () => Promise<void>;
  create: (input: CreateSchemaInput) => Promise<LocalSchema>;
  update: (id: string, input: UpdateSchemaInput) => Promise<LocalSchema | null>;
  delete: (id: string) => Promise<void>;
  clone: (id: string, newName?: string) => Promise<LocalSchema | null>;
  select: (id: string | null) => void;
  getById: (id: string) => LocalSchema | undefined;
  importSchemas: (schemas: CreateSchemaInput[]) => Promise<LocalSchema[]>;
  clearAll: () => Promise<void>;
}

type SchemaStore = SchemaState & SchemaActions;
type SetFn = (
  partial: Partial<SchemaState> | ((state: SchemaState) => Partial<SchemaState>),
) => void;
type GetFn = () => SchemaStore;

const initialState: SchemaState = {
  schemas: [],
  schemaIndex: new Map(),
  selectedSchemaId: null,
  isLoading: false,
  isInitialized: false,
  error: null,
};

// Default empty schema for new schemas
const DEFAULT_SCHEMA: JSONSchemaDefinition = {
  $schema: 'http://json-schema.org/draft-07/schema#',
  type: 'object',
  properties: {},
  required: [],
};

/** Build a new schema record from user input. */
function buildSchema(input: CreateSchemaInput): LocalSchema {
  const now = new Date().toISOString();
  return {
    id: nanoid(),
    metadata: input.metadata,
    jsonSchema: input.jsonSchema,
    createdAt: now,
    updatedAt: now,
    version: 1,
    syncStatus: 'local-only',
  };
}

/** Merge update input into an existing schema. */
function applySchemaUpdate(existing: LocalSchema, input: UpdateSchemaInput): LocalSchema {
  return {
    ...existing,
    metadata: input.metadata ? { ...existing.metadata, ...input.metadata } : existing.metadata,
    jsonSchema: input.jsonSchema ?? existing.jsonSchema,
    updatedAt: new Date().toISOString(),
    version: existing.version + 1,
    syncStatus: existing.remoteId ? 'pending-sync' : 'local-only',
  };
}

/** Immutably add a schema to state. */
function addSchemaToState(
  state: SchemaState,
  schema: LocalSchema,
): Pick<SchemaState, 'schemas' | 'schemaIndex'> {
  const newIndex = new Map(state.schemaIndex);
  newIndex.set(schema.id, schema);
  return { schemas: [...state.schemas, schema], schemaIndex: newIndex };
}

/** Immutably replace a single schema in the store state. */
function replaceSchemaInState(
  state: SchemaState,
  id: string,
  updated: LocalSchema,
): Pick<SchemaState, 'schemas' | 'schemaIndex'> {
  const newIndex = new Map(state.schemaIndex);
  newIndex.set(id, updated);
  return {
    schemas: state.schemas.map((s) => (s.id === id ? updated : s)),
    schemaIndex: newIndex,
  };
}

/** Remove a schema from state. */
function removeSchemaFromState(
  state: SchemaState,
  id: string,
): Pick<SchemaState, 'schemas' | 'schemaIndex' | 'selectedSchemaId'> {
  const newIndex = new Map(state.schemaIndex);
  newIndex.delete(id);
  return {
    schemas: state.schemas.filter((s) => s.id !== id),
    schemaIndex: newIndex,
    selectedSchemaId: state.selectedSchemaId === id ? null : state.selectedSchemaId,
  };
}

/** Initialize from IndexedDB. */
async function handleInitialize(set: SetFn, get: GetFn): Promise<void> {
  if (get().isInitialized) {
    return;
  }
  set({ isLoading: true, error: null });
  try {
    const schemas = await schemaPersistence.getAll();
    const schemaIndex = new Map(schemas.map((s) => [s.id, s]));
    set({ schemas, schemaIndex, isLoading: false, isInitialized: true });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to load schemas';
    set({ error: message, isLoading: false, isInitialized: true });
  }
}

/** Create and persist a new schema. */
async function handleCreate(set: SetFn, input: CreateSchemaInput): Promise<LocalSchema> {
  const schema = buildSchema(input);
  await schemaPersistence.set(schema);
  set((state) => addSchemaToState(state, schema));
  return schema;
}

/** Clone a schema with an optional new name. */
function handleClone(get: GetFn, id: string, newName?: string): Promise<LocalSchema | null> | null {
  const { schemaIndex, create: createSchema } = get();
  const source = schemaIndex.get(id);
  if (!source) {
    return null;
  }
  const clonedMetadata: SchemaMetadata = {
    ...source.metadata,
    name: newName ?? `${source.metadata.name} (Copy)`,
  };
  return createSchema({
    metadata: clonedMetadata,
    jsonSchema: structuredClone(source.jsonSchema),
  });
}

const useSchemaStore = create<SchemaStore>()(
  subscribeWithSelector((set, get) => ({
    ...initialState,
    initialize: () => handleInitialize(set, get),
    create: (input: CreateSchemaInput) => handleCreate(set, input),
    update: async (id: string, input: UpdateSchemaInput) => {
      const existing = get().schemaIndex.get(id);
      if (!existing) {
        return null;
      }
      const updated = applySchemaUpdate(existing, input);
      await schemaPersistence.set(updated);
      set((state) => replaceSchemaInState(state, id, updated));
      return updated;
    },
    delete: async (id: string) => {
      await schemaPersistence.delete(id);
      set((state) => removeSchemaFromState(state, id));
    },
    clone: (id: string, newName?: string) => Promise.resolve(handleClone(get, id, newName)),
    select: (id: string | null) => set({ selectedSchemaId: id }),
    getById: (id: string) => get().schemaIndex.get(id),
    importSchemas: (inputs: CreateSchemaInput[]) => {
      const { create: createSchema } = get();
      return Promise.all(inputs.map((input) => createSchema(input)));
    },
    clearAll: async () => {
      await schemaPersistence.clear();
      set({ schemas: [], schemaIndex: new Map(), selectedSchemaId: null });
    },
  })),
);

export { DEFAULT_SCHEMA, useSchemaStore };
