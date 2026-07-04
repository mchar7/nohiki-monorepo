import { Link } from '@tanstack/react-router';
import { FileText } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { UploadDialog } from '@/features/attachments/index.ts';
import { ROUTE_PATHS } from '@/shared/config/index.ts';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent } from '@/shared/ui/card.tsx';
import type { DocumentTab } from './DocumentTabContentModel.ts';

interface EmptyStateProps {
  readonly tab: DocumentTab;
}

function EmptyState({ tab }: EmptyStateProps): JSX.Element {
  const { t } = useTranslation(['documents']);

  const emptyConfig: Record<DocumentTab, { title: string; description: string }> = {
    all: {
      title: t('documents:empty.noDocuments'),
      description: t('documents:empty.noDocumentsDescription'),
    },
    uploaded: {
      title: t('documents:empty.noUploaded'),
      description: t('documents:empty.noUploadedDescription'),
    },
    generated: {
      title: t('documents:empty.noGenerated'),
      description: t('documents:empty.noGeneratedDescription'),
    },
  };

  const config = emptyConfig[tab];

  return (
    <Card>
      <CardContent className="py-12 text-center">
        <FileText className="mx-auto mb-4 size-12 text-muted-foreground" />
        <h3 className="mb-2 font-medium">{config.title}</h3>
        <p className="mb-4 text-muted-foreground">{config.description}</p>
        {tab !== 'uploaded' ? (
          <Button asChild={true}>
            <Link to={ROUTE_PATHS.DOCUMENTS.GENERATE}>{t('documents:empty.createFirst')}</Link>
          </Button>
        ) : null}
        {tab !== 'generated' ? (
          <div className={tab !== 'uploaded' ? 'mt-3' : undefined}>
            <UploadDialog />
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

export { EmptyState };
