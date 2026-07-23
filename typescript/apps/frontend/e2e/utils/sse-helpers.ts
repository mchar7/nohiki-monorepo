import type { Page, Request, Route } from '@playwright/test';

interface SSEEventData {
  type: string;
  data: Record<string, unknown>;
}

interface SSEMock {
  readonly interceptedRequests: Request[];
  push: (event: SSEEventData) => void;
  flush: () => Promise<void>;
  cleanup: () => Promise<void>;
}

const SSE_ROUTE_PATTERN = '**/api/documents/*/events';

function formatSSEMessage(event: SSEEventData): string {
  return `event: ${event.type}\ndata: ${JSON.stringify(event.data)}\n\n`;
}

/**
 * Intercept the document SSE endpoint via `page.route()` and serve
 * pre-configured events as a `text/event-stream` response.
 *
 * Two usage modes:
 *
 * **Immediate** (events provided upfront): the stream is fulfilled as
 * soon as the EventSource connects.
 *
 * **Deferred** (no events upfront): call `push()` to queue events, then
 * `flush()` to fulfill the held route. Useful when you need the page to
 * load before delivering events.
 *
 * EventSource reconnection attempts after the initial response are
 * aborted to prevent retry loops in tests.
 */
async function mockSSEEndpoint(page: Page, events: SSEEventData[] = []): Promise<SSEMock> {
  const interceptedRequests: Request[] = [];
  const pendingEvents = [...events];
  let capturedRoute: Route | null = null;
  let fulfilled = false;

  async function fulfillRoute(route: Route): Promise<void> {
    fulfilled = true;
    const body = pendingEvents.map(formatSSEMessage).join('');
    await route.fulfill({
      status: 200,
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
      },
      body,
    });
  }

  await page.route(SSE_ROUTE_PATTERN, async (route) => {
    interceptedRequests.push(route.request());

    if (fulfilled) {
      await route.abort();
      return;
    }

    if (pendingEvents.length > 0) {
      await fulfillRoute(route);
    } else {
      capturedRoute = route;
    }
  });

  return {
    interceptedRequests,

    push(event: SSEEventData): void {
      pendingEvents.push(event);
    },

    async flush(): Promise<void> {
      if (fulfilled || !capturedRoute) {
        return;
      }
      await fulfillRoute(capturedRoute);
      capturedRoute = null;
    },

    async cleanup(): Promise<void> {
      if (capturedRoute && !fulfilled) {
        await capturedRoute.abort();
      }
      await page.unroute(SSE_ROUTE_PATTERN);
    },
  };
}

export { mockSSEEndpoint };
