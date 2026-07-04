import { zodResolver } from '@hookform/resolvers/zod';
import { Loader2 } from 'lucide-react';
import type { JSX } from 'react';
import type { ControllerRenderProps } from 'react-hook-form';
import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { z } from 'zod';
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
import { PasswordStrength } from '@/shared/ui/index.ts';
import { Input } from '@/shared/ui/input.tsx';
import { UnsavedChangesDialog } from '@/shared/ui/unsaved-changes-dialog.tsx';
import { useUpdateAccount } from '../api/index.ts';

interface PasswordFormValues {
  currentPassword: string;
  newPassword: string;
  confirmPassword: string;
}

function createPasswordSchema(t: ReturnType<typeof useTranslation<['account']>>['t']): z.ZodObject<{
  currentPassword: z.ZodString;
  newPassword: z.ZodString;
  confirmPassword: z.ZodString;
}> {
  return z
    .object({
      currentPassword: z.string().min(1, t('account:validation.currentPassword.required')),
      newPassword: z.string().min(
        AUTH_CONSTRAINTS.PASSWORD_MIN_LENGTH,
        t('account:validation.newPassword.minLength', {
          min: AUTH_CONSTRAINTS.PASSWORD_MIN_LENGTH,
        }),
      ),
      confirmPassword: z.string(),
    })
    .refine((data) => data.newPassword === data.confirmPassword, {
      error: t('account:validation.confirmPassword.mismatch'),
      path: ['confirmPassword'],
    });
}

function SecuritySection(): JSX.Element {
  const { t } = useTranslation(['account', 'common']);
  const updateMutation = useUpdateAccount();
  const schema = createPasswordSchema(t);

  const form = useForm<PasswordFormValues>({
    resolver: zodResolver(schema),
    defaultValues: { currentPassword: '', newPassword: '', confirmPassword: '' },
    mode: 'onBlur',
  });

  const blocker = useUnsavedChanges(form.formState.isDirty);

  const onSubmit = async (values: PasswordFormValues): Promise<void> => {
    try {
      await updateMutation.mutateAsync({ body: { password: values.newPassword } });
      toast.success(t(TOAST_SUCCESS.PASSWORD_CHANGED));
      form.reset();
    } catch (error: unknown) {
      const reason = extractErrorReason(error);
      toast.error(
        reason
          ? t(TOAST_ERROR.PASSWORD_CHANGE_FAILED, { reason })
          : t('account:feedback.passwordErrorFallback'),
      );
    }
  };

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>{t('account:sections.security.title')}</CardTitle>
          <CardDescription>{t('account:sections.security.description')}</CardDescription>
        </CardHeader>
        <CardContent>
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
              <fieldset
                disabled={updateMutation.isPending}
                className="space-y-4 disabled:opacity-70"
              >
                <PasswordFields form={form} />
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

interface FieldsProps {
  readonly form: ReturnType<typeof useForm<PasswordFormValues>>;
}

function PasswordFields({ form }: FieldsProps): JSX.Element {
  const { t } = useTranslation(['account']);
  const newPassword = form.watch('newPassword');

  const renderCurrentPassword = ({
    field,
  }: {
    field: ControllerRenderProps<PasswordFormValues, 'currentPassword'>;
  }): JSX.Element => (
    <FormItem>
      <FormLabel>{t('account:fields.currentPassword.label')}</FormLabel>
      <FormControl>
        <Input
          type="password"
          placeholder={t('account:fields.currentPassword.placeholder')}
          {...field}
        />
      </FormControl>
      <FormMessage />
    </FormItem>
  );

  const renderNewPassword = ({
    field,
  }: {
    field: ControllerRenderProps<PasswordFormValues, 'newPassword'>;
  }): JSX.Element => (
    <FormItem>
      <FormLabel>{t('account:fields.newPassword.label')}</FormLabel>
      <FormControl>
        <Input
          type="password"
          placeholder={t('account:fields.newPassword.placeholder')}
          {...field}
        />
      </FormControl>
      <FormDescription>
        {t('account:fields.newPassword.hint', { min: AUTH_CONSTRAINTS.PASSWORD_MIN_LENGTH })}
      </FormDescription>
      <FormMessage />
    </FormItem>
  );

  const renderConfirmPassword = ({
    field,
  }: {
    field: ControllerRenderProps<PasswordFormValues, 'confirmPassword'>;
  }): JSX.Element => (
    <FormItem>
      <FormLabel>{t('account:fields.confirmPassword.label')}</FormLabel>
      <FormControl>
        <Input
          type="password"
          placeholder={t('account:fields.confirmPassword.placeholder')}
          {...field}
        />
      </FormControl>
      <FormMessage />
    </FormItem>
  );

  return (
    <div className="space-y-4">
      <FormField control={form.control} name="currentPassword" render={renderCurrentPassword} />
      <FormField control={form.control} name="newPassword" render={renderNewPassword} />
      <PasswordStrength password={newPassword} />
      <FormField control={form.control} name="confirmPassword" render={renderConfirmPassword} />
    </div>
  );
}

function SubmitButton({ isPending }: { readonly isPending: boolean }): JSX.Element {
  const { t } = useTranslation(['account']);

  return (
    <Button type="submit" disabled={isPending}>
      {isPending ? <Loader2 className="mr-2 size-4 animate-spin" aria-hidden="true" /> : null}
      {isPending ? t('account:actions.saving') : t('account:actions.changePassword')}
    </Button>
  );
}

export { SecuritySection };
