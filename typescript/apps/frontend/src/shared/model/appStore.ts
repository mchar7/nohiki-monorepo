/**
 * Combined Application Store
 *
 * Zustand store combining all feature slices for global state management.
 * Uses persist middleware for localStorage persistence.
 *
 * Design decisions:
 * - Slices are composed using the slice pattern for modularity
 * - Only non-sensitive data is persisted
 * - Uses partialize to exclude auth-related data from persistence
 */
import { create, type UseBoundStore } from 'zustand';
import { createJSONStorage, devtools, persist } from 'zustand/middleware';
import type { StoreApi } from 'zustand/vanilla';
import { STORAGE_KEYS } from '@/shared/api/config.ts';
import { type AuthSlice, createAuthSlice } from './authSlice.ts';

interface UISlice {
  sidebarCollapsed: boolean;
  theme: 'light' | 'dark' | 'system';
  selectedProfileId: string | null;
  density: 'compact' | 'comfortable' | 'spacious';
  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  setTheme: (theme: 'light' | 'dark' | 'system') => void;
  setSelectedProfileId: (id: string | null) => void;
  setDensity: (density: 'compact' | 'comfortable' | 'spacious') => void;
}

const createUISlice = (
  set: (partial: Partial<UISlice> | ((state: UISlice) => Partial<UISlice>)) => void,
): UISlice => ({
  sidebarCollapsed: false,
  theme: 'system',
  selectedProfileId: null,
  density: 'comfortable',

  toggleSidebar: (): void => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),

  setSidebarCollapsed: (collapsed: boolean): void => set({ sidebarCollapsed: collapsed }),

  setTheme: (theme: 'light' | 'dark' | 'system'): void => set({ theme }),

  setSelectedProfileId: (id: string | null): void => set({ selectedProfileId: id }),

  setDensity: (density: 'compact' | 'comfortable' | 'spacious'): void => set({ density }),
});

interface PendingCommandsSlice {
  pendingCommands: Map<string, { type: string; startedAt: number }>;
  addPendingCommand: (requestId: string, type: string) => void;
  removePendingCommand: (requestId: string) => void;
  clearPendingCommands: () => void;
  hasPendingCommand: (requestId: string) => boolean;
}

const createPendingCommandsSlice = (
  set: (
    partial:
      | Partial<PendingCommandsSlice>
      | ((state: PendingCommandsSlice) => Partial<PendingCommandsSlice>),
  ) => void,
  get: () => PendingCommandsSlice,
): PendingCommandsSlice => ({
  pendingCommands: new Map(),

  addPendingCommand: (requestId: string, type: string): void =>
    set((state) => {
      const newMap = new Map(state.pendingCommands);
      newMap.set(requestId, { type, startedAt: Date.now() });
      return { pendingCommands: newMap };
    }),

  removePendingCommand: (requestId: string): void =>
    set((state) => {
      const newMap = new Map(state.pendingCommands);
      newMap.delete(requestId);
      return { pendingCommands: newMap };
    }),

  clearPendingCommands: (): void => set({ pendingCommands: new Map() }),

  hasPendingCommand: (requestId: string): boolean => get().pendingCommands.has(requestId),
});

type AppStore = AuthSlice & UISlice & PendingCommandsSlice;

const useAppStore: UseBoundStore<StoreApi<AppStore>> = create<AppStore>()(
  devtools(
    persist(
      (set, get, api) => ({
        ...createAuthSlice(set as never, get as never, api as never),
        ...createUISlice(set as never),
        ...createPendingCommandsSlice(set as never, get as never),
      }),
      {
        name: STORAGE_KEYS.AUTH_STATE,
        storage: createJSONStorage(() => localStorage),
        partialize: (state: AppStore) => ({
          sidebarCollapsed: state.sidebarCollapsed,
          theme: state.theme,
          selectedProfileId: state.selectedProfileId,
          density: state.density,
        }),
      },
    ),
    { name: 'NohikiAppStore' },
  ),
);

export type { AppStore };
export { useAppStore };
