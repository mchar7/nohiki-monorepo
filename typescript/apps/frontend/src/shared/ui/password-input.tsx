import { Eye, EyeOff } from 'lucide-react';
import type { JSX } from 'react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/shared/lib/utils/utils.ts';
import { Button } from './button.tsx';
import { Input } from './input.tsx';
import type { PasswordInputProps } from './password-input.types.ts';

function PasswordInput({ className, value, ref, ...props }: PasswordInputProps): JSX.Element {
  const { t } = useTranslation('common');
  const [showPassword, setShowPassword] = useState(false);
  const hasContent = typeof value === 'string' && value.length > 0;

  const handleClick = (): void => setShowPassword((visible) => !visible);

  return (
    <div className="relative">
      <Input
        type={showPassword ? 'text' : 'password'}
        className={cn('pr-10', className)}
        ref={ref}
        value={value}
        {...props}
      />
      {hasContent ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="absolute top-0 right-0 h-full px-3 py-2 hover:bg-transparent"
          onClick={handleClick}
          aria-label={t(showPassword ? 'a11y.hidePassword' : 'a11y.showPassword')}
          aria-pressed={showPassword}
        >
          {showPassword ? (
            <EyeOff className="size-4 text-muted-foreground" aria-hidden="true" />
          ) : (
            <Eye className="size-4 text-muted-foreground" aria-hidden="true" />
          )}
        </Button>
      ) : null}
    </div>
  );
}

export { PasswordInput };
