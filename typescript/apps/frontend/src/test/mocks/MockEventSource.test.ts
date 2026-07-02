import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import { nonNull } from '@/shared/test-utils';
import { MockEventSource } from './MockEventSource';

describe('MockEventSource', () => {
  beforeEach(() => {
    MockEventSource.reset();
  });

  afterEach(() => {
    MockEventSource.reset();
  });

  describe('constructor', () => {
    test('sets url from string', () => {
      const es = new MockEventSource('https://example.com/events');
      expect(es.url).toBe('https://example.com/events');
    });

    test('sets url from URL object', () => {
      const es = new MockEventSource(new URL('https://example.com/events'));
      expect(es.url).toBe('https://example.com/events');
    });

    test('defaults withCredentials to false', () => {
      const es = new MockEventSource('/events');
      expect(es.withCredentials).toBe(false);
    });

    test('sets withCredentials from init dict', () => {
      const es = new MockEventSource('/events', { withCredentials: true });
      expect(es.withCredentials).toBe(true);
    });

    test('starts in CONNECTING state', () => {
      const es = new MockEventSource('/events');
      expect(es.readyState).toBe(MockEventSource.CONNECTING);
    });

    test('registers itself in instances', () => {
      const es = new MockEventSource('/events');
      expect(MockEventSource.instances).toContain(es);
    });
  });

  describe('ready-state constants', () => {
    test('exposes correct static values', () => {
      expect(MockEventSource.CONNECTING).toBe(0);
      expect(MockEventSource.OPEN).toBe(1);
      expect(MockEventSource.CLOSED).toBe(2);
    });

    test('exposes matching instance values', () => {
      const es = new MockEventSource('/events');
      expect(es.CONNECTING).toBe(0);
      expect(es.OPEN).toBe(1);
      expect(es.CLOSED).toBe(2);
    });
  });

  describe('simulateOpen()', () => {
    test('sets readyState to OPEN', () => {
      const es = new MockEventSource('/events');
      es.simulateOpen();
      expect(es.readyState).toBe(MockEventSource.OPEN);
    });

    test('fires onopen handler', () => {
      const es = new MockEventSource('/events');
      const onopen = vi.fn();
      es.onopen = onopen;
      es.simulateOpen();
      expect(onopen).toHaveBeenCalledOnce();
      expect(nonNull(onopen.mock.calls[0])[0]).toBeInstanceOf(Event);
    });

    test('does not throw when onopen is null', () => {
      const es = new MockEventSource('/events');
      expect(() => es.simulateOpen()).not.toThrow();
    });
  });

  describe('simulateMessage()', () => {
    test('fires onmessage with the given data', () => {
      const es = new MockEventSource('/events');
      const onmessage = vi.fn();
      es.onmessage = onmessage;
      es.simulateMessage('{"hello":"world"}');
      expect(onmessage).toHaveBeenCalledOnce();
      const [event] = onmessage.mock.calls[0] as [MessageEvent];
      expect(event).toBeInstanceOf(MessageEvent);
      expect(event.data).toBe('{"hello":"world"}');
    });

    test('does not throw when onmessage is null', () => {
      const es = new MockEventSource('/events');
      expect(() => es.simulateMessage('data')).not.toThrow();
    });
  });

  describe('simulateEvent()', () => {
    test('fires all listeners registered for the event type', () => {
      const es = new MockEventSource('/events');
      const listener1 = vi.fn();
      const listener2 = vi.fn();
      es.addEventListener('status', listener1);
      es.addEventListener('status', listener2);
      es.simulateEvent('status', 'processing');
      expect(listener1).toHaveBeenCalledOnce();
      expect(listener2).toHaveBeenCalledOnce();
    });

    test('passes a MessageEvent with the correct data', () => {
      const es = new MockEventSource('/events');
      const listener = vi.fn();
      es.addEventListener('complete', listener);
      es.simulateEvent('complete', '{"documentId":"abc"}');
      const [event] = listener.mock.calls[0] as [MessageEvent];
      expect(event).toBeInstanceOf(MessageEvent);
      expect(event.data).toBe('{"documentId":"abc"}');
      expect(event.type).toBe('complete');
    });

    test('does not fire listeners for a different event type', () => {
      const es = new MockEventSource('/events');
      const statusListener = vi.fn();
      es.addEventListener('status', statusListener);
      es.simulateEvent('complete', 'done');
      expect(statusListener).not.toHaveBeenCalled();
    });

    test('does not throw when no listeners are registered for the type', () => {
      const es = new MockEventSource('/events');
      expect(() => es.simulateEvent('unknown', 'data')).not.toThrow();
    });
  });

  describe('simulateError()', () => {
    test('fires onerror handler', () => {
      const es = new MockEventSource('/events');
      const onerror = vi.fn();
      es.onerror = onerror;
      es.simulateError();
      expect(onerror).toHaveBeenCalledOnce();
      expect(nonNull(onerror.mock.calls[0])[0]).toBeInstanceOf(Event);
    });

    test('does not throw when onerror is null', () => {
      const es = new MockEventSource('/events');
      expect(() => es.simulateError()).not.toThrow();
    });
  });

  describe('close()', () => {
    test('sets readyState to CLOSED', () => {
      const es = new MockEventSource('/events');
      es.simulateOpen();
      es.close();
      expect(es.readyState).toBe(MockEventSource.CLOSED);
    });
  });

  describe('removeEventListener()', () => {
    test('stops a removed listener from firing', () => {
      const es = new MockEventSource('/events');
      const listener = vi.fn();
      es.addEventListener('status', listener);
      es.removeEventListener('status', listener);
      es.simulateEvent('status', 'processing');
      expect(listener).not.toHaveBeenCalled();
    });

    test('does not affect other listeners for the same type', () => {
      const es = new MockEventSource('/events');
      const keep = vi.fn();
      const remove = vi.fn();
      es.addEventListener('status', keep);
      es.addEventListener('status', remove);
      es.removeEventListener('status', remove);
      es.simulateEvent('status', 'data');
      expect(keep).toHaveBeenCalledOnce();
      expect(remove).not.toHaveBeenCalled();
    });

    test('does not throw when removing a listener that was never added', () => {
      const es = new MockEventSource('/events');
      expect(() => es.removeEventListener('status', vi.fn())).not.toThrow();
    });
  });

  describe('instances tracking', () => {
    test('tracks multiple instances', () => {
      const es1 = new MockEventSource('/a');
      const es2 = new MockEventSource('/b');
      expect(MockEventSource.instances).toHaveLength(2);
      expect(MockEventSource.instances).toContain(es1);
      expect(MockEventSource.instances).toContain(es2);
    });

    test('reset() clears all instances', () => {
      const _a = new MockEventSource('/a');
      const _b = new MockEventSource('/b');
      MockEventSource.reset();
      expect(MockEventSource.instances).toHaveLength(0);
    });
  });
});
