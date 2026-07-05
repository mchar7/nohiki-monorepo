import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import { nonNull } from '@/shared/test-utils';
import { MockEventSource } from '@/test/mocks/MockEventSource';
import { SseStreamManager } from './SseStreamManager.ts';

const DEFAULT_CONFIG = {
  url: '/test/events',
  eventName: 'test_event',
} as const;

describe('SseStreamManager connection lifecycle', () => {
  beforeEach(() => {
    MockEventSource.reset();
    vi.stubGlobal('EventSource', MockEventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test('opens an EventSource on first subscribe', () => {
    const stream = new SseStreamManager(DEFAULT_CONFIG);
    expect(MockEventSource.instances).toHaveLength(0);

    stream.subscribe(vi.fn());

    expect(MockEventSource.instances).toHaveLength(1);
    expect(nonNull(MockEventSource.instances[0]).url).toBe('/test/events');
    expect(nonNull(MockEventSource.instances[0]).withCredentials).toBe(true);
    const requestUrl = new URL(
      nonNull(MockEventSource.instances[0]).url,
      'https://app.nohiki.test',
    );
    expect(requestUrl.search).toBe('');
    expect(requestUrl.username).toBe('');
    expect(requestUrl.password).toBe('');
  });

  test('respects withCredentials override', () => {
    const stream = new SseStreamManager({ ...DEFAULT_CONFIG, withCredentials: false });
    stream.subscribe(vi.fn());

    expect(nonNull(MockEventSource.instances[0]).withCredentials).toBe(false);
  });

  test('does NOT open a second EventSource for additional subscribers', () => {
    const stream = new SseStreamManager(DEFAULT_CONFIG);
    stream.subscribe(vi.fn());
    stream.subscribe(vi.fn());
    stream.subscribe(vi.fn());

    expect(MockEventSource.instances).toHaveLength(1);
  });
});

describe('SseStreamManager subscriber lifecycle', () => {
  beforeEach(() => {
    MockEventSource.reset();
    vi.stubGlobal('EventSource', MockEventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test('closes EventSource when the last subscriber unsubscribes', () => {
    const stream = new SseStreamManager(DEFAULT_CONFIG);

    const unsub1 = stream.subscribe(vi.fn());
    const unsub2 = stream.subscribe(vi.fn());

    const [es] = MockEventSource.instances as [MockEventSource];
    expect(es.readyState).not.toBe(MockEventSource.CLOSED);

    unsub1();
    // Still one subscriber, connection stays open
    expect(es.readyState).not.toBe(MockEventSource.CLOSED);

    unsub2();
    // Last subscriber gone, connection closed
    expect(es.readyState).toBe(MockEventSource.CLOSED);
  });

  test('tracks subscriberCount accurately', () => {
    const stream = new SseStreamManager(DEFAULT_CONFIG);

    expect(stream.subscriberCount).toBe(0);

    const unsub1 = stream.subscribe(vi.fn());
    expect(stream.subscriberCount).toBe(1);

    const unsub2 = stream.subscribe(vi.fn());
    expect(stream.subscriberCount).toBe(2);

    unsub1();
    expect(stream.subscriberCount).toBe(1);

    unsub2();
    expect(stream.subscriberCount).toBe(0);
  });

  test('exposes isOpen reflecting connection state', () => {
    const stream = new SseStreamManager(DEFAULT_CONFIG);
    expect(stream.isOpen).toBe(false);

    const unsub = stream.subscribe(vi.fn());
    expect(stream.isOpen).toBe(true);

    unsub();
    expect(stream.isOpen).toBe(false);
  });
});

describe('SseStreamManager event dispatch', () => {
  beforeEach(() => {
    MockEventSource.reset();
    vi.stubGlobal('EventSource', MockEventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test('dispatches configured events to all handlers', () => {
    const stream = new SseStreamManager(DEFAULT_CONFIG);
    const handler1 = vi.fn();
    const handler2 = vi.fn();

    stream.subscribe(handler1);
    stream.subscribe(handler2);

    const [es] = MockEventSource.instances as [MockEventSource];
    const payload = JSON.stringify({ id: 'abc' });
    es.simulateEvent('test_event', payload);

    expect(handler1).toHaveBeenCalledOnce();
    expect(handler2).toHaveBeenCalledOnce();

    const receivedEvent = nonNull(handler1.mock.calls[0])[0] as MessageEvent;
    expect(receivedEvent.data).toBe(payload);
  });

  test('does not dispatch to unsubscribed handlers', () => {
    const stream = new SseStreamManager(DEFAULT_CONFIG);
    const stayingHandler = vi.fn();
    const leavingHandler = vi.fn();

    stream.subscribe(stayingHandler);
    const unsub = stream.subscribe(leavingHandler);

    unsub();

    const [es] = MockEventSource.instances as [MockEventSource];
    es.simulateEvent('test_event', '{}');

    expect(stayingHandler).toHaveBeenCalledOnce();
    expect(leavingHandler).not.toHaveBeenCalled();
  });

  test('only dispatches events matching the configured eventName', () => {
    const stream = new SseStreamManager(DEFAULT_CONFIG);
    const handler = vi.fn();
    stream.subscribe(handler);

    const [es] = MockEventSource.instances as [MockEventSource];
    es.simulateEvent('other_event', '{}');

    expect(handler).not.toHaveBeenCalled();
  });
});

describe('SseStreamManager destroy and reconnection', () => {
  beforeEach(() => {
    MockEventSource.reset();
    vi.stubGlobal('EventSource', MockEventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test('cleans up fully on destroy', () => {
    const stream = new SseStreamManager(DEFAULT_CONFIG);
    stream.subscribe(vi.fn());

    const [es] = MockEventSource.instances as [MockEventSource];
    expect(es.readyState).not.toBe(MockEventSource.CLOSED);

    stream.destroy();

    expect(es.readyState).toBe(MockEventSource.CLOSED);
    expect(stream.subscriberCount).toBe(0);
    expect(stream.isOpen).toBe(false);
  });

  test('keeps the native EventSource alive so browser reconnection remains enabled', () => {
    const stream = new SseStreamManager(DEFAULT_CONFIG);
    stream.subscribe(vi.fn());

    const [es] = MockEventSource.instances as [MockEventSource];
    es.simulateOpen();
    es.simulateError();

    expect(es.readyState).toBe(MockEventSource.OPEN);
    expect(stream.isOpen).toBe(true);
    expect(MockEventSource.instances).toHaveLength(1);
  });

  test('reopens EventSource after full unsubscribe + re-subscribe cycle', () => {
    const stream = new SseStreamManager(DEFAULT_CONFIG);

    const unsub = stream.subscribe(vi.fn());
    expect(MockEventSource.instances).toHaveLength(1);

    unsub();
    expect(nonNull(MockEventSource.instances[0]).readyState).toBe(MockEventSource.CLOSED);

    // Re-subscribing should open a fresh connection
    stream.subscribe(vi.fn());
    expect(MockEventSource.instances).toHaveLength(2);
    expect(nonNull(MockEventSource.instances[1]).readyState).not.toBe(MockEventSource.CLOSED);
  });
});
