import type { SkillSearchResponse } from '@/shared/api/index.ts';

interface SkillInputProps {
  readonly value: SkillSearchResponse['skills'];
  readonly onChange: (skills: SkillSearchResponse['skills']) => void;
  readonly placeholder?: string;
  readonly maxSkills?: number;
  readonly disabled?: boolean;
}

export type { SkillInputProps };
