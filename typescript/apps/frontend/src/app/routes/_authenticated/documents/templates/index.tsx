import { TemplateGallery } from '@pages/documents';
import { type AnyRoute, createFileRoute } from '@tanstack/react-router';
import type { JSX } from 'react';

const Route: AnyRoute = createFileRoute('/_authenticated/documents/templates/')({
  component: TemplateGalleryPage,
});

function TemplateGalleryPage(): JSX.Element {
  return (
    <div className="flex-1 space-y-4 p-4 pt-6 md:p-8">
      <TemplateGallery />
    </div>
  );
}

export { Route };
