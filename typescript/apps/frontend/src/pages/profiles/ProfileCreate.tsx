import { Link } from '@tanstack/react-router';
import { Loader2, Plus } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ExperienceCard,
  KeywordsCard,
  ProfileNameCard,
  RelocationCard,
  SalaryCard,
  SkillsCard,
  ThresholdsCard,
  useProfileCreateForm,
  WorkArrangementsCard,
} from '@/features/profile-management/index.ts';
import { ROUTE_PATHS } from '@/shared/config/index.ts';
import { useDocumentTitle, useUnsavedChanges } from '@/shared/lib/index.ts';
import { Button } from '@/shared/ui/button.tsx';
import { Form } from '@/shared/ui/form.tsx';
import { PageHeader } from '@/shared/ui/index.ts';
import { UnsavedChangesDialog } from '@/shared/ui/unsaved-changes-dialog.tsx';
import { PageLayout } from '@/widgets/layout/index.ts';

function ProfileCreate(): JSX.Element {
  const { form, onSubmit, isPending } = useProfileCreateForm();
  const { isDirty, isSubmitSuccessful } = form.formState;
  const blocker = useUnsavedChanges(isDirty && !isSubmitSuccessful);

  return (
    <PageLayout contentWidth="narrow" className="space-y-6">
      <ProfileCreateHeader />
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
          <ProfileCreateActions isPending={isPending} />
        </form>
      </Form>
      <UnsavedChangesDialog
        open={blocker.status === 'blocked'}
        onConfirm={blocker.proceed}
        onCancel={blocker.reset}
      />
    </PageLayout>
  );
}

function ProfileCreateHeader(): JSX.Element {
  const { t } = useTranslation(['profiles']);

  useDocumentTitle(t('pages.create.title'));

  return (
    <PageHeader
      title={t('profiles:pages.create.title')}
      description={t('profiles:pages.create.description')}
      backTo={ROUTE_PATHS.PROFILES.LIST}
      preferHistory={true}
    />
  );
}

function ProfileCreateActions({ isPending }: { readonly isPending: boolean }): JSX.Element {
  const { t } = useTranslation(['profiles', 'common']);

  return (
    <div className="flex justify-end gap-3">
      <Button type="button" variant="outline" asChild={true}>
        <Link to={ROUTE_PATHS.PROFILES.LIST}>{t('common:actions.cancel')}</Link>
      </Button>
      <Button type="submit" disabled={isPending}>
        {isPending ? (
          <Loader2 className="mr-2 size-4 animate-spin" />
        ) : (
          <Plus className="mr-2 size-4" />
        )}
        {isPending ? t('profiles:pages.create.submitting') : t('profiles:actions.create')}
      </Button>
    </div>
  );
}

export { ProfileCreate };
