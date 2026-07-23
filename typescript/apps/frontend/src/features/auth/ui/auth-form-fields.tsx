import type { JSX } from 'react';
import { useId, useState } from 'react';
import type { Control, ControllerRenderProps, UseFormReturn } from 'react-hook-form';
import { useFormState, useWatch } from 'react-hook-form';
import { useTranslation } from 'react-i18next';

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/shared/ui/alert-dialog.tsx';
import { Checkbox } from '@/shared/ui/checkbox.tsx';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/shared/ui/form.tsx';
import { FormRootError } from '@/shared/ui/form-root-error.tsx';
import { Input } from '@/shared/ui/input.tsx';
import { Label } from '@/shared/ui/label.tsx';
import { PasswordInput } from '@/shared/ui/password-input.tsx';
import { PasswordStrength } from '@/shared/ui/password-strength.tsx';
import type { FormValues } from './auth-page.types.ts';

interface AuthFormFieldsProps {
  readonly form: UseFormReturn<FormValues>;
  readonly isRegister: boolean;
  readonly rememberMe: boolean;
  readonly onRememberMeChange: (checked: boolean) => void;
}

function AuthFormFields({
  form,
  isRegister,
  rememberMe,
  onRememberMeChange,
}: AuthFormFieldsProps): JSX.Element {
  const { t } = useTranslation(['auth', 'common']);
  // form.formState is a Proxy whose updates are invisible to React Compiler;
  // useFormState subscribes explicitly so error changes trigger re-renders.
  const { errors } = useFormState({ control: form.control });
  const [forgotOpen, setForgotOpen] = useState(false);
  const rememberMeId = useId();

  return (
    <>
      {isRegister ? (
        <FormField control={form.control} name="displayName" render={renderDisplayNameField(t)} />
      ) : null}

      <FormField control={form.control} name="email" render={renderEmailField(t)} />
      <FormField
        control={form.control}
        name="password"
        render={renderPasswordField(t, isRegister)}
      />

      {!isRegister && (
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Checkbox
              id={rememberMeId}
              checked={rememberMe}
              onCheckedChange={(checked: boolean | 'indeterminate') => {
                onRememberMeChange(checked === true);
              }}
            />
            <Label htmlFor={rememberMeId} className="text-sm">
              {t('pages.login.rememberMe')}
            </Label>
          </div>
          <button
            type="button"
            onClick={() => {
              setForgotOpen(true);
            }}
            className="text-muted-foreground text-sm hover:text-primary"
          >
            {t('pages.login.forgotPassword')}
          </button>
        </div>
      )}

      {isRegister ? (
        <div className="space-y-3">
          <WatchedPasswordStrength control={form.control} />
          <FormField
            control={form.control}
            name="confirmPassword"
            render={renderConfirmPasswordField(t)}
          />
        </div>
      ) : null}

      <FormRootError error={errors.root?.message} />

      <AlertDialog open={forgotOpen} onOpenChange={setForgotOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('pages.login.forgotPasswordDialog.title')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('pages.login.forgotPasswordDialog.description')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogAction>{t('pages.login.forgotPasswordDialog.close')}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

/** Isolates password-change re-renders to the strength indicator only. */
function WatchedPasswordStrength({
  control,
}: {
  readonly control: Control<FormValues>;
}): JSX.Element {
  const password = useWatch({ control, name: 'password' });
  return <PasswordStrength password={password} />;
}

type TranslationFn = ReturnType<typeof useTranslation<['auth', 'common']>>['t'];

function renderDisplayNameField(
  t: TranslationFn,
): (props: { field: ControllerRenderProps<FormValues, 'displayName'> }) => JSX.Element {
  return ({ field }: { field: ControllerRenderProps<FormValues, 'displayName'> }): JSX.Element => (
    <FormItem>
      <FormLabel>{t('auth:fields.displayName.label')}</FormLabel>
      <FormControl>
        <Input
          type="text"
          placeholder={t('auth:fields.displayName.placeholder')}
          autoComplete="name"
          maxLength={255}
          required={true}
          {...field}
        />
      </FormControl>
      <FormMessage />
    </FormItem>
  );
}

function renderEmailField(
  t: TranslationFn,
): (props: { field: ControllerRenderProps<FormValues, 'email'> }) => JSX.Element {
  return ({ field }: { field: ControllerRenderProps<FormValues, 'email'> }): JSX.Element => (
    <FormItem>
      <FormLabel>{t('auth:fields.email.label')}</FormLabel>
      <FormControl>
        <Input
          type="email"
          placeholder={t('auth:fields.email.placeholder')}
          autoComplete="email"
          {...field}
        />
      </FormControl>
      <FormMessage />
    </FormItem>
  );
}

function renderPasswordField(
  t: TranslationFn,
  isRegister: boolean,
): (props: { field: ControllerRenderProps<FormValues, 'password'> }) => JSX.Element {
  return ({ field }: { field: ControllerRenderProps<FormValues, 'password'> }): JSX.Element => {
    const passwordAutoComplete = isRegister ? 'new-password' : 'current-password';
    return (
      <FormItem>
        <FormLabel>{t('auth:fields.password.label')}</FormLabel>
        <FormControl>
          <PasswordInput
            placeholder={t('auth:fields.password.placeholder')}
            autoComplete={passwordAutoComplete}
            {...field}
          />
        </FormControl>
        <FormMessage />
      </FormItem>
    );
  };
}

function renderConfirmPasswordField(
  t: TranslationFn,
): (props: { field: ControllerRenderProps<FormValues, 'confirmPassword'> }) => JSX.Element {
  return ({
    field,
  }: {
    field: ControllerRenderProps<FormValues, 'confirmPassword'>;
  }): JSX.Element => (
    <FormItem>
      <FormLabel>{t('auth:fields.confirmPassword.label')}</FormLabel>
      <FormControl>
        <PasswordInput
          placeholder={t('auth:fields.confirmPassword.placeholder')}
          autoComplete="new-password"
          {...field}
        />
      </FormControl>
      <FormMessage />
    </FormItem>
  );
}

export { AuthFormFields };
