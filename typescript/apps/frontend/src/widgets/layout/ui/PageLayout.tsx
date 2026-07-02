import { cn } from '@shared/lib/index.ts';
import type { JSX, ReactNode } from 'react';

/**
 * Thin page container that owns content width and base vertical padding.
 *
 * Every routed page should wrap its content in PageLayout. Width presets:
 * - `full` (default): `container mx-auto` for list/overview pages
 * - `narrow`: `container mx-auto max-w-3xl` for form/detail pages
 * - `medium`: `container mx-auto max-w-4xl` for mid-width pages (e.g. licenses)
 *
 * Vertical spacing between sections is NOT baked in. Pages add `space-y-6`
 * (or whatever they need) via the `className` prop, keeping this component
 * focused on a single concern: centering content at the correct width.
 *
 * One-off overrides (e.g. extra vertical padding for an empty state) also
 * go through `className`.
 */

type ContentWidth = 'full' | 'narrow' | 'medium';

const WIDTH_CLASSES: Record<ContentWidth, string> = {
  full: 'container mx-auto',
  narrow: 'container mx-auto max-w-3xl',
  medium: 'container mx-auto max-w-4xl',
};

interface PageLayoutProps {
  readonly children: ReactNode;
  readonly contentWidth?: ContentWidth;
  readonly className?: string;
}

export function PageLayout({
  children,
  contentWidth = 'full',
  className,
}: PageLayoutProps): JSX.Element {
  return <div className={cn(WIDTH_CLASSES[contentWidth], 'py-6', className)}>{children}</div>;
}
