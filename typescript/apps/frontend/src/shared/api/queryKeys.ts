/**
 * Query keys for TanStack Query cache management.
 *
 * Centralized key definitions ensure consistent cache invalidation
 * and prevent typos across the application.
 */
export const queryKeys = {
  // Auth & Session
  session: ['session'] as const,
  account: ['account'] as const,

  // Profiles
  profiles: {
    all: ['profiles'] as const,
    list: () => [...queryKeys.profiles.all, 'list'] as const,
    detail: (id: string) => [...queryKeys.profiles.all, 'detail', id] as const,
    importance: (id: string) => [...queryKeys.profiles.all, id, 'importance'] as const,
    resolvedImportance: (id: string) =>
      [...queryKeys.profiles.all, id, 'resolved-importance'] as const,
  },

  // Job Listings
  listings: {
    all: ['listings'] as const,
    list: (filters?: Record<string, unknown>) =>
      [...queryKeys.listings.all, 'list', filters] as const,
    detail: (id: string) => [...queryKeys.listings.all, 'detail', id] as const,
  },

  // Correlations (Job Matches)
  correlations: {
    all: ['correlations'] as const,
    mine: (filters?: Record<string, unknown>) =>
      [...queryKeys.correlations.all, 'mine', filters] as const,
    detail: (id: string) => [...queryKeys.correlations.all, 'detail', id] as const,
  },

  // Templates
  templates: {
    all: ['templates'] as const,
    families: () => [...queryKeys.templates.all, 'families'] as const,
    family: (id: string) => [...queryKeys.templates.all, 'families', id] as const,
    versions: (familyId: string) =>
      [...queryKeys.templates.all, 'families', familyId, 'versions'] as const,
    version: (familyId: string, version: number) =>
      [...queryKeys.templates.all, 'families', familyId, 'versions', version] as const,
    content: (familyId: string, version: number) =>
      [...queryKeys.templates.all, 'families', familyId, 'versions', version, 'content'] as const,
  },

  // Schemas
  schemas: {
    all: ['schemas'] as const,
    families: () => [...queryKeys.schemas.all, 'families'] as const,
    family: (id: string) => [...queryKeys.schemas.all, 'families', id] as const,
    versions: (familyId: string) =>
      [...queryKeys.schemas.all, 'families', familyId, 'versions'] as const,
  },

  // Documents
  documents: {
    all: ['documents'] as const,
    list: () => [...queryKeys.documents.all, 'list'] as const,
    status: (requestId: string) => [...queryKeys.documents.all, 'status', requestId] as const,
  },

  // Attachments
  attachments: {
    all: ['attachments'] as const,
    list: () => [...queryKeys.attachments.all, 'list'] as const,
    detail: (id: string) => [...queryKeys.attachments.all, 'detail', id] as const,
  },
} as const;
