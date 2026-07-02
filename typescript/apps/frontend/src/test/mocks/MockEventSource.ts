/**
 * Mock EventSource for testing SSE-based hooks and components.
 *
 * Mimics the browser EventSource API surface so tests can simulate server-sent
 * events without opening real network connections. Test helpers (simulate*) are
 * intentionally NOT part of the native EventSource interface.
 */
export class MockEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;

  // Instance copies so code referencing `es.OPEN` works too
  readonly CONNECTING = 0;
  readonly OPEN = 1;
  readonly CLOSED = 2;

  url: string;
  withCredentials: boolean;
  readyState: number = MockEventSource.CONNECTING;

  // Standard event-handler properties
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  // Named-event listeners registered via addEventListener
  private readonly listeners: Map<string, Set<(event: MessageEvent) => void>> = new Map();

  static instances: MockEventSource[] = [];

  /** Reset the instance registry between tests. */
  static reset(): void {
    MockEventSource.instances = [];
  }

  constructor(url: string | URL, eventSourceInitDict?: EventSourceInit) {
    this.url = url.toString();
    this.withCredentials = eventSourceInitDict?.withCredentials ?? false;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent) => void): void {
    if (!this.listeners.has(type)) {
      this.listeners.set(type, new Set());
    }
    this.listeners.get(type)?.add(listener);
  }

  removeEventListener(type: string, listener: (event: MessageEvent) => void): void {
    this.listeners.get(type)?.delete(listener);
  }

  close(): void {
    this.readyState = MockEventSource.CLOSED;
  }

  // Required by the EventTarget contract; no-op for our purposes.
  dispatchEvent(_event: Event): boolean {
    return true;
  }

  /** Transition to OPEN state and fire the onopen handler. */
  simulateOpen(): void {
    this.readyState = MockEventSource.OPEN;
    this.onopen?.(new Event('open'));
  }

  /** Fire onmessage with an unnamed message event carrying `data`. */
  simulateMessage(data: string): void {
    this.onmessage?.(new MessageEvent('message', { data }));
  }

  /**
   * Fire all addEventListener listeners registered for `type`, passing `data`
   * as the event's data payload. Mirrors how browsers dispatch named SSE events.
   */
  simulateEvent(type: string, data: string): void {
    const event = new MessageEvent(type, { data });
    const listeners = this.listeners.get(type);
    if (listeners) {
      for (const listener of listeners) {
        listener(event);
      }
    }
  }

  /** Fire onerror to simulate a connection error. */
  simulateError(): void {
    this.onerror?.(new Event('error'));
  }
}
