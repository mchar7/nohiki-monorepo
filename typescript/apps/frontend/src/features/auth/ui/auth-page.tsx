import { zodResolver } from '@hookform/resolvers/zod';
import type { TFunction } from 'i18next';
import { Command } from 'lucide-react';
import type { JSX } from 'react';
import { useId, useLayoutEffect, useState } from 'react';
import type { UseFormReturn } from 'react-hook-form';
import { useForm, useFormState } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { z } from 'zod';
import { ApiError, useLogin, useRegister } from '@/shared/api/index.ts';
import { AUTH_CONSTRAINTS, HTTP_STATUS } from '@/shared/config/index.ts';
import { cn, useDocumentTitle, useFormRootErrorClearOnEdit } from '@/shared/lib/index.ts';
import { Card, CardContent, CardHeader } from '@/shared/ui/card.tsx';
import { Form } from '@/shared/ui/form.tsx';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/shared/ui/tabs.tsx';
import { useLogoutWarningToast } from '../lib/useLogoutWarningToast.ts';
import { useRateLimitFormSync } from '../lib/useRateLimitFormSync.ts';
import { useRememberMe } from '../lib/useRememberMe.ts';
import { AuthFormFields } from './auth-form-fields.tsx';
import type { FormValues } from './auth-page.types.ts';
import { OAuthButtons } from './oauth-buttons.tsx';
import { SubmitButtonWithTooltip } from './submit-button-with-tooltip.tsx';
import { TermsFooter } from './terms-footer.tsx';

const BRAND_NAME = 'Nohiki';
const CONTROL_CHARACTER_RE = /\p{Cc}/u;
const WHITESPACE_RE = /\s+/gu;
const DEFAULT_RATE_LIMIT_SECONDS = 30;

type AuthMode = 'login' | 'register';

type TranslationFn = TFunction<readonly ['auth', 'common'], undefined>;

interface AuthErrorResult {
  readonly message: string;
  readonly retrySeconds: number | null;
}

function classifyAuthError(error: unknown, mode: AuthMode, t: TranslationFn): AuthErrorResult {
  if (error instanceof ApiError) {
    if (error.status === HTTP_STATUS.TOO_MANY_REQUESTS) {
      const seconds = error.retryAfter ?? DEFAULT_RATE_LIMIT_SECONDS;
      return { message: t('auth:errors.rateLimited', { seconds }), retrySeconds: seconds };
    }
    if (error.status === HTTP_STATUS.CONFLICT) {
      return { message: t('auth:errors.emailExists'), retrySeconds: null };
    }
  }
  return {
    message: mode === 'login' ? t('auth:errors.invalidCredentials') : t('auth:errors.generic'),
    retrySeconds: null,
  };
}

function createAuthSchema(t: TranslationFn, mode: AuthMode): z.ZodType<FormValues, FormValues> {
  const displayNameSchema = z
    .string()
    .refine((value) => !CONTROL_CHARACTER_RE.test(value), {
      error: t('auth:validation.displayName.controlCharacters'),
    })
    .transform((value) => value.trim().replace(WHITESPACE_RE, ' '))
    .pipe(
      z
        .string()
        .min(1, t('auth:validation.displayName.required'))
        .max(
          AUTH_CONSTRAINTS.DISPLAY_NAME_MAX_LENGTH,
          t('auth:validation.displayName.maxLength', {
            max: AUTH_CONSTRAINTS.DISPLAY_NAME_MAX_LENGTH,
          }),
        ),
    );

  const baseSchema = z.object({
    displayName: mode === 'register' ? displayNameSchema : z.string(),
    email: z.email({ error: t('auth:validation.email.invalid') }),
    password: z
      .string()
      .min(
        AUTH_CONSTRAINTS.PASSWORD_MIN_LENGTH,
        t('auth:validation.password.minLength', { min: AUTH_CONSTRAINTS.PASSWORD_MIN_LENGTH }),
      )
      .max(
        AUTH_CONSTRAINTS.PASSWORD_MAX_LENGTH,
        t('auth:validation.password.maxLength', { max: AUTH_CONSTRAINTS.PASSWORD_MAX_LENGTH }),
      ),
    confirmPassword: z.string(),
  });

  if (mode === 'register') {
    return baseSchema.refine((data) => data.password === data.confirmPassword, {
      error: t('auth:validation.confirmPassword.mismatch'),
      path: ['confirmPassword'],
    });
  }

  return baseSchema;
}

async function submitAuthForm(
  values: FormValues,
  mode: AuthMode,
  loginMutation: ReturnType<typeof useLogin>,
  registerMutation: ReturnType<typeof useRegister>,
): Promise<void> {
  if (mode === 'login') {
    await loginMutation.mutateAsync({ email: values.email, password: values.password });
  } else {
    await registerMutation.mutateAsync({
      email: values.email,
      password: values.password,
      display_name: values.displayName,
    });
  }
}

// ─── Auth Form Hook ──────────────────────────────────────────────────────────

interface AuthFormState {
  readonly form: UseFormReturn<FormValues>;
  readonly isPending: boolean;
  readonly isRateLimited: boolean;
  readonly isRegister: boolean;
  readonly rememberMe: boolean;
  readonly handleRememberMeChange: (checked: boolean) => void;
  readonly handleModeChange: (newMode: string) => void;
  readonly onSubmit: (values: FormValues) => Promise<void>;
}

function useAuthForm(
  t: TranslationFn,
  mode: AuthMode,
  setMode: (newMode: AuthMode) => void,
  onSuccess: (() => void) | undefined,
): AuthFormState {
  const loginMutation = useLogin();
  const registerMutation = useRegister();
  const isPending = loginMutation.isPending || registerMutation.isPending;
  const authSchema = createAuthSchema(t, mode);
  const { rememberedEmail, rememberMe, handleRememberMeChange, persistEmail } = useRememberMe();

  const form = useForm<FormValues>({
    resolver: zodResolver(authSchema),
    defaultValues: { displayName: '', email: rememberedEmail, password: '', confirmPassword: '' },
    mode: 'onChange',
  });

  useFormRootErrorClearOnEdit(form);
  const { isRateLimited, triggerRateLimit } = useRateLimitFormSync(form, (seconds) =>
    t('auth:errors.rateLimited', { seconds }),
  );
  useLogoutWarningToast(t('auth:session.logoutFailed'));

  const handleModeChange = (newMode: string): void => {
    form.clearErrors();
    setMode(newMode as AuthMode);
  };

  const onSubmit = async (values: FormValues): Promise<void> => {
    form.clearErrors('root');
    try {
      await submitAuthForm(values, mode, loginMutation, registerMutation);
      if (mode === 'login') {
        persistEmail(values.email);
      }
      onSuccess?.();
    } catch (error: unknown) {
      const { message, retrySeconds } = classifyAuthError(error, mode, t);
      if (retrySeconds !== null) {
        triggerRateLimit(retrySeconds);
      }
      form.setError('root', { message });
    }
  };

  return {
    form,
    isPending,
    isRateLimited,
    isRegister: mode === 'register',
    rememberMe,
    handleRememberMeChange,
    handleModeChange,
    onSubmit,
  };
}

// ─── Components ──────────────────────────────────────────────────────────────

interface AuthPageProps extends React.ComponentPropsWithoutRef<'div'> {
  defaultMode?: AuthMode;
  onSuccess?: () => void;
  returnUrl?: string | undefined;
}

function AuthPage({
  className,
  defaultMode = 'login',
  onSuccess,
  returnUrl,
  ...props
}: Readonly<AuthPageProps>): JSX.Element {
  const { t } = useTranslation(['auth', 'common']);
  const [mode, setMode] = useState<AuthMode>(defaultMode);
  const authFormPanelId = `auth-form-panel-${useId()}`;
  useLayoutEffect(() => {
    setMode(defaultMode);
  }, [defaultMode]);
  useDocumentTitle(t(mode === 'login' ? 'auth:pages.login.title' : 'auth:pages.register.title'));

  const auth = useAuthForm(t, mode, setMode, onSuccess);

  return (
    <div className={cn('flex w-full max-w-[27rem] flex-col', className)} {...props}>
      <BrandingHeader />
      <Card className="w-full overflow-hidden rounded-2xl border-border/70 bg-card/95 shadow-[0_18px_60px_-32px_hsl(var(--foreground)/0.35)] backdrop-blur-sm">
        <Tabs value={mode} onValueChange={auth.handleModeChange} className="w-full gap-0">
          <CardHeader className="space-y-4 px-4 pt-4 pb-0 sm:px-6 sm:pt-6">
            <div className="space-y-1 text-center">
              <h1 className="font-semibold text-2xl tracking-tight">
                {t(mode === 'login' ? 'auth:pages.login.title' : 'auth:pages.register.title')}
              </h1>
              <p className="text-balance text-muted-foreground text-sm">
                {t(mode === 'login' ? 'auth:pages.login.subtitle' : 'auth:pages.register.subtitle')}
              </p>
            </div>
            <TabsList className="grid h-10 w-full grid-cols-2 rounded-xl bg-muted/70 p-1">
              <TabsTrigger aria-controls={authFormPanelId} className="h-8 rounded-lg" value="login">
                {t('auth:actions.signIn')}
              </TabsTrigger>
              <TabsTrigger
                aria-controls={authFormPanelId}
                className="h-8 rounded-lg"
                value="register"
              >
                {t('auth:actions.signUp')}
              </TabsTrigger>
            </TabsList>
          </CardHeader>
          <CardContent className="px-4 pt-4 pb-4 sm:px-6 sm:pt-5 sm:pb-5">
            <TabsContent id={authFormPanelId} value={mode} forceMount className="m-0 p-0">
              <div className="grid gap-4">
                <OAuthButtons returnUrl={returnUrl} />
                <OrDivider />
                <AuthFormSection {...auth} />
                <TermsFooter />
              </div>
            </TabsContent>
          </CardContent>
        </Tabs>
      </Card>
    </div>
  );
}

function AuthFormSection({
  form,
  isPending,
  isRateLimited,
  isRegister,
  rememberMe,
  handleRememberMeChange,
  onSubmit,
}: Readonly<AuthFormState>): JSX.Element {
  // form.formState is a Proxy whose updates are invisible to React Compiler's
  // memoization; useFormState subscribes explicitly so re-renders fire.
  // RHF's isValid counts root errors (set via setError('root')) which would
  // disable the submit button after a failed login, preventing retries.
  // Compute field-level validity that excludes root errors.
  const { errors: formErrors } = useFormState({ control: form.control });
  const isValid = !Object.keys(formErrors).some((key) => key !== 'root');

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)}>
        <fieldset disabled={isRateLimited} className="space-y-4">
          <AuthFormFields
            form={form}
            isRegister={isRegister}
            rememberMe={rememberMe}
            onRememberMeChange={handleRememberMeChange}
          />
          <SubmitButtonWithTooltip
            isPending={isPending}
            isValid={isValid}
            isRegister={isRegister}
          />
        </fieldset>
      </form>
    </Form>
  );
}

function BrandingHeader(): JSX.Element {
  return (
    <a href="/" className="mb-3 flex items-center gap-2.5 self-center font-semibold tracking-tight">
      <div className="flex size-8 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
        <Command className="size-4.5" aria-hidden="true" />
      </div>
      <span className="text-lg">{BRAND_NAME}</span>
    </a>
  );
}

function OrDivider(): JSX.Element {
  const { t } = useTranslation(['auth']);

  return (
    <div className="relative flex items-center">
      <div className="h-px flex-1 bg-border" aria-hidden="true" />
      <span className="px-3 text-muted-foreground text-xs">{t('auth:social.orContinueWith')}</span>
      <div className="h-px flex-1 bg-border" aria-hidden="true" />
    </div>
  );
}

export { AuthPage, createAuthSchema };
