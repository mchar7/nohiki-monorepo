import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/shared/lib/utils/utils.ts';
import { Progress } from './progress.tsx';

interface PasswordStrengthProps {
  readonly password: string;
  readonly className?: string;
}

interface StrengthResult {
  score: number;
  label: string;
  color: string;
}

const STRENGTH_COLORS = [
  'bg-destructive',
  'bg-orange-500',
  'bg-yellow-500',
  'bg-green-500',
] as const;

const LOWERCASE_RE = /[a-z]/u;
const UPPERCASE_RE = /[A-Z]/u;
const DIGIT_RE = /\d/u;
const SPECIAL_CHAR_RE = /[!@#$%^&*(),.?":{}|<>]/u;

const MIN_PASSWORD_LENGTH_WEAK: number = 8;
const MIN_PASSWORD_LENGTH_STRONG: number = 12;
const TOTAL_PASSWORD_CRITERIA: number = 5;
const STRENGTH_SCALE: number = 4;
const MAX_STRENGTH_INDEX: number = 3;

function calculateStrength(password: string): StrengthResult {
  if (!password) {
    return { score: 0, label: 'empty', color: STRENGTH_COLORS[0] };
  }

  let score = 0;
  const len = password.length;

  if (len >= MIN_PASSWORD_LENGTH_WEAK) {
    score += 1;
  }
  if (len >= MIN_PASSWORD_LENGTH_STRONG) {
    score += 1;
  }
  if (LOWERCASE_RE.test(password) && UPPERCASE_RE.test(password)) {
    score += 1;
  }
  if (DIGIT_RE.test(password)) {
    score += 1;
  }
  if (SPECIAL_CHAR_RE.test(password)) {
    score += 1;
  }

  const normalizedScore = Math.min(
    Math.floor((score / TOTAL_PASSWORD_CRITERIA) * STRENGTH_SCALE),
    MAX_STRENGTH_INDEX,
  );
  const labels = ['weak', 'fair', 'good', 'strong'] as const;

  return {
    score: normalizedScore,
    label: labels[normalizedScore] ?? 'weak',
    color: STRENGTH_COLORS[normalizedScore] ?? 'bg-destructive',
  };
}

const STRENGTH_LABELS = {
  weak: 'validation.password.weak',
  fair: 'validation.password.fair',
  good: 'validation.password.good',
  strong: 'validation.password.strong',
} as const;

type StrengthLabelKey = (typeof STRENGTH_LABELS)[keyof typeof STRENGTH_LABELS];

export function PasswordStrength({
  password,
  className,
}: PasswordStrengthProps): JSX.Element | null {
  const { t } = useTranslation('auth');

  const strength = calculateStrength(password);
  const PROGRESS_MAX_PERCENT: number = 100;
  const progressValue = password
    ? ((strength.score + 1) / STRENGTH_SCALE) * PROGRESS_MAX_PERCENT
    : 0;

  if (!password) {
    return null;
  }

  const labelKey: StrengthLabelKey =
    STRENGTH_LABELS[strength.label as keyof typeof STRENGTH_LABELS] ?? 'validation.password.weak';

  const TEXT_COLORS = [
    'text-destructive',
    'text-orange-500',
    'text-yellow-600',
    'text-green-600',
  ] as const;
  const textColorClass = TEXT_COLORS[strength.score];

  return (
    <div className={cn('space-y-1', className)}>
      <Progress
        value={progressValue}
        className={cn(
          'h-1.5 transition-all duration-200',
          strength.color.replace('bg-', '[&>div]:bg-'),
        )}
      />
      <p className={cn('text-center text-xs transition-colors duration-200', textColorClass)}>
        {t(labelKey)}
      </p>
    </div>
  );
}
