import { cn } from '@shared/lib/index.ts';
import { Loader2 } from 'lucide-react';
import type { JSX } from 'react';

interface LoadingSpinnerProps {
  readonly size?: 'sm' | 'md' | 'lg';
  readonly text?: string;
  readonly description?: string;
  readonly className?: string;
  readonly centered?: boolean;
  readonly variant?: 'default' | 'overlay' | 'inline';
}

const sizeClasses = {
  sm: {
    spinner: 'size-4',
    text: 'text-sm',
    description: 'text-xs',
    gap: 'gap-2',
    container: 'min-h-32',
  },
  md: {
    spinner: 'size-6',
    text: 'text-sm',
    description: 'text-xs',
    gap: 'gap-3',
    container: 'min-h-64',
  },
  lg: {
    spinner: 'size-8',
    text: 'text-base',
    description: 'text-sm',
    gap: 'gap-4',
    container: 'min-h-96',
  },
};

export function LoadingSpinner({
  size = 'md',
  text,
  description,
  className,
  centered = true,
  variant = 'default',
}: LoadingSpinnerProps): JSX.Element {
  const classes = sizeClasses[size];

  const content = (
    <div className={cn('flex flex-col items-center', classes.gap)}>
      <div className="relative">
        <div className="absolute inset-0 animate-ping opacity-20">
          <Loader2 className={cn('text-primary', classes.spinner)} aria-hidden="true" />
        </div>
        <Loader2 className={cn('animate-spin text-primary', classes.spinner)} aria-hidden="true" />
      </div>
      {text || description ? (
        <div className="flex flex-col items-center gap-1 text-center">
          {text ? (
            <span className={cn('font-medium text-foreground', classes.text)}>{text}</span>
          ) : null}
          {description ? (
            <span className={cn('text-muted-foreground', classes.description)}>{description}</span>
          ) : null}
        </div>
      ) : null}
    </div>
  );

  if (variant === 'inline') {
    return (
      <div className={cn('flex items-center gap-2', className)}>
        <Loader2
          className={cn('animate-spin text-muted-foreground', classes.spinner)}
          aria-hidden="true"
        />
        {text ? <span className={cn('text-muted-foreground', classes.text)}>{text}</span> : null}
      </div>
    );
  }

  if (variant === 'overlay') {
    return (
      <div
        className={cn(
          'absolute inset-0 flex items-center justify-center bg-background/80 backdrop-blur-sm',
          className,
        )}
      >
        {content}
      </div>
    );
  }

  if (centered) {
    return (
      <div className={cn('flex items-center justify-center', classes.container, className)}>
        {content}
      </div>
    );
  }

  return <div className={className}>{content}</div>;
}
