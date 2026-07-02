export type {
  Session,
  User,
} from '@/shared/model/index.ts';

/**
 * OAuth provider identifiers. Defined locally because the generated API client
 * does not yet include the OAuth OpenAPI spec - these values mirror the backend
 * enum and are used as path segments in authorize/unlink URLs.
 */
export const OAuthProvider = {
  GOOGLE: 'google',
  GITHUB: 'github',
} as const;

export type OAuthProvider = (typeof OAuthProvider)[keyof typeof OAuthProvider];
