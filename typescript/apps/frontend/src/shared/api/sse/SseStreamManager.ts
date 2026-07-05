/**
 * Generic Server-Sent Events multiplexer.
 *
 * Single Responsibility: manage one EventSource connection and a
 * reference-counted set of subscribers. Opens on first subscribe, closes
 * on last unsubscribe. The connection is shared by every subscriber so a
 * page can have N consumers of the same stream without N tabs of network
 * traffic.
 *
 * The manager is intentionally domain-agnostic: it knows about a URL and
 * an event name and nothing else. Domain layers (e.g. `entities/document`)
 * wrap this primitive with their own factory that holds the configured
 * instance and exposes a domain-typed API to the rest of the codebase.
 *
 * Each subscriber receives every event delivered on the configured
 * channel; payload-level filtering (request_id, etc.) is the subscriber's
 * responsibility.
 */

type SseEventHandler = (event: MessageEvent) => void;

interface SseStreamConfig {
  readonly url: string;
  readonly eventName: string;
  readonly withCredentials?: boolean;
}

export class SseStreamManager {
  private readonly config: SseStreamConfig;
  private readonly handlers: Set<SseEventHandler> = new Set();
  private eventSource: EventSource | null = null;

  constructor(config: SseStreamConfig) {
    this.config = config;
  }

  /**
   * Subscribe a handler for events on the configured channel. The first
   * subscriber opens the underlying EventSource; the last to unsubscribe
   * closes it. Returns an unsubscribe function.
   */
  subscribe(handler: SseEventHandler): () => void {
    this.handlers.add(handler);

    if (!this.eventSource) {
      this.connect();
    }

    return (): void => {
      this.handlers.delete(handler);
      if (this.handlers.size === 0) {
        this.disconnect();
      }
    };
  }

  /** Number of active subscribers. */
  get subscriberCount(): number {
    return this.handlers.size;
  }

  /** Whether the underlying EventSource is currently open. */
  get isOpen(): boolean {
    return this.eventSource !== null;
  }

  /**
   * Tear everything down: close the underlying EventSource and drop all
   * handlers. Intended for tests or full-app cleanup; production code
   * should rely on subscriber lifecycle via `subscribe()`.
   */
  destroy(): void {
    this.disconnect();
    this.handlers.clear();
  }

  private connect(): void {
    this.eventSource = new EventSource(this.config.url, {
      withCredentials: this.config.withCredentials ?? true,
    });

    this.eventSource.addEventListener(this.config.eventName, (event: MessageEvent): void => {
      for (const handler of this.handlers) {
        handler(event);
      }
    });

    // EventSource auto-reconnects natively on transient errors.
    // Calling close() here would kill that built-in recovery mechanism.
    this.eventSource.onerror = (): void => {
      // Intentionally empty: EventSource auto-reconnects natively.
    };
  }

  private disconnect(): void {
    this.eventSource?.close();
    this.eventSource = null;
  }
}
