import process from 'node:process';
import { E2E_CONFIG, TIMEOUTS } from '../constants.ts';
import { expect, test } from '../fixtures/auth.ts';
import { DocumentsPage } from '../pages/index.ts';
import { createProfileViaApi, waitForProfile, waitForProjection } from '../utils/api-helpers.ts';
import { generateDocument } from '../utils/document-helpers.ts';
import { mockSSEEndpoint } from '../utils/sse-helpers.ts';

/**
 * Minimal Jinja2 HTML template that satisfies BFF validation
 * (balanced block tags, <!DOCTYPE html>). Renders a simple resume.
 */
const SIMPLE_TEMPLATE = `<!DOCTYPE html>
<html>
<head><title>{{ name }} - Resume</title></head>
<body>
<h1>{{ name }}</h1>
<p>{{ title }}</p>
</body>
</html>`;

/** Unique prerequisite names per run to avoid collisions. */
const RUN_ID = Date.now();
const TEMPLATE_NAME = `e2e-sse-${RUN_ID}`;
const PROFILE_NAME = `E2E SSE Profile ${RUN_ID}`;

const DOCUMENTS_EVENTS_PATH_RE = /^\/api\/documents\/[^/]+\/events$/u;
const GENERATE_DOCUMENT_PATH = '/api/v1/documents/generate';
const HTTP_ACCEPTED = 202;
const HTTP_CLIENT_ERROR_MIN = 400;
const HTTP_SERVER_ERROR_MIN = 500;
const POLL_INTERVAL_MS = 2000;

interface TemplateFamily {
  id: string;
  name: string;
  latest_version: { id: string } | null;
}

interface PaginatedTemplateFamilies {
  items: TemplateFamily[];
  total: number;
}

interface GenerateDocumentResult {
  request_id: string;
}

function documentEventsPath(requestId: string): string {
  return `/api/documents/${encodeURIComponent(requestId)}/events`;
}

// biome-ignore format: Playwright test.describe.serial requires single-line syntax
test.describe.serial('Document Generation SSE Journey', () => {
  const generatedRequestIds: string[] = [];

  test('1. Create generation prerequisites via API', async ({ request }) => {
    const createTemplateResponse = await request.post('/api/v1/template-families', {
      data: {
        name: TEMPLATE_NAME,
        display_name: TEMPLATE_NAME,
        namespace: 'resume',
        template_content: SIMPLE_TEMPLATE,
        description: 'E2E SSE test template',
      },
    });
    expect(createTemplateResponse.status()).toBe(HTTP_ACCEPTED);
    await createProfileViaApi(request, {
      pref_name: PROFILE_NAME,
      search_keywords: ['software engineering'],
    });

    const [families] = await Promise.all([
      waitForProjection<PaginatedTemplateFamilies>(
        request,
        '/api/v1/template-families?page=1&page_size=100',
        (data) =>
          data.items.some((family) => family.name === TEMPLATE_NAME && family.latest_version !== null),
        { timeout: TIMEOUTS.cqrsProjection, interval: POLL_INTERVAL_MS },
      ),
      waitForProfile(request, PROFILE_NAME),
    ]);
    const templateVersionId =
      families.items.find(
        (family) => family.name === TEMPLATE_NAME && family.latest_version !== null,
      )?.latest_version?.id ?? '';
    expect(templateVersionId).toBeTruthy();
  });

  test('2. SSE connection is established on document generation', async ({ page }) => {
    const sseMock = await mockSSEEndpoint(page);
    try {
      const wizard = await generateDocument(page, {
        docType: 'Resume',
        profileName: PROFILE_NAME,
        templateName: TEMPLATE_NAME,
      });
      const generationResponsePromise = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === GENERATE_DOCUMENT_PATH &&
          response.request().method() === 'POST',
      );
      const sseRequestPromise = page.waitForRequest(
        (request) => DOCUMENTS_EVENTS_PATH_RE.test(new URL(request.url()).pathname),
      );

      await wizard.clickGenerate();
      const generationResponse = await generationResponsePromise;
      expect(generationResponse.status()).toBe(HTTP_ACCEPTED);
      const generation = (await generationResponse.json()) as GenerateDocumentResult;
      generatedRequestIds.push(generation.request_id);

      const sseRequest = await sseRequestPromise;
      expect(new URL(sseRequest.url()).pathname).toBe(documentEventsPath(generation.request_id));
      expect(sseRequest.headers().accept).toContain('text/event-stream');

      sseMock.push({
        type: 'document_status',
        data: { request_id: generation.request_id, status: 'pending' },
      });
      await sseMock.flush();
      await expect(page.getByRole('heading', { name: 'Generating your document' })).toBeVisible();
    } finally {
      await sseMock.cleanup();
    }
  });

  test('3. Document status updates in real-time via SSE', async ({ page }) => {
    const sseMock = await mockSSEEndpoint(page);
    try {
      const wizard = await generateDocument(page, {
        docType: 'Resume',
        profileName: PROFILE_NAME,
        templateName: TEMPLATE_NAME,
      });
      const generationResponsePromise = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === GENERATE_DOCUMENT_PATH &&
          response.request().method() === 'POST',
      );
      const sseRequestPromise = page.waitForRequest(
        (request) => DOCUMENTS_EVENTS_PATH_RE.test(new URL(request.url()).pathname),
      );

      await wizard.clickGenerate();
      const generationResponse = await generationResponsePromise;
      expect(generationResponse.status()).toBe(HTTP_ACCEPTED);
      const generation = (await generationResponse.json()) as GenerateDocumentResult;
      generatedRequestIds.push(generation.request_id);
      await sseRequestPromise;

      sseMock.push({
        type: 'document_status',
        data: { request_id: generation.request_id, status: 'processing', progress: 50 },
      });
      await sseMock.flush();

      await expect(page.getByText('50% complete', { exact: true })).toBeVisible();
    } finally {
      await sseMock.cleanup();
    }
  });

  test('4. Generated document appears in documents list', async ({ page, request }) => {
    await waitForProjection<{ items: Array<{ request_id: string }> }>(
      request,
      '/api/v1/documents?page=1&page_size=100',
      (data) => data.items.some((document) => generatedRequestIds.includes(document.request_id)),
      { timeout: TIMEOUTS.cqrsProjection, interval: POLL_INTERVAL_MS },
    );

    const documentsPage = new DocumentsPage(page);
    await documentsPage.goto();
    await documentsPage.waitForDocumentsLoaded();
    await expect(page.getByRole('heading', { name: TEMPLATE_NAME }).first()).toBeVisible();
  });

  test('5. SSE endpoint requires authentication', async ({ browser }) => {
    const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
    const unauthPage = await context.newPage();
    const baseUrl = process.env.E2E_BASE_URL ?? E2E_CONFIG.baseUrl;
    const response = await unauthPage.request.get(
      `${baseUrl}${documentEventsPath('00000000-0000-4000-8000-000000000000')}`,
    );
    expect(response.status()).toBeGreaterThanOrEqual(HTTP_CLIENT_ERROR_MIN);
    expect(response.status()).toBeLessThan(HTTP_SERVER_ERROR_MIN);
    await context.close();
  });
});
