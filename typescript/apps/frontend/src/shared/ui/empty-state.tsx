import { cn } from '@shared/lib/index.ts';
import type { LucideIcon } from 'lucide-react';
import type { JSX, ReactNode } from 'react';
import { Button } from './button.tsx';

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description?: string | undefined;
  action?:
    | {
        label: string;
        onClick: () => void;
        variant?: ('default' | 'outline' | 'secondary') | undefined;
      }
    | undefined;
  secondaryAction?:
    | {
        label: string;
        onClick: () => void;
      }
    | undefined;
  children?: ReactNode | undefined;
  className?: string | undefined;
  size?: 'sm' | 'md' | 'lg';
  variant?: 'default' | 'card' | 'inline';
}

const sizeClasses = {
  sm: {
    container: 'min-h-48 py-8',
    iconWrapper: 'size-12',
    icon: 'size-5',
    title: 'text-base font-semibold',
    description: 'text-sm max-w-sm',
    gap: 'gap-3',
  },
  md: {
    container: 'min-h-80 py-12',
    iconWrapper: 'size-16',
    icon: 'size-7',
    title: 'text-lg font-semibold',
    description: 'text-sm max-w-md',
    gap: 'gap-4',
  },
  lg: {
    container: 'min-h-96 py-16',
    iconWrapper: 'h-20 w-20',
    icon: 'size-9',
    title: 'text-xl font-semibold',
    description: 'text-base max-w-lg',
    gap: 'gap-5',
  },
};

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  secondaryAction,
  children,
  className,
  size = 'md',
  variant = 'default',
}: EmptyStateProps): JSX.Element {
  const classes = sizeClasses[size];

  const containerVariants = {
    default: '',
    card: 'rounded-xl border border-dashed border-border/60 bg-muted/20',
    inline: 'py-6',
  };

  return (
    <div
      className={cn(
        'flex items-center justify-center px-6',
        classes.container,
        containerVariants[variant],
        className,
      )}
    >
      <div className={cn('flex flex-col items-center text-center', classes.gap)}>
        <div
          className={cn(
            'flex items-center justify-center rounded-full bg-linear-to-br from-muted to-muted/60 ring-1 ring-border/40',
            classes.iconWrapper,
          )}
        >
          <Icon
            className={cn('text-muted-foreground/70', classes.icon)}
            strokeWidth={1.5}
            aria-hidden="true"
          />
        </div>

        <div className="space-y-1.5">
          <h3 className={cn('text-foreground', classes.title)}>{title}</h3>
          {description ? (
            <p className={cn('text-muted-foreground leading-relaxed', classes.description)}>
              {description}
            </p>
          ) : null}
        </div>

        {children}

        {action || secondaryAction ? (
          <div className="flex items-center gap-3 pt-2">
            {action ? (
              <Button
                onClick={action.onClick}
                variant={action.variant ?? 'default'}
                size={size === 'sm' ? 'sm' : 'default'}
              >
                {action.label}
              </Button>
            ) : null}
            {secondaryAction ? (
              <Button onClick={secondaryAction.onClick} variant="ghost" size="sm">
                {secondaryAction.label}
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
