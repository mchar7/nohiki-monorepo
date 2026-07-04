import { zodResolver } from '@hookform/resolvers/zod';
import type { TFunction } from 'i18next';
import { Loader2 } from 'lucide-react';
import { type JSX, useId } from 'react';
import type { ControllerRenderProps, UseFormReturn } from 'react-hook-form';
import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { z } from 'zod';
import type { UserResponse } from '@/shared/api';
import { AUTH_CONSTRAINTS } from '@/shared/config/index.ts';
import { TOAST_ERROR, TOAST_SUCCESS } from '@/shared/lib';
import { extractErrorReason, useUnsavedChanges } from '@/shared/lib/index.ts';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/shared/ui/form.tsx';
import { Input } from '@/shared/ui/input.tsx';
import { OptionalIndicator } from '@/shared/ui/optional-indicator.tsx';
import { UnsavedChangesDialog } from '@/shared/ui/unsaved-changes-dialog.tsx';
import { useUpdateAccount } from '../api/index.ts';
import { AvatarUploadSection } from './AvatarUploadSection.tsx';

const CONTROL_CHARACTER_RE = /\p{Cc}/u;
const WHITESPACE_RE = /\s+/gu;

interface ProfileFormInput {
  first_name?: string | null;
  last_name?: string | null;
  display_name: string;
}

interface ProfileFormValues extends ProfileFormInput {}

function createProfileSchema(
  t: TFunction<readonly ['account', 'common'], undefined>,
): z.ZodType<ProfileFormValues, ProfileFormInput> {
  return z.object({
    first_name: z
      .string()
      .max(
        AUTH_CONSTRAINTS.NAME_MAX_LENGTH,
        t('account:validation.firstName.maxLength', { max: AUTH_CONSTRAINTS.NAME_MAX_LENGTH }),
      )
      .nullable()
      .optional(),
    last_name: z
      .string()
      .max(
        AUTH_CONSTRAINTS.NAME_MAX_LENGTH,
        t('account:validation.lastName.maxLength', { max: AUTH_CONSTRAINTS.NAME_MAX_LENGTH }),
      )
      .nullable()
      .optional(),
    display_name: z
      .string()
      .refine((value) => !CONTROL_CHARACTER_RE.test(value), {
        error: t('account:validation.displayName.controlCharacters'),
      })
      .transform((value) => value.trim().replace(WHITESPACE_RE, ' '))
      .pipe(
        z
          .string()
          .min(1, t('account:validation.displayName.required'))
          .max(
            AUTH_CONSTRAINTS.DISPLAY_NAME_MAX_LENGTH,
            t('account:validation.displayName.maxLength', {
              max: AUTH_CONSTRAINTS.DISPLAY_NAME_MAX_LENGTH,
            }),
          ),
      ),
  });
}

interface ProfileSectionProps {
  readonly account: UserResponse;
}

function ProfileSection({ account }: ProfileSectionProps): JSX.Element {
  const { t } = useTranslation(['account', 'common']);
  const updateMutation = useUpdateAccount();
  const schema = createProfileSchema(t);

  const form = useForm<ProfileFormInput, unknown, ProfileFormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      first_name: account.first_name,
      last_name: account.last_name,
      display_name: account.display_name ?? '',
    },
    mode: 'onBlur',
  });

  const blocker = useUnsavedChanges(form.formState.isDirty);

  const onSubmit = async (values: ProfileFormValues): Promise<void> => {
    try {
      await updateMutation.mutateAsync({
        body: {
          first_name: values.first_name ?? null,
          last_name: values.last_name ?? null,
          display_name: values.display_name,
        },
      });
      toast.success(t(TOAST_SUCCESS.PROFILE_UPDATED));
    } catch (error: unknown) {
      const reason = extractErrorReason(error);
      toast.error(
        reason
          ? t(TOAST_ERROR.PROFILE_UPDATE_FAILED, { reason })
          : t('account:feedback.updateErrorFallback'),
      );
    }
  };

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>{t('account:sections.profile.title')}</CardTitle>
          <CardDescription>{t('account:sections.profile.description')}</CardDescription>
        </CardHeader>
        <CardContent>
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
              <AvatarUploadSection account={account} />
              <EmailDisplay email={account.email} />
              <fieldset
                disabled={updateMutation.isPending}
                className="space-y-4 disabled:opacity-70"
              >
                <NameFields form={form} />
                <DisplayNameField form={form} />
              </fieldset>
              <SubmitButton isPending={updateMutation.isPending} />
            </form>
          </Form>
        </CardContent>
      </Card>
      <UnsavedChangesDialog
        open={blocker.status === 'blocked'}
        onConfirm={blocker.proceed}
        onCancel={blocker.reset}
      />
    </>
  );
}

function EmailDisplay({ email }: { readonly email: string }): JSX.Element {
  const { t } = useTranslation(['account']);
  const emailId = useId();

  return (
    <div className="space-y-2">
      <label htmlFor={emailId} className="font-medium text-sm">
        {t('account:fields.email.label')}
      </label>
      <Input id={emailId} value={email} disabled={true} />
      <p className="text-muted-foreground text-sm">{t('account:fields.email.description')}</p>
    </div>
  );
}

interface FieldsProps {
  readonly form: UseFormReturn<ProfileFormInput, unknown, ProfileFormValues>;
}

function NameFields({ form }: FieldsProps): JSX.Element {
  const { t } = useTranslation(['account']);

  const renderFirstName = ({
    field,
  }: {
    field: ControllerRenderProps<ProfileFormInput, 'first_name'>;
  }): JSX.Element => (
    <FormItem>
      <FormLabel>
        {t('account:fields.firstName.label')} <OptionalIndicator />
      </FormLabel>
      <FormControl>
        <Input
          placeholder={t('account:fields.firstName.placeholder')}
          {...field}
          value={field.value ?? ''}
        />
      </FormControl>
      <FormMessage />
    </FormItem>
  );

  const renderLastName = ({
    field,
  }: {
    field: ControllerRenderProps<ProfileFormInput, 'last_name'>;
  }): JSX.Element => (
    <FormItem>
      <FormLabel>
        {t('account:fields.lastName.label')} <OptionalIndicator />
      </FormLabel>
      <FormControl>
        <Input
          placeholder={t('account:fields.lastName.placeholder')}
          {...field}
          value={field.value ?? ''}
        />
      </FormControl>
      <FormMessage />
    </FormItem>
  );

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <FormField control={form.control} name="first_name" render={renderFirstName} />
      <FormField control={form.control} name="last_name" render={renderLastName} />
    </div>
  );
}

function DisplayNameField({ form }: FieldsProps): JSX.Element {
  const { t } = useTranslation(['account']);

  const renderDisplayName = ({
    field,
  }: {
    field: ControllerRenderProps<ProfileFormInput, 'display_name'>;
  }): JSX.Element => (
    <FormItem>
      <FormLabel>{t('account:fields.displayName.label')}</FormLabel>
      <FormControl>
        <Input
          placeholder={t('account:fields.displayName.placeholder')}
          maxLength={AUTH_CONSTRAINTS.DISPLAY_NAME_MAX_LENGTH}
          required={true}
          {...field}
        />
      </FormControl>
      <FormDescription>{t('account:fields.displayName.description')}</FormDescription>
      <FormMessage />
    </FormItem>
  );

  return <FormField control={form.control} name="display_name" render={renderDisplayName} />;
}

function SubmitButton({ isPending }: { readonly isPending: boolean }): JSX.Element {
  const { t } = useTranslation(['account']);

  return (
    <Button type="submit" disabled={isPending}>
      {isPending ? <Loader2 className="mr-2 size-4 animate-spin" aria-hidden="true" /> : null}
      {isPending ? t('account:actions.saving') : t('account:actions.save')}
    </Button>
  );
}

export { createProfileSchema, ProfileSection };
