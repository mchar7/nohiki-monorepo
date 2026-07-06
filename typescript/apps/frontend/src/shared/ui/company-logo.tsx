import { Building2 } from 'lucide-react';
import { type JSX, useState } from 'react';
import { cn } from '@/shared/lib';

interface CompanyLogoProps {
  readonly companyName: string | null;
  readonly logoUrl?: string | null;
  readonly size?: 'sm' | 'md';
}

/**
 * Deterministic palette: hue is derived from company name so the same
 * company always gets the same colour across sessions and re-renders.
 */
const COLOR_PALETTE = [
  { bg: 'bg-rose-100 dark:bg-rose-900/40', text: 'text-rose-700 dark:text-rose-300' },
  { bg: 'bg-orange-100 dark:bg-orange-900/40', text: 'text-orange-700 dark:text-orange-300' },
  { bg: 'bg-amber-100 dark:bg-amber-900/40', text: 'text-amber-700 dark:text-amber-300' },
  { bg: 'bg-emerald-100 dark:bg-emerald-900/40', text: 'text-emerald-700 dark:text-emerald-300' },
  { bg: 'bg-sky-100 dark:bg-sky-900/40', text: 'text-sky-700 dark:text-sky-300' },
  { bg: 'bg-violet-100 dark:bg-violet-900/40', text: 'text-violet-700 dark:text-violet-300' },
  { bg: 'bg-pink-100 dark:bg-pink-900/40', text: 'text-pink-700 dark:text-pink-300' },
  { bg: 'bg-teal-100 dark:bg-teal-900/40', text: 'text-teal-700 dark:text-teal-300' },
] as const;

/** Djb2-style hash avoids bitwise ops by using addition only. */
const HASH_SEED = 5381;
const HASH_MULTIPLIER = 33;

function hashCompanyName(name: string): number {
  let hash = HASH_SEED;
  for (let i = 0; i < name.length; i += 1) {
    hash = hash * HASH_MULTIPLIER + name.charCodeAt(i);
  }
  return Math.abs(hash) % COLOR_PALETTE.length;
}

/** Renders a coloured circle with the first letter of the company name. */
function InitialAvatar({
  companyName,
  sizeClasses,
}: {
  readonly companyName: string;
  readonly sizeClasses: string;
}): JSX.Element {
  const colorEntry = COLOR_PALETTE[hashCompanyName(companyName)];
  const bg = colorEntry?.bg ?? 'bg-muted';
  const text = colorEntry?.text ?? 'text-muted-foreground';
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-full font-semibold leading-none',
        sizeClasses,
        bg,
        text,
      )}
      aria-hidden="true"
    >
      {companyName[0]?.toUpperCase() ?? '?'}
    </span>
  );
}

/**
 * Renders a company avatar: a `<img>` when `logoUrl` is provided (with
 * initial-avatar `onError` fallback), a coloured initial circle when only
 * `companyName` is known, or a `Building2` icon as the final fallback.
 */
function CompanyLogo({ companyName, logoUrl, size = 'sm' }: CompanyLogoProps): JSX.Element {
  const [imgError, setImgError] = useState(false);

  const sizeClasses = size === 'sm' ? 'size-6 text-xs' : 'size-8 text-sm';
  const iconSize = size === 'sm' ? 'size-3.5' : 'size-4';

  if (logoUrl && !imgError) {
    return (
      <span
        className={cn(
          'inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full',
          sizeClasses,
        )}
      >
        <img
          src={logoUrl}
          alt=""
          aria-hidden="true"
          width={32}
          height={32}
          className="size-full object-contain"
          onError={() => {
            setImgError(true);
          }}
        />
      </span>
    );
  }

  if (companyName) {
    return <InitialAvatar companyName={companyName} sizeClasses={sizeClasses} />;
  }

  return (
    <Building2 className={cn('shrink-0 text-muted-foreground', iconSize)} aria-hidden="true" />
  );
}

export { CompanyLogo };
