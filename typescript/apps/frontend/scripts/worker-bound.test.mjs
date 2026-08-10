import { describe, expect, test } from 'vitest';

import { resolveMaxWorkers } from '../vitest.config.ts';

// Host shapes, not any particular host. Memory limits are declared in binary units and host
// totals are reported in decimal ones, so the two are deliberately mixed here.
const HOST_MEMORY = 28 * 1000 ** 3;
const HALF_FENCE = 14 * 1024 ** 3;

describe('resolveMaxWorkers', () => {
  test('halves a slot that is fenced to half its host', () => {
    // A 0.5 share of 12 threads is 6, which is 5 workers plus the main thread.
    expect(resolveMaxWorkers(12, HALF_FENCE, HOST_MEMORY)).toBe(5);
  });

  test('leaves a host that fences nothing alone', () => {
    // No memory limit means no share to take: every visible thread stays available.
    expect(resolveMaxWorkers(12, undefined, HOST_MEMORY)).toBe(11);
    expect(resolveMaxWorkers(20, undefined, HOST_MEMORY)).toBe(19);
  });

  test('ignores a fence that does not actually fence', () => {
    // A limit at or above the host total is not a share of anything.
    expect(resolveMaxWorkers(20, HOST_MEMORY, HOST_MEMORY)).toBe(19);
  });

  test('falls back to the visible count when the host cannot be read', () => {
    // No /proc to read: a non-Linux developer machine, or a sandbox. Vitest's own answer.
    expect(resolveMaxWorkers(20, HALF_FENCE, undefined)).toBe(19);
  });

  test('keeps one worker on shapes the share would round to nothing', () => {
    // Two visible threads, and a container fenced far below its share of the host.
    expect(resolveMaxWorkers(2, undefined, HOST_MEMORY)).toBe(1);
    expect(resolveMaxWorkers(12, 512 * 1024 ** 2, HOST_MEMORY)).toBe(1);
  });

  test('scales with the fence rather than pinning a number', () => {
    // A host with a different shape derives its own answer, not this one's.
    expect(resolveMaxWorkers(64, 16 * 1024 ** 3, 128 * 1024 ** 3)).toBe(7);
    expect(resolveMaxWorkers(8, 6 * 1024 ** 3, 8 * 1024 ** 3)).toBe(5);
  });
});
