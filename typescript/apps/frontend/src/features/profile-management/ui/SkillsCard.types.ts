import type { Control } from 'react-hook-form';
import type { ProfileFormValues } from '../model/index.ts';

interface SkillsCardProps {
  readonly control: Control<ProfileFormValues>;
}

export type { SkillsCardProps };
