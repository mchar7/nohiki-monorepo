import { useEffect } from 'react';

const APP_NAME = 'Nohiki';

export function useDocumentTitle(title?: string): void {
  useEffect(() => {
    const previousTitle = document.title;
    document.title = title ? `${title} | ${APP_NAME}` : APP_NAME;
    return (): void => {
      document.title = previousTitle;
    };
  }, [title]);
}
