export const ROUTE_PATHS = {
  HOME: '/',

  AUTH: {
    ROOT: '/auth',
    LOGIN: '/auth/login',
    REGISTER: '/auth/register',
    OAUTH_CALLBACK: '/auth/callback',
  },

  JOBS: {
    LIST: '/jobs',
    DETAIL: '/jobs/$listingId',
    MATCHES: '/jobs/matches',
    MATCH_DETAIL: '/jobs/matches/$correlationId',
  },

  PROFILES: {
    LIST: '/profiles',
    NEW: '/profiles/new',
    DETAIL: '/profiles/$profileId',
  },

  DOCUMENTS: {
    LIST: '/documents',
    GENERATE: '/documents/generate',
    TEMPLATES: '/documents/templates',
    TEMPLATE_STUDIO: '/documents/templates/studio',
    EDITOR: '/documents/editor/$datasetId',
  },

  ACCOUNT: {
    SETTINGS: '/account',
  },

  SETTINGS: '/settings',
  LICENSES: '/licenses',
} as const;
