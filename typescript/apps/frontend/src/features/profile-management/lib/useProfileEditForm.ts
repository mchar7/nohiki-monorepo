import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { type UseFormReturn, useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import type { ProfileResponse } from '@/shared/api';
import { hydrateSkillIds } from '@/shared/api';
import { extractErrorReason } from '@/shared/lib/index.ts';
import { useUpdateProfile } from '../api/index.ts';
import { createProfileSchema, type ProfileFormValues } from '../model/index.ts';
import { formValuesToUpdatePayload, profileToFormValues } from './profile.transforms.ts';

interface UseProfileEditFormOptions {
  profileId: string;
  profile: ProfileResponse;
}

interface UseProfileEditFormResult {
  form: UseFormReturn<ProfileFormValues>;
  isEditing: boolean;
  isHydrating: boolean;
  startEditing: () => void;
  cancelEditing: () => void;
  onSubmit: (values: ProfileFormValues) => Promise<void>;
  isPending: boolean;
}

/**
 * Hook encapsulating profile edit form logic with view/edit mode toggle.
 *
 * When startEditing is called, user skill IDs from the profile are hydrated
 * into full SkillSearchResult objects via the batch API before the form is populated.
 * Search keywords are already literal strings and require no hydration.
 */
export function useProfileEditForm({
  profileId,
  profile,
}: UseProfileEditFormOptions): UseProfileEditFormResult {
  const { t } = useTranslation(['profiles', 'common']);
  const [isEditing, setIsEditing] = useState(false);
  const [isHydrating, setIsHydrating] = useState(false);
  const updateMutation = useUpdateProfile();

  const form = useForm({
    resolver: zodResolver(createProfileSchema(t)),
    mode: 'onBlur',
  });

  const startEditing = (): void => {
    setIsHydrating(true);
    const originalSkillIds = new Set(profile.user_skills ?? []);
    hydrateSkillIds([...originalSkillIds])
      .then((hydratedUserSkills) => {
        const hydratedSkillIds = new Set(hydratedUserSkills.map((skill) => skill.id));
        const isComplete =
          hydratedSkillIds.size === originalSkillIds.size &&
          [...originalSkillIds].every((skillId) => hydratedSkillIds.has(skillId));
        if (!isComplete) {
          toast.error(t('profiles:pages.detail.hydrationIncomplete'));
          return;
        }
        form.reset(profileToFormValues(profile, hydratedUserSkills));
        setIsEditing(true);
      })
      .catch((error: unknown) => {
        const reason = extractErrorReason(error);
        toast.error(
          reason
            ? t('profiles:pages.detail.hydrationError', { reason })
            : t('profiles:pages.detail.hydrationErrorFallback'),
        );
      })
      .finally(() => {
        setIsHydrating(false);
      });
  };

  const cancelEditing = (): void => {
    form.reset();
    setIsEditing(false);
  };

  const onSubmit = async (values: ProfileFormValues): Promise<void> => {
    try {
      const payload = formValuesToUpdatePayload(values);
      await updateMutation.mutateAsync({ params: { path: { pref_id: profileId } }, body: payload });
      toast.success(t('profiles:pages.detail.success'));
      setIsEditing(false);
    } catch (error: unknown) {
      const reason = extractErrorReason(error);
      toast.error(
        reason
          ? t('profiles:pages.detail.updateError', { reason })
          : t('profiles:pages.detail.updateErrorFallback'),
      );
    }
  };

  return {
    form,
    isEditing,
    isHydrating,
    startEditing,
    cancelEditing,
    onSubmit,
    isPending: updateMutation.isPending,
  };
}
