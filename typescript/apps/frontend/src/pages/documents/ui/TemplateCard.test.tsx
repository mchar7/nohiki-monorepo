import type { RenderResult } from '@testing-library/react';
import { render, screen } from '@testing-library/react';
import type React from 'react';
import { I18nextProvider } from 'react-i18next';
import { describe, expect } from 'vitest';
import type { TemplateFamilyResponse } from '@/shared/api';
import { wrapWithRouter } from '@/shared/test-utils/index.ts';
import { i18n } from '@/test/setup.ts';
import { TemplateCard } from './TemplateCard.tsx';

const mockTemplate: TemplateFamilyResponse = {
  id: 'template-1',
  namespace: 'resume',
  name: 'modern_resume',
  display_name: 'Modern Résumé',
  description: 'A clean and modern resume template.',
  latest_version: {
    id: 'version-1',
    namespace: 'resume',
    name: 'modern_resume',
    display_name: 'Modern Résumé',
    version: '1.2.0',
    content_schema: {},
    template_content: '',
    access_scope: 'PUBLIC',
    is_active: true,
  },
};

const USE_TEMPLATE_PATTERN = /use template/iu;
const CUSTOMIZE_PATTERN = /customize/iu;

async function renderCard(
  props: Partial<React.ComponentProps<typeof TemplateCard>> = {},
): Promise<RenderResult> {
  const ui = await wrapWithRouter(
    <I18nextProvider i18n={i18n}>
      <TemplateCard template={mockTemplate} {...props} />
    </I18nextProvider>,
  );
  return render(ui);
}

describe('TemplateCard', () => {
  test('renders display name and never exposes the machine identifier', async () => {
    await renderCard();
    expect(screen.getByText('Modern Résumé')).toBeInTheDocument();
    expect(screen.queryByText('modern_resume')).not.toBeInTheDocument();
    expect(screen.getByText('A clean and modern resume template.')).toBeInTheDocument();
  });

  test('renders namespace and version', async () => {
    await renderCard();
    expect(screen.getByText('resume')).toBeInTheDocument();
    expect(screen.getByText('v1.2.0')).toBeInTheDocument();
  });

  test('renders action buttons with correct labels', async () => {
    await renderCard();
    expect(screen.getByRole('link', { name: USE_TEMPLATE_PATTERN })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: CUSTOMIZE_PATTERN })).toBeInTheDocument();
  });

  test('falls back to default description if none provided', async () => {
    await renderCard({ template: { ...mockTemplate, description: null } });
    expect(screen.getByText('Try adjusting your search query')).toBeInTheDocument();
  });

  test('falls back to default version if latest_version is null', async () => {
    await renderCard({ template: { ...mockTemplate, latest_version: null } });
    expect(screen.getByText('v1.0.0')).toBeInTheDocument();
  });
});
