type AuthTransitionHandler = (userId: string | null) => void;

const AUTH_TRANSITION_STORAGE_KEY = 'nohiki_auth_transition';

interface AuthTransition {
  readonly userId: string | null;
  readonly nonce: string;
}

function publishAuthTransition(userId: string | null): void {
  try {
    if (typeof globalThis.localStorage === 'undefined') return;

    const transition: AuthTransition = {
      userId,
      nonce: `${Date.now()}:${Math.random()}`,
    };
    globalThis.localStorage.setItem(AUTH_TRANSITION_STORAGE_KEY, JSON.stringify(transition));
  } catch {
    // Cross-tab synchronization is optional and must never block the local mutation.
  }
}

function subscribeToAuthTransitions(handler: AuthTransitionHandler): () => void {
  if (typeof globalThis.addEventListener !== 'function') return (): void => undefined;

  const listener = (event: StorageEvent): void => {
    if (event.key !== AUTH_TRANSITION_STORAGE_KEY || event.newValue === null) return;

    try {
      const transition = JSON.parse(event.newValue) as Partial<AuthTransition>;
      if (transition.userId === null || typeof transition.userId === 'string') {
        handler(transition.userId);
      }
    } catch {
      // Ignore malformed values written by unrelated or older clients.
    }
  };

  globalThis.addEventListener('storage', listener);
  return (): void => globalThis.removeEventListener('storage', listener);
}

export type { AuthTransitionHandler };
export { AUTH_TRANSITION_STORAGE_KEY, publishAuthTransition, subscribeToAuthTransitions };
