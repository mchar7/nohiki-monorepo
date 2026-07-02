import { Link2 } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import type { ProfileResponse } from '@/shared/api';
import { useIsMobileLayout } from '@/shared/lib/index.ts';
import { BottomSheet } from '@/shared/ui/bottom-sheet.tsx';
import { Button } from '@/shared/ui/button.tsx';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/shared/ui/dialog.tsx';
import { Skeleton } from '@/shared/ui/skeleton.tsx';
import { useLinkAttachmentToProfile } from '../api/index.ts';

interface LinkToProfileDialogProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly uploadId: string;
  /** Profiles available to link. Caller fetches these (e.g. via useProfiles). */
  readonly profiles: readonly ProfileResponse[];
  /** Whether the caller is still loading the profile list. */
  readonly isLoadingProfiles: boolean;
}

function ProfileList({
  profiles,
  onSelect,
  isPending,
}: {
  readonly profiles: readonly ProfileResponse[];
  readonly onSelect: (prefId: string) => void;
  readonly isPending: boolean;
}): JSX.Element {
  const { t } = useTranslation(['attachments']);

  if (profiles.length === 0) {
    return (
      <p className="py-4 text-center text-muted-foreground text-sm">
        {t('attachments:linkDialog.noProfiles')}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      {profiles.map((profile) => (
        <Button
          key={profile.id}
          variant="ghost"
          className="w-full justify-start"
          disabled={isPending}
          onClick={() => onSelect(profile.id)}
        >
          <Link2 className="mr-2 size-4" aria-hidden="true" />
          {profile.pref_name}
        </Button>
      ))}
    </div>
  );
}

function ProfileListSkeleton(): JSX.Element {
  return (
    <div className="flex flex-col gap-2 py-2">
      <Skeleton className="h-9 w-full" />
      <Skeleton className="h-9 w-full" />
      <Skeleton className="h-9 w-full" />
    </div>
  );
}

function LinkToProfileDialog({
  open,
  onOpenChange,
  uploadId,
  profiles,
  isLoadingProfiles,
}: LinkToProfileDialogProps): JSX.Element {
  const { t } = useTranslation(['attachments', 'common']);
  const isMobile = useIsMobileLayout();
  const linkMutation = useLinkAttachmentToProfile();

  const handleSelect = (prefId: string): void => {
    linkMutation.mutate(
      { params: { path: { pref_id: prefId, upload_id: uploadId } } },
      {
        onSuccess: () => {
          onOpenChange(false);
        },
      },
    );
  };

  const content = isLoadingProfiles ? (
    <ProfileListSkeleton />
  ) : (
    <ProfileList profiles={profiles} onSelect={handleSelect} isPending={linkMutation.isPending} />
  );

  if (isMobile) {
    return (
      <BottomSheet
        open={open}
        onOpenChange={onOpenChange}
        title={t('attachments:linkDialog.title')}
        description={t('attachments:linkDialog.description')}
      >
        {content}
      </BottomSheet>
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('attachments:linkDialog.title')}</DialogTitle>
          <DialogDescription>{t('attachments:linkDialog.description')}</DialogDescription>
        </DialogHeader>
        {content}
      </DialogContent>
    </Dialog>
  );
}

export { LinkToProfileDialog };
