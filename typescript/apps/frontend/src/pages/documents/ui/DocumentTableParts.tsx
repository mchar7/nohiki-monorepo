import { Link } from '@tanstack/react-router';
import { FileText } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { UploadDialog } from '@/features/attachments/index.ts';
import { ROUTE_PATHS } from '@/shared/config/index.ts';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent } from '@/shared/ui/card.tsx';

function EmptyState(): JSX.Element {
  const { t } = useTranslation(['documents']);

  return (
    <Card>
      <CardContent className="py-12 text-center">
        <FileText className="mx-auto mb-4 size-12 text-muted-foreground" />
        <h3 className="mb-2 font-medium">{t('documents:empty.noDocuments')}</h3>
        <p className="mb-4 text-muted-foreground">{t('documents:empty.noDocumentsDescription')}</p>
        <Button asChild={true}>
          <Link to={ROUTE_PATHS.DOCUMENTS.GENERATE}>{t('documents:empty.createFirst')}</Link>
        </Button>
        <div className="mt-3">
          <UploadDialog />
        </div>
      </CardContent>
    </Card>
  );
}

export { EmptyState };
