import { Content, Portal, Root, Trigger } from '@radix-ui/react-popover';
import { cn } from '@shared/lib/index.ts';
import { X } from 'lucide-react';
import { type ElementType, type JSX, useRef, useState } from 'react';
import { useClickOutside, useEscapeClose, useScrollClose } from './fab-hooks.tsx';
import type {
  FABSize,
  FloatingAction,
  FloatingActionButtonProps,
} from './floating-action-button.types.ts';

/** Animation stagger delay per action item (ms) */
const ACTION_STAGGER_DELAY_MS: number = 40;
/** Duration after which FAB animation state resets to idle (ms) */
const ANIM_IDLE_RESET_MS: number = 300;

interface ActionItemProps {
  readonly action: FloatingAction;
  readonly open: boolean;
  readonly index: number;
  readonly onActionClick: (action: FloatingAction) => void;
}

function ActionItem({ action, open, index, onActionClick }: ActionItemProps): JSX.Element {
  const Icon = action.icon;

  const handleClick = (): void => {
    onActionClick(action);
  };

  return (
    <button
      key={action.id}
      type="button"
      onClick={handleClick}
      disabled={action.disabled || action.loading}
      style={{
        animationDelay: open ? `${index * ACTION_STAGGER_DELAY_MS}ms` : '0ms',
      }}
      className={cn(
        'flex items-center gap-3 rounded-md px-3 py-2.5 font-medium text-sm',
        'opacity-0',
        open && 'animate-fab-action-in',
        'transition-colors duration-100',
        action.disabled || action.loading
          ? 'cursor-not-allowed text-muted-foreground/50'
          : cn(
              'hover:bg-accent focus-visible:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              action.emphasis ? 'text-primary' : 'text-foreground',
            ),
      )}
    >
      {action.loading ? (
        <span className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
      ) : (
        <Icon className="size-4 shrink-0" />
      )}
      <span>{action.label}</span>
    </button>
  );
}

const sizeClasses: Record<FABSize, { button: string; icon: string }> = {
  sm: { button: 'size-12', icon: 'size-5' },
  md: { button: 'h-14 w-14', icon: 'size-6' },
  lg: { button: 'size-16', icon: 'size-7' },
};

const positionClasses: Record<string, string> = {
  'bottom-right': 'right-4 bottom-4 sm:right-6 sm:bottom-6',
  'bottom-left': 'left-4 bottom-4 sm:left-6 sm:bottom-6',
};

/** CSS keyframe animations for FAB open/close/action transitions - disabled for users who prefer reduced motion */
const FAB_STYLES = `
  @media (prefers-reduced-motion: no-preference) {
    @keyframes fab-pop { 0% { transform: scale(1); } 50% { transform: scale(1.08); } 100% { transform: scale(1); } }
    @keyframes fab-menu-open { 0% { opacity: 0; transform: translateY(8px); } 100% { opacity: 1; transform: translateY(0); } }
    @keyframes fab-menu-close { 0% { opacity: 1; transform: translateY(0); } 100% { opacity: 0; transform: translateY(8px); } }
    @keyframes fab-action-in { 0% { opacity: 0; transform: translateX(8px); } 100% { opacity: 1; transform: translateX(0); } }
    .animate-fab-open, .animate-fab-close { animation: fab-pop 0.2s ease-out; }
    .animate-fab-menu-open { animation: fab-menu-open 0.15s ease-out forwards; }
    .animate-fab-menu-close { animation: fab-menu-close 0.1s ease-out forwards; }
    .animate-fab-action-in { animation: fab-action-in 0.15s ease-out forwards; }
  }
  @media (prefers-reduced-motion: reduce) {
    .animate-fab-open, .animate-fab-close,
    .animate-fab-menu-open, .animate-fab-menu-close,
    .animate-fab-action-in { animation: none; opacity: 1; }
  }
`;

function FABTriggerButton({
  open,
  animState,
  buttonSize,
  iconSize,
  triggerLabel,
  triggerIcon: TriggerIcon,
}: {
  readonly open: boolean;
  readonly animState: 'idle' | 'opening' | 'closing';
  readonly buttonSize: string;
  readonly iconSize: string;
  readonly triggerLabel: string;
  readonly triggerIcon: ElementType;
}): JSX.Element {
  return (
    <button
      type="button"
      className={cn(
        'group relative flex items-center justify-center rounded-full shadow-lg',
        'bg-primary text-primary-foreground',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
        'transition-transform duration-200 ease-out',
        'hover:scale-105 hover:shadow-xl',
        'active:scale-95',
        buttonSize,
        animState === 'opening' && 'animate-fab-open',
        animState === 'closing' && 'animate-fab-close',
      )}
      aria-label={triggerLabel}
    >
      <span
        className={cn(
          'transition-all duration-200 ease-out',
          open ? 'rotate-180 scale-90' : 'rotate-0 scale-100',
        )}
      >
        {open ? (
          <X className={iconSize} />
        ) : (
          <TriggerIcon className={cn(iconSize, 'transition-transform group-hover:scale-110')} />
        )}
      </span>
    </button>
  );
}

function FABMenuContent({
  actions,
  open,
  position,
  onActionClick,
}: {
  readonly actions: FloatingAction[];
  readonly open: boolean;
  readonly position: 'bottom-right' | 'bottom-left';
  readonly onActionClick: (action: FloatingAction) => void;
}): JSX.Element {
  const handleInteractOutside = (e: Event): void => {
    e.preventDefault();
  };

  return (
    <Portal>
      <Content
        side="top"
        align={position === 'bottom-right' ? 'end' : 'start'}
        sideOffset={12}
        onInteractOutside={handleInteractOutside}
        className={cn(
          'z-50 min-w-[180px] origin-bottom rounded-lg border bg-popover p-1.5 shadow-lg',
          'data-[state=closed]:animate-fab-menu-close data-[state=open]:animate-fab-menu-open',
        )}
      >
        <div className="flex flex-col">
          {actions.map((action, index) => (
            <ActionItem
              key={action.id}
              action={action}
              open={open}
              index={index}
              onActionClick={onActionClick}
            />
          ))}
        </div>
      </Content>
    </Portal>
  );
}

/**
 * A reusable Floating Action Button (FAB) with fluid animations and multi-action support.
 */
function FloatingActionButton({
  actions,
  triggerIcon,
  triggerLabel,
  className,
  closeOnScroll = true,
  position = 'bottom-right',
  size = 'md',
}: Readonly<FloatingActionButtonProps>): JSX.Element {
  const [open, setOpen] = useState(false);
  const [animState, setAnimState] = useState<'idle' | 'opening' | 'closing'>('idle');
  const containerRef = useRef<HTMLDivElement>(null);

  const handleOpenChange = (newOpen: boolean): void => {
    setAnimState(newOpen ? 'opening' : 'closing');
    setOpen(newOpen);
    setTimeout((): void => setAnimState('idle'), ANIM_IDLE_RESET_MS);
  };

  const handleClose = (): void => handleOpenChange(false);

  useScrollClose(open, closeOnScroll, handleClose);
  useClickOutside(open, containerRef, handleClose);
  useEscapeClose(open, handleClose);

  const handleActionClick = (action: FloatingAction): void => {
    if (action.disabled || action.loading) {
      return;
    }
    action.onClick();
    handleOpenChange(false);
  };

  const { button: buttonSize, icon: iconSize } = sizeClasses[size];

  return (
    <div ref={containerRef} className={cn('fixed z-50', positionClasses[position], className)}>
      <Root open={open} onOpenChange={handleOpenChange}>
        <Trigger asChild={true}>
          <FABTriggerButton
            open={open}
            animState={animState}
            buttonSize={buttonSize}
            iconSize={iconSize}
            triggerLabel={triggerLabel}
            triggerIcon={triggerIcon}
          />
        </Trigger>
        <FABMenuContent
          actions={actions}
          open={open}
          position={position}
          onActionClick={handleActionClick}
        />
      </Root>
      <style>{FAB_STYLES}</style>
    </div>
  );
}

export { FloatingActionButton };
