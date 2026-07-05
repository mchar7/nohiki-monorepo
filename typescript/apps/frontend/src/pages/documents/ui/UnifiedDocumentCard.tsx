import {
  Check,
  Copy,
  Download,
  FileText,
  Image,
  Loader2,
  MoreVertical,
  Trash2,
} from 'lucide-react';
import { type JSX, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { getFileCategory } from '@/features/attachments';
import { useDeleteAttachment } from '@/features/attachments/index.ts';
import type { AttachmentResponse, DocumentStatusResponse } from '@/shared/api';
import {
  cn,
  formatFileSize,
  formatRelativeTime,
  getSafeExternalUrl,
  getSafeGeneratedDocumentUrl,
  useCopyToClipboard,
} from '@/shared/lib/index.ts';
import { Badge } from '@/shared/ui/badge.tsx';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent } from '@/shared/ui/card.tsx';
import { Progress } from '@/shared/ui/progress.tsx';
import {
  ResponsiveMenu,
  ResponsiveMenuItem,
  ResponsiveMenuSeparator,
} from '@/shared/ui/responsive-menu.tsx';
import { StatusBadge } from '@/shared/ui/status-badge.tsx';
import { documentStatusThemes } from '@/shared/ui/status-badge-model.ts';
import type { UnifiedDocument } from './UnifiedDocumentCard.types.ts';

/** Number of characters for truncated request ID display */
const REQUEST_ID_DISPLAY_LENGTH: number = 8;

interface UnifiedDocumentCardProps {
  readonly document: UnifiedDocument;
}

function assertNever(value: never): never {
  throw new Error(`Unexpected document type: ${String(value)}`);
}

/** Unified card rendering both uploaded attachments and generated documents. */
function UnifiedDocumentCard({ document: doc }: UnifiedDocumentCardProps): JSX.Element {
  switch (doc.type) {
    case 'uploaded':
      return <UploadedCard attachment={doc.data} />;
    case 'generated':
      return <GeneratedCard generatedDoc={doc.data} />;
    default:
      return assertNever(doc);
  }
}

interface UploadedCardProps {
  readonly attachment: AttachmentResponse;
}

function UploadedCard({ attachment }: UploadedCardProps): JSX.Element {
  const { t } = useTranslation(['documents', 'attachments', 'common']);
  const { size, unit } = formatFileSize(attachment.file_size);
  const deleteMutation = useDeleteAttachment();

  const handleDelete = (): void => {
    deleteMutation.mutate({ params: { path: { upload_id: attachment.id } } });
  };

  return (
    <Card className="transition-colors hover:border-primary/50">
      <CardContent className="p-4">
        <div className="flex items-start gap-3">
          <FileIcon contentType={attachment.content_type} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h3 className="truncate font-medium">{attachment.filename}</h3>
              <TypeBadge type="uploaded" />
            </div>
            <p className="text-muted-foreground text-sm">
              {t(`attachments:size.${unit}` as `size.${'bytes' | 'kb' | 'mb'}`, { size })}
            </p>
          </div>
          <UploadedActions attachment={attachment} onDelete={handleDelete} />
        </div>
      </CardContent>
    </Card>
  );
}

interface UploadedActionsProps {
  readonly attachment: AttachmentResponse;
  readonly onDelete: () => void;
}

function UploadedActions({ attachment, onDelete }: UploadedActionsProps): JSX.Element {
  const { t } = useTranslation(['attachments', 'common']);
  const [menuOpen, setMenuOpen] = useState(false);
  const downloadUrl = getSafeExternalUrl(attachment.download_url);

  const handleDownload = (): void => {
    if (downloadUrl) {
      window.open(downloadUrl, '_blank', 'noopener,noreferrer');
    }
  };

  return (
    <ResponsiveMenu
      open={menuOpen}
      onOpenChange={setMenuOpen}
      title={t('attachments:card.actions')}
      trigger={
        <Button variant="ghost" size="icon" className="size-8">
          <MoreVertical className="size-4" aria-hidden="true" />
          <span className="sr-only">{t('common:a11y.more')}</span>
        </Button>
      }
    >
      <ResponsiveMenuItem
        icon={<Download className="size-4" aria-hidden="true" />}
        disabled={!downloadUrl}
        onClick={handleDownload}
      >
        {t('attachments:actions.download')}
      </ResponsiveMenuItem>
      <ResponsiveMenuSeparator />
      <ResponsiveMenuItem
        icon={<Trash2 className="size-4" aria-hidden="true" />}
        variant="destructive"
        onClick={onDelete}
      >
        {t('attachments:actions.delete')}
      </ResponsiveMenuItem>
    </ResponsiveMenu>
  );
}

interface GeneratedCardProps {
  readonly generatedDoc: DocumentStatusResponse;
}

function GeneratedCard({ generatedDoc }: GeneratedCardProps): JSX.Element {
  const { t } = useTranslation(['documents', 'common']);
  const [copy, isCopied] = useCopyToClipboard();
  const statusKey = generatedDoc.status as 'pending' | 'processing' | 'completed' | 'failed';
  const displayName =
    generatedDoc.template_name ??
    `${generatedDoc.request_id.slice(0, REQUEST_ID_DISPLAY_LENGTH)}\u2026`;

  return (
    <Card className="transition-colors hover:border-primary/50">
      <CardContent className="p-4">
        <div className="flex items-start gap-3">
          <FileText className={cn('size-8 shrink-0', statusIconColor(generatedDoc.status))} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h3 className="truncate font-medium text-sm">{displayName}</h3>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => copy(generatedDoc.request_id)}
                  className="text-muted-foreground hover:text-foreground"
                  aria-label={t('common:actions.copyRequestId')}
                >
                  {isCopied ? <Check className="size-3" /> : <Copy className="size-3" />}
                </button>
              </div>
              <TypeBadge type="generated" />
              {generatedDoc.output_format ? (
                <Badge
                  variant="secondary"
                  aria-label={t('documents:card.outputFormat', {
                    format: generatedDoc.output_format.toUpperCase(),
                  })}
                >
                  {generatedDoc.output_format.toUpperCase()}
                </Badge>
              ) : null}
            </div>
            <div className="mt-1 flex items-center gap-2">
              <StatusBadge
                status={generatedDoc.status}
                label={t(`documents:status.${statusKey}`)}
                themes={documentStatusThemes}
              />
              {generatedDoc.status === 'processing' ? (
                <Loader2 className="size-3.5 animate-spin text-blue-500" aria-hidden="true" />
              ) : null}
              {generatedDoc.created_at ? (
                <span className="text-muted-foreground text-xs">
                  {t('documents:card.createdAt', {
                    time: formatRelativeTime(generatedDoc.created_at),
                  })}
                </span>
              ) : null}
            </div>
            {generatedDoc.error ? (
              <p className="mt-1 text-destructive text-xs">{generatedDoc.error}</p>
            ) : null}
          </div>
          <GeneratedActions generatedDoc={generatedDoc} />
        </div>
        {generatedDoc.status === 'processing' ? (
          <Progress value={undefined} className="mt-3 h-1.5" />
        ) : null}
      </CardContent>
    </Card>
  );
}

interface GeneratedActionsProps {
  readonly generatedDoc: DocumentStatusResponse;
}

function GeneratedActions({ generatedDoc }: GeneratedActionsProps): JSX.Element | null {
  const { t } = useTranslation(['documents']);
  const downloadUrl = getSafeGeneratedDocumentUrl(
    generatedDoc.download_url,
    window.location.origin,
  );

  if (generatedDoc.status === 'completed' && downloadUrl) {
    return (
      <Button size="sm" variant="outline" asChild={true}>
        <a href={downloadUrl} target="_blank" rel="noopener noreferrer">
          <Download className="mr-2 size-4" />
          {t('documents:actions.download')}
        </a>
      </Button>
    );
  }

  if (generatedDoc.status === 'processing') {
    return (
      <Button size="sm" variant="ghost" disabled={true}>
        <Loader2 className="mr-2 size-4 animate-spin" />
        {t('documents:generation.generating')}
      </Button>
    );
  }

  if (generatedDoc.status === 'pending') {
    return <span className="text-muted-foreground text-sm">{t('documents:status.pending')}</span>;
  }

  return null;
}

/** Color-coded icon for uploaded file types */
function FileIcon({ contentType }: { readonly contentType: string }): JSX.Element {
  const category = getFileCategory(contentType);
  switch (category) {
    case 'pdf':
      return <FileText className="size-8 text-red-500" />;
    case 'word':
      return <FileText className="size-8 text-blue-500" />;
    case 'image':
      return <Image className="size-8 text-green-500" />;
    default:
      return <FileText className="size-8 text-muted-foreground" />;
  }
}

/** Visual type badge distinguishing "Uploaded" vs "Generated" */
function TypeBadge({ type }: { readonly type: 'uploaded' | 'generated' }): JSX.Element {
  const { t } = useTranslation(['documents']);

  if (type === 'uploaded') {
    return (
      <Badge
        variant="outline"
        className="border-sky-500/20 bg-sky-500/10 text-sky-700 dark:text-sky-400"
      >
        {t('documents:typeBadge.uploaded')}
      </Badge>
    );
  }

  return (
    <Badge
      variant="outline"
      className="border-violet-500/20 bg-violet-500/10 text-violet-700 dark:text-violet-400"
    >
      {t('documents:typeBadge.generated')}
    </Badge>
  );
}

/** Map document generation status to an icon color */
function statusIconColor(status: string): string {
  switch (status) {
    case 'completed':
      return 'text-green-500';
    case 'failed':
      return 'text-destructive';
    case 'processing':
      return 'text-blue-500';
    default:
      return 'text-muted-foreground';
  }
}

export { UnifiedDocumentCard };
