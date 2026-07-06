import { cn } from '@shared/lib/index.ts';
import type { LucideIcon } from 'lucide-react';
import type { JSX } from 'react';

/**
 * Variant determines the visual treatment of the icon.
 * - `primary`: Uses the theme's primary/accent color (for emphasis, active states)
 * - `muted`: Uses muted foreground color (for secondary, informational sections)
 * - `subtle`: Uses a very subtle background with muted icon (for less prominent sections)
 */
type IconVariant = 'primary' | 'muted' | 'subtle';

/**
 * Size determines the icon and container dimensions.
 * - `sm`: 16px icon in 28px container (for compact card headers)
 * - `md`: 20px icon in 36px container (for standard card headers, default)
 * - `lg`: 24px icon in 44px container (for feature banners, hero sections)
 */
type IconSize = 'sm' | 'md' | 'lg';

interface SectionIconProps {
  /** The Lucide icon component to render */
  readonly icon: LucideIcon;
  /** Visual variant - controls color treatment */
  readonly variant?: IconVariant;
  /** Size variant */
  readonly size?: IconSize;
  /** Additional CSS classes for the container */
  readonly className?: string;
  /** Whether to show just the icon without the container background */
  readonly bare?: boolean;
}

const sizeConfig = {
  sm: {
    container: 'size-7 rounded-md',
    icon: 'size-4',
  },
  md: {
    container: 'size-9 rounded-lg',
    icon: 'size-5',
  },
  lg: {
    container: 'h-11 w-11 rounded-lg',
    icon: 'size-6',
  },
} as const;

const variantConfig = {
  primary: {
    container: 'bg-primary/10',
    icon: 'text-primary',
  },
  muted: {
    container: 'bg-muted',
    icon: 'text-muted-foreground',
  },
  subtle: {
    container: 'bg-muted/50',
    icon: 'text-muted-foreground/70',
  },
} as const;

/**
 * SectionIcon provides consistent icon styling for section headers throughout the app.
 *
 * Use `variant="primary"` for:
 * - Main feature sections that should draw attention
 * - Active/selected states
 * - Primary action areas
 *
 * Use `variant="muted"` for:
 * - Secondary or informational sections
 * - Empty states
 * - Disabled or coming-soon features
 *
 * Use `variant="subtle"` for:
 * - Tertiary content
 * - Dense UIs where less visual weight is needed
 *
 * @example
 * // Primary section with emphasis
 * <CardTitle className="flex items-center gap-2">
 *   <SectionIcon icon={FileText} variant="primary" />
 *   Recent Documents
 * </CardTitle>
 *
 * @example
 * // Muted empty state
 * <SectionIcon icon={Inbox} variant="muted" size="lg" />
 */
export function SectionIcon({
  icon: Icon,
  variant = 'primary',
  size = 'md',
  className,
  bare = false,
}: SectionIconProps): JSX.Element {
  const sizeClasses = sizeConfig[size];
  const variantClasses = variantConfig[variant];

  if (bare) {
    return <Icon className={cn(sizeClasses.icon, variantClasses.icon, className)} />;
  }

  return (
    <div
      className={cn(
        'flex shrink-0 items-center justify-center',
        sizeClasses.container,
        variantClasses.container,
        className,
      )}
    >
      <Icon className={cn(sizeClasses.icon, variantClasses.icon)} />
    </div>
  );
}

/**
 * Inline icon for use directly in text without a container background.
 * Provides consistent sizing and color treatment for icons used inline with text.
 */
export function InlineIcon({
  icon: Icon,
  variant = 'muted',
  size = 'sm',
  className,
}: Omit<SectionIconProps, 'bare'>): JSX.Element {
  const sizeClasses = sizeConfig[size];
  const variantClasses = variantConfig[variant];

  return <Icon className={cn(sizeClasses.icon, variantClasses.icon, className)} />;
}
