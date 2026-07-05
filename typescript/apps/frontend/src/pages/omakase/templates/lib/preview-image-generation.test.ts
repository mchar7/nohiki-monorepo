import { beforeEach, describe, expect, test, vi } from 'vitest';
import type { PreviewState } from '../model/index.ts';
import { generateOrUseCached } from './preview-image-generation.ts';

const { awaitDocumentReady, post } = vi.hoisted(() => ({
  awaitDocumentReady: vi.fn(),
  post: vi.fn(),
}));

vi.mock('@/entities/document', () => ({ awaitDocumentReady }));
vi.mock('@/shared/api/index.ts', () => ({ fetchClient: { POST: post } }));

function initialState(): PreviewState {
  return {
    imageUrl: null,
    imageNaturalSize: null,
    isGenerating: false,
    generationError: null,
    lastGeneratedAt: null,
    scale: {
      mode: 'fit',
      percentage: 100,
      imageNaturalSize: null,
      containerSize: { width: 800, height: 600 },
    },
    containerSize: { width: 800, height: 600 },
    pageSize: { width: 210, height: 297, unit: 'mm' },
    templateData: {},
  };
}

describe('preview image artifact failures', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    post.mockResolvedValue({ data: { request_id: 'req-1' }, error: undefined });
    awaitDocumentReady.mockResolvedValue({
      downloadUrl: 'https://storage.example.com/rendered/preview.png',
      status: 'completed',
    });
  });

  test('records a non-ok fetch as an error without creating or caching an object URL', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 504 }));
    const createObjectURL = vi.spyOn(URL, 'createObjectURL');
    const onError = vi.fn();
    const cache = new Map();
    let state = initialState();

    await generateOrUseCached({
      templateVersionId: 'tpl-1',
      templateData: {},
      pageSize: state.pageSize,
      containerSize: state.containerSize,
      maxDimension: 1200,
      cacheSize: 3,
      targetSize: { width: 800, height: 1131 },
      cache,
      setPreviewState: (update) => {
        state = update(state);
      },
      onError,
      fallbackErrorMessage: 'Preview failed',
    });

    expect(state).toMatchObject({
      imageUrl: null,
      isGenerating: false,
      generationError: 'Generated preview fetch failed with status 504',
    });
    expect(onError).toHaveBeenCalledWith('Generated preview fetch failed with status 504');
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(cache).toHaveLength(0);
    vi.unstubAllGlobals();
  });
});
