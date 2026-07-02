import { useState } from 'react';

/** localStorage key for persisting the remembered email address across sessions. */
const REMEMBERED_EMAIL_KEY = 'nohiki_remembered_email';

interface UseRememberMeResult {
  readonly rememberedEmail: string;
  readonly rememberMe: boolean;
  readonly handleRememberMeChange: (checked: boolean) => void;
  /** Persists the email to localStorage if remember-me is active. */
  readonly persistEmail: (email: string) => void;
}

/**
 * Manages "Remember Me" checkbox state with localStorage persistence.
 *
 * Reads the stored email on mount (for pre-filling the login form) and
 * provides a callback to persist the email on successful login.
 */
export function useRememberMe(): UseRememberMeResult {
  const rememberedEmail = localStorage.getItem(REMEMBERED_EMAIL_KEY) ?? '';

  const [rememberMe, setRememberMe] = useState(() => rememberedEmail !== '');

  const handleRememberMeChange = (checked: boolean): void => {
    setRememberMe(checked);
    if (!checked) {
      localStorage.removeItem(REMEMBERED_EMAIL_KEY);
    }
  };

  const persistEmail = (email: string): void => {
    if (rememberMe) {
      localStorage.setItem(REMEMBERED_EMAIL_KEY, email);
    }
  };

  return { rememberedEmail, rememberMe, handleRememberMeChange, persistEmail };
}
