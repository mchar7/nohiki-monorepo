import { type Context, createContext, type RefObject, useContext } from 'react';

const MainScrollRefContext: Context<RefObject<HTMLElement | null> | null> =
  createContext<RefObject<HTMLElement | null> | null>(null);

/**
 * Returns the ref attached to BaseLayout's scrollable `<main>` element.
 * Used by pages that need access to the scroll container (e.g. pull-to-refresh).
 */
function useMainScrollRef(): RefObject<HTMLElement | null> {
  const ref = useContext(MainScrollRefContext);
  if (!ref) {
    throw new Error('useMainScrollRef must be used within a MainScrollRefContext.Provider');
  }
  return ref;
}

export { MainScrollRefContext, useMainScrollRef };
