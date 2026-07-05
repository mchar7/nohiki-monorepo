import { useParams } from '@tanstack/react-router';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ExperienceCard,
  FeatureImportanceSection,
  KeywordsCard,
  ProfileNameCard,
  ProfileViewCard,
  RelocationCard,
  SalaryCard,
  SkillsCard,
  ThresholdsCard,
  useProfile,
  useProfileDelete,
  useProfileEditForm,
  WorkArrangementsCard,
} from '@/features/profile-management/index.ts';
import { ROUTE_PATHS } from '@/shared/config/index.ts';
import { useDocumentTitle, useUnsavedChanges } from '@/shared/lib/index.ts';
import { Form } from '@/shared/ui/form.tsx';
import { PageHeader } from '@/shared/ui/index.ts';
import { UnsavedChangesDialog } from '@/shared/ui/unsaved-changes-dialog.tsx';
import { PageLayout } from '@/widgets/layout/index.ts';
import { DeleteConfirmDialog } from './ui/DeleteConfirmDialog.tsx';
import { ProfileDetailActions } from './ui/ProfileDetailActions.tsx';
import { ProfileDetailSkeleton, ProfileNotFound } from './ui/ProfileDetailStates.tsx';
import { ProfileEditActions } from './ui/ProfileEditActions.tsx';

function ProfileDetail(): JSX.Element {
  const { profileId } = useParams({ from: '/_authenticated/profiles/$profileId' });
  const { data: profile, isLoading, error } = useProfile(profileId ?? '');

  if (isLoading) {
    return <ProfileDetailSkeleton />;
  }
  if (error || !profile || !profileId) {
    return <ProfileNotFound />;
  }

  return <ProfileDetailContent profileId={profileId} profile={profile} />;
}

interface ProfileDetailContentProps {
  readonly profileId: string;
  readonly profile: NonNullable<ReturnType<typeof useProfile>['data']>;
}

function ProfileDetailContent({ profileId, profile }: ProfileDetailContentProps): JSX.Element {
  const { t } = useTranslation(['profiles']);
  const editForm = useProfileEditForm({ profileId, profile });
  const deleteAction = useProfileDelete({ profileId });

  const pageTitle = editForm.isEditing ? t('pages.detail.editMode') : profile.pref_name;
  useDocumentTitle(pageTitle);
  const blocker = useUnsavedChanges(editForm.isEditing && editForm.form.formState.isDirty);

  const headerActions = editForm.isEditing ? undefined : (
    <ProfileDetailActions onEdit={editForm.startEditing} onDelete={deleteAction.openDialog} />
  );

  return (
    <PageLayout contentWidth="narrow" className="space-y-6">
      <PageHeader
        title={profile.pref_name}
        description=""
        backTo={ROUTE_PATHS.PROFILES.LIST}
        preferHistory={true}
        actions={headerActions}
      />

      {editForm.isEditing ? (
        <ProfileEditForm
          form={editForm.form}
          onSubmit={editForm.onSubmit}
          onCancel={editForm.cancelEditing}
          isPending={editForm.isPending}
        />
      ) : null}
      {editForm.isEditing ? null : <ProfileViewCard profile={profile} />}

      <FeatureImportanceSection profileId={profileId} />

      <DeleteConfirmDialog
        open={deleteAction.showDialog}
        onOpenChange={deleteAction.closeDialog}
        profileName={profile.pref_name}
        isPending={deleteAction.isPending}
        onConfirm={deleteAction.confirmDelete}
      />
      <UnsavedChangesDialog
        open={blocker.status === 'blocked'}
        onConfirm={blocker.proceed}
        onCancel={blocker.reset}
      />
    </PageLayout>
  );
}

interface ProfileEditFormProps {
  readonly form: ReturnType<typeof useProfileEditForm>['form'];
  readonly onSubmit: (
    values: Parameters<ReturnType<typeof useProfileEditForm>['onSubmit']>[0],
  ) => void;
  readonly onCancel: () => void;
  readonly isPending: boolean;
}

function ProfileEditForm({
  form,
  onSubmit,
  onCancel,
  isPending,
}: ProfileEditFormProps): JSX.Element {
  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
        <fieldset disabled={isPending} className="space-y-6 disabled:opacity-70">
          <ProfileNameCard control={form.control} />
          <KeywordsCard control={form.control} />
          <SkillsCard control={form.control} />
          <ExperienceCard control={form.control} />
          <SalaryCard control={form.control} />
          <WorkArrangementsCard control={form.control} />
          <RelocationCard control={form.control} />
          <ThresholdsCard control={form.control} />
        </fieldset>
        <ProfileEditActions isPending={isPending} onCancel={onCancel} />
      </form>
    </Form>
  );
}

export { ProfileDetail };
