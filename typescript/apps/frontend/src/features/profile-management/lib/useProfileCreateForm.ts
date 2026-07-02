import { zodResolver } from '@hookform/resolvers/zod';
import { useNavigate } from '@tanstack/react-router';
import { useEffect } from 'react';
import { type UseFormReturn, useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { ROUTE_PATHS } from '@/shared/config/index.ts';
import { extractErrorReason } from '@/shared/lib/index.ts';
import { useCreateProfile } from '../api/index.ts';
import {
  createProfileSchema,
  PROFILE_FORM_DEFAULTS,
  type ProfileFormValues,
} from '../schemas/index.ts';
import { formValuesToCreatePayload } from './profile.transforms.ts';

interface UseProfileCreateFormResult {
  form: UseFormReturn<ProfileFormValues>;
  onSubmit: (values: ProfileFormValues) => Promise<void>;
  isPending: boolean;
}

/**
 * Hook encapsulating all profile creation form logic.
 * Separates business logic from UI presentation.
 */
export function useProfileCreateForm(): UseProfileCreateFormResult {
  const { t } = useTranslation(['profiles', 'common']);
  const navigate = useNavigate();
  const createMutation = useCreateProfile();

  const form = useForm({
    resolver: zodResolver(createProfileSchema(t)),
    defaultValues: PROFILE_FORM_DEFAULTS,
    mode: 'onBlur',
  });

  // Destructure to subscribe to formState changes via react-hook-form's Proxy;
  // accessing properties only inside useEffect deps doesn't trigger re-renders
  const { isSubmitSuccessful } = form.formState;

  // Navigate after successful submission in a separate render cycle;
  // the blocker skips blocking when isSubmitSuccessful is true
  useEffect(() => {
    if (isSubmitSuccessful) {
      form.reset();
      navigate({ to: ROUTE_PATHS.PROFILES.LIST });
    }
  }, [isSubmitSuccessful, form, navigate]);

  const onSubmit = async (values: ProfileFormValues): Promise<void> => {
    form.clearErrors('root');
    try {
      const payload = formValuesToCreatePayload(values);
      await createMutation.mutateAsync({ body: payload });
      toast.success(t('profiles:pages.create.success'));
    } catch (error: unknown) {
      const reason = extractErrorReason(error);
      const message = reason
        ? t('profiles:pages.create.error', { reason })
        : t('profiles:pages.create.errorFallback');
      form.setError('root', { type: 'server', message });
      toast.error(message);
    }
  };

  return {
    form,
    onSubmit,
    isPending: createMutation.isPending,
  };
}
