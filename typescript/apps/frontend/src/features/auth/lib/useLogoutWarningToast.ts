import { useEffect } from 'react';
import { showWarning } from '@/shared/lib';

const LOGOUT_WARNING_KEY = 'nohiki_logout_warning';

/** Show a one-shot warning toast if redirected from a failed logout (reads sessionStorage flag set by useLogout onError). */
function useLogoutWarningToast(message: string): void {
  useEffect(() => {
    if (globalThis.sessionStorage.getItem(LOGOUT_WARNING_KEY)) {
      showWarning(message);
      globalThis.sessionStorage.removeItem(LOGOUT_WARNING_KEY);
    }
  }, [message]);
}

export { useLogoutWarningToast };
