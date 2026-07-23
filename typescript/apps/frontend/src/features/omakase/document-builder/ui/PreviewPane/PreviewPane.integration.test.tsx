import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, vi } from 'vitest';
import type { UsePreviewPaneReturn } from '../../lib/previewPaneHelpers.ts';
import { usePreviewPane } from '../../lib/usePreviewPane.ts';
import { PreviewPane } from './PreviewPane.tsx';

vi.mock('../../lib/usePreviewPane.ts', () => ({
  usePreviewPane: vi.fn(),
}));

const mockHandleJsChoice = vi.fn<(method: 'html' | 'image', remember: boolean) => void>();

const mockPreviewState: UsePreviewPaneReturn = {
  htmlUrl: null,
  imageUrl: null,
  isGenerating: false,
  isGeneratingPreview: false,
  isGeneratingImage: false,
  hasPreview: false,
  error: null,
  clearError: vi.fn(),
  generatePreview: vi.fn().mockResolvedValue(undefined),
  clearPreview: vi.fn(),
  revokeHtmlUrl: vi.fn(),
  revokeImageUrl: vi.fn(),
  downloadPdf: vi.fn().mockResolvedValue(undefined),
  renderMethod: 'html',
  setRenderMethod: vi.fn(),
  jsWarning: {
    showWarning: true,
    templateName: 'Test Template',
    templateVersion: '1.0.0',
    reason: 'Dynamic content generation',
    handleJsChoice: mockHandleJsChoice,
    checkJsRequirement: vi.fn().mockReturnValue(false),
  },
};

describe('PreviewPane JavaScript warning integration', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(usePreviewPane).mockReturnValue(mockPreviewState);
  });

  test('renders warning details supplied by the preview hook', () => {
    render(<PreviewPane showHeader={false} templateId="template-1" />);

    expect(
      screen.getByRole('heading', { name: 'JavaScript Template Warning' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Reason: Dynamic content generation')).toBeInTheDocument();
    expect(
      screen.getByRole('checkbox', { name: 'Don\'t ask again for "Test Template@1.0.0"' }),
    ).toBeInTheDocument();
  });

  test.each([
    {
      buttonName: 'Render as Image (WebP)',
      method: 'image' as const,
      remember: false,
    },
    {
      buttonName: 'Render Directly (HTML)',
      method: 'html' as const,
      remember: true,
    },
  ])('passes the $method choice and remember preference through the component boundary', async ({
    buttonName,
    method,
    remember,
  }) => {
    const user = userEvent.setup();
    render(<PreviewPane showHeader={false} templateId="template-1" />);

    if (remember) {
      await user.click(
        screen.getByRole('checkbox', {
          name: 'Don\'t ask again for "Test Template@1.0.0"',
        }),
      );
    }
    await user.click(screen.getByRole('button', { name: buttonName }));

    expect(mockHandleJsChoice).toHaveBeenCalledOnce();
    expect(mockHandleJsChoice).toHaveBeenCalledWith(method, remember);
  });
});
