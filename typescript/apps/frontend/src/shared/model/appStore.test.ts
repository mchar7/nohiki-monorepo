import { beforeEach, describe, expect, vi } from 'vitest';
import { useAppStore } from './appStore.ts';

/** Number of pending commands added in the clearPendingCommands test */
const TEST_PENDING_COMMAND_COUNT: number = 3;

beforeEach(() => {
  vi.clearAllMocks();
  useAppStore.setState(
    {
      ...useAppStore.getInitialState(),
      pendingCommands: new Map(),
    },
    true,
  );
});

describe('appStore - UISlice', () => {
  test('toggles sidebar', () => {
    expect(useAppStore.getState().sidebarCollapsed).toBe(false);
    useAppStore.getState().toggleSidebar();
    expect(useAppStore.getState().sidebarCollapsed).toBe(true);
    useAppStore.getState().toggleSidebar();
    expect(useAppStore.getState().sidebarCollapsed).toBe(false);
  });

  test('sets sidebar collapsed state directly', () => {
    useAppStore.getState().setSidebarCollapsed(true);
    expect(useAppStore.getState().sidebarCollapsed).toBe(true);
    useAppStore.getState().setSidebarCollapsed(false);
    expect(useAppStore.getState().sidebarCollapsed).toBe(false);
  });

  test('sets theme', () => {
    expect(useAppStore.getState().theme).toBe('system');
    useAppStore.getState().setTheme('dark');
    expect(useAppStore.getState().theme).toBe('dark');
    useAppStore.getState().setTheme('light');
    expect(useAppStore.getState().theme).toBe('light');
    useAppStore.getState().setTheme('system');
    expect(useAppStore.getState().theme).toBe('system');
  });

  test('sets selected profile ID', () => {
    expect(useAppStore.getState().selectedProfileId).toBeNull();
    useAppStore.getState().setSelectedProfileId('profile-123');
    expect(useAppStore.getState().selectedProfileId).toBe('profile-123');
    useAppStore.getState().setSelectedProfileId(null);
    expect(useAppStore.getState().selectedProfileId).toBeNull();
  });
});

describe('appStore - PendingCommandsSlice', () => {
  test('adds pending command', () => {
    expect(useAppStore.getState().pendingCommands.size).toBe(0);
    useAppStore.getState().addPendingCommand('req-1', 'generate-pdf');
    expect(useAppStore.getState().pendingCommands.size).toBe(1);
    expect(useAppStore.getState().pendingCommands.has('req-1')).toBe(true);
    expect(useAppStore.getState().pendingCommands.get('req-1')?.type).toBe('generate-pdf');
  });

  test('removes pending command', () => {
    useAppStore.getState().addPendingCommand('req-1', 'generate-pdf');
    useAppStore.getState().addPendingCommand('req-2', 'render-html');
    expect(useAppStore.getState().pendingCommands.size).toBe(2);
    useAppStore.getState().removePendingCommand('req-1');
    expect(useAppStore.getState().pendingCommands.size).toBe(1);
    expect(useAppStore.getState().pendingCommands.has('req-1')).toBe(false);
    expect(useAppStore.getState().pendingCommands.has('req-2')).toBe(true);
  });

  test('clears all pending commands', () => {
    useAppStore.getState().addPendingCommand('req-1', 'type-1');
    useAppStore.getState().addPendingCommand('req-2', 'type-2');
    useAppStore.getState().addPendingCommand('req-3', 'type-3');
    expect(useAppStore.getState().pendingCommands.size).toBe(TEST_PENDING_COMMAND_COUNT);
    useAppStore.getState().clearPendingCommands();
    expect(useAppStore.getState().pendingCommands.size).toBe(0);
  });

  test('checks if command is pending', () => {
    useAppStore.getState().addPendingCommand('req-1', 'generate-pdf');
    expect(useAppStore.getState().hasPendingCommand('req-1')).toBe(true);
    expect(useAppStore.getState().hasPendingCommand('req-2')).toBe(false);
  });
});

describe('appStore - combined slices', () => {
  test('combines all slices', () => {
    const state = useAppStore.getState();

    // UI slice
    expect(state.sidebarCollapsed).toBeDefined();
    expect(state.theme).toBeDefined();
    expect(state.toggleSidebar).toBeDefined();
    expect(state.setSidebarCollapsed).toBeDefined();
    expect(state.setTheme).toBeDefined();
    expect(state.setSelectedProfileId).toBeDefined();

    // Pending commands slice
    expect(state.pendingCommands).toBeDefined();
    expect(state.addPendingCommand).toBeDefined();
    expect(state.removePendingCommand).toBeDefined();
    expect(state.clearPendingCommands).toBeDefined();
    expect(state.hasPendingCommand).toBeDefined();

    // Auth slice
    expect(state.isAuthenticated).toBeDefined();
    expect(state.login).toBeDefined();
    expect(state.logout).toBeDefined();
  });
});
