import type { JSX, ReactNode } from 'react';
import { isFeatureEnabled } from '@/shared/config';
import { AuthListingsCanvas } from './AuthListingsCanvas.tsx';

interface AuthLayoutProps {
  readonly children: ReactNode;
}

/**
 * Shared layout for auth pages (login, register).
 * Renders the decorative listing canvas background with a radial vignette overlay
 * and centers the auth form above both layers.
 */
export function AuthLayout({ children }: AuthLayoutProps): JSX.Element {
  return (
    <div className="relative min-h-svh bg-gradient-to-b from-background via-background/95 to-muted/30">
      {isFeatureEnabled('authListings') && <AuthListingsCanvas />}
      {/* Radial vignette: darkens edges to focus attention on the centered auth form */}
      <div
        aria-hidden="true"
        className="pointer-events-none fixed inset-0 z-[1]"
        style={{
          background:
            'radial-gradient(ellipse 60% 50% at 50% 50%, transparent 0%, var(--background) 100%)',
        }}
      />
      <div className="relative z-10 flex min-h-svh flex-col items-center justify-center px-3 py-4 sm:px-6 sm:py-8 md:p-10">
        {children}
      </div>
    </div>
  );
}
