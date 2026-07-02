import type { Control } from 'react-hook-form';
import type { ProfileFormValues } from '../schemas/index.ts';

interface SkillsCardProps {
  readonly control: Control<ProfileFormValues>;
}

export type { SkillsCardProps };
