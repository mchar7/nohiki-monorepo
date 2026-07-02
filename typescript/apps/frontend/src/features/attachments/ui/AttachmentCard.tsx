import { Download, Eye, FileText, Image, Link2, MoreVertical, Trash2, Unlink2 } from 'lucide-react';
import { type JSX, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { AttachmentResponse, ProfileResponse } from '@/shared/api';
import { formatFileSize, formatRelativeTime, getSafeExternalUrl } from '@/shared/lib/index.ts';
import { Badge } from '@/shared/ui/badge.tsx';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent } from '@/shared/ui/card.tsx';
import {
  ResponsiveMenu,
  ResponsiveMenuItem,
  ResponsiveMenuSeparator,
} from '@/shared/ui/responsive-menu.tsx';
import { loadCategory } from '../lib/categorize.ts';
import { getFileCategory } from '../lib/format.ts';
import type { LinkedProfile } from './AttachmentCard.types.ts';
import { LinkToProfileDialog } from './LinkToProfileDialog.tsx';
import { PreviewSheet } from './PreviewSheet.tsx';

interface AttachmentCardProps {
  readonly attachment: AttachmentResponse;
  readonly onDelete: (id: string) => void;
  readonly linkedProfile?: LinkedProfile | null;
  readonly onUnlink?: (prefId: string, uploadId: string) => void;
  /**
   * Profiles available to link this attachment to. Defaults to an empty list,
   * which renders the "no profiles" empty state. The caller (page-level
   * composition) fetches profiles and passes them in so this feature does
   * not cross-import profile-management.
   */
  readonly availableProfiles?: readonly ProfileResponse[];
  readonly isLoadingProfiles?: boolean;
}

function AttachmentCard({
  attachment,
  onDelete,
  linkedProfile,
  onUnlink,
  availableProfiles = [],
  isLoadingProfiles = false,
}: AttachmentCardProps): JSX.Element {
  const { t } = useTranslation(['attachments', 'common']);
  const { size, unit } = formatFileSize(attachment.file_size);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [linkDialogOpen, setLinkDialogOpen] = useState(false);
  const category = loadCategory(attachment.id);

  const handleDelete = (): void => {
    onDelete(attachment.id);
  };

  const handlePreview = (): void => {
    setPreviewOpen(true);
  };

  const handleOpenLinkDialog = (): void => {
    setLinkDialogOpen(true);
  };

  const handleUnlink = (): void => {
    if (linkedProfile) {
      onUnlink?.(linkedProfile.id, attachment.id);
    }
  };

  return (
    <>
      <Card className="transition-colors hover:border-primary/50">
        <CardContent className="p-4">
          <div className="flex items-start gap-3">
            <FileIcon contentType={attachment.content_type} />
            <div className="min-w-0 flex-1">
              <h3 className="truncate font-medium">{attachment.filename}</h3>
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-muted-foreground text-sm">
                  {t(`attachments:size.${unit}` as `size.${'bytes' | 'kb' | 'mb'}`, { size })}
                </p>
                {attachment.created_at ? (
                  <p className="text-muted-foreground text-xs">
                    {t('attachments:card.uploadedAt', {
                      time: formatRelativeTime(attachment.created_at),
                    })}
                  </p>
                ) : null}
                {category ? (
                  <Badge variant="secondary" aria-label={t('attachments:card.categoryLabel')}>
                    {t(`attachments:category.${category}`)}
                  </Badge>
                ) : null}
                {linkedProfile ? (
                  <Badge variant="outline">
                    <Link2 className="size-3" aria-hidden="true" />
                    {t('attachments:card.linkedProfile', { name: linkedProfile.name })}
                  </Badge>
                ) : null}
              </div>
            </div>
            <AttachmentActions
              attachment={attachment}
              onDelete={handleDelete}
              onPreview={handlePreview}
              linkedProfile={linkedProfile}
              onLinkToProfile={handleOpenLinkDialog}
              onUnlink={handleUnlink}
            />
          </div>
        </CardContent>
      </Card>
      <PreviewSheet open={previewOpen} onOpenChange={setPreviewOpen} attachment={attachment} />
      <LinkToProfileDialog
        open={linkDialogOpen}
        onOpenChange={setLinkDialogOpen}
        uploadId={attachment.id}
        profiles={availableProfiles}
        isLoadingProfiles={isLoadingProfiles}
      />
    </>
  );
}

function FileIcon({ contentType }: { readonly contentType: string }): JSX.Element {
  const category = getFileCategory(contentType);

  const iconProps = { className: 'size-8 text-muted-foreground' };

  switch (category) {
    case 'pdf':
      return <FileText {...iconProps} className="size-8 text-red-500" />;
    case 'word':
      return <FileText {...iconProps} className="size-8 text-blue-500" />;
    case 'image':
      return <Image {...iconProps} className="size-8 text-green-500" />;
    default:
      return <FileText {...iconProps} />;
  }
}

interface AttachmentActionsProps {
  readonly attachment: AttachmentResponse;
  readonly onDelete: () => void;
  readonly onPreview: () => void;
  readonly linkedProfile?: LinkedProfile | null;
  readonly onLinkToProfile: () => void;
  readonly onUnlink: () => void;
}

function AttachmentActions({
  attachment,
  onDelete,
  onPreview,
  linkedProfile,
  onLinkToProfile,
  onUnlink,
}: AttachmentActionsProps): JSX.Element {
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
      {attachment.content_type === 'application/pdf' && (
        <ResponsiveMenuItem
          icon={<Eye className="size-4" aria-hidden="true" />}
          disabled={!downloadUrl}
          onClick={onPreview}
        >
          {t('attachments:actions.preview')}
        </ResponsiveMenuItem>
      )}
      <ResponsiveMenuItem
        icon={<Download className="size-4" aria-hidden="true" />}
        disabled={!downloadUrl}
        onClick={handleDownload}
      >
        {t('attachments:actions.download')}
      </ResponsiveMenuItem>
      {linkedProfile ? (
        <ResponsiveMenuItem
          icon={<Unlink2 className="size-4" aria-hidden="true" />}
          onClick={onUnlink}
        >
          {t('attachments:actions.unlinkFromProfile')}
        </ResponsiveMenuItem>
      ) : (
        <ResponsiveMenuItem
          icon={<Link2 className="size-4" aria-hidden="true" />}
          onClick={onLinkToProfile}
        >
          {t('attachments:actions.linkToProfile')}
        </ResponsiveMenuItem>
      )}
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

export { AttachmentCard };
