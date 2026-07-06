import { X } from 'lucide-react';
import type React from 'react';
import type { JSX } from 'react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/shared/lib/utils/utils.ts';
import { Badge } from '@/shared/ui/badge.tsx';
import { Input } from '@/shared/ui/input.tsx';

interface TagInputProps {
  readonly value: readonly string[];
  readonly onChange: (tags: string[]) => void;
  readonly placeholder?: string;
  readonly maxTags?: number;
  readonly disabled?: boolean;
  readonly className?: string;
  readonly id?: string;
  readonly 'aria-invalid'?: boolean;
}

const DUPLICATE_MESSAGE_MS: number = 2000;

export function TagInput({
  value,
  onChange,
  placeholder,
  maxTags = 20,
  disabled = false,
  className,
  id,
  'aria-invalid': ariaInvalid,
}: TagInputProps): JSX.Element {
  const { t } = useTranslation('common');
  const [inputValue, setInputValue] = useState('');
  const [focusedTagIndex, setFocusedTagIndex] = useState(-1);
  const [duplicateMessage, setDuplicateMessage] = useState<string | null>(null);
  const [shaking, setShaking] = useState(false);
  const tagRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const duplicateTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    (): (() => void) => (): void => {
      if (duplicateTimerRef.current) {
        clearTimeout(duplicateTimerRef.current);
      }
    },
    [],
  );

  const showDuplicateWarning = (tag: string): void => {
    setDuplicateMessage(t('tagInput.duplicate', { tag }));
    setShaking(true);
    if (duplicateTimerRef.current) {
      clearTimeout(duplicateTimerRef.current);
    }
    duplicateTimerRef.current = setTimeout(() => {
      setDuplicateMessage(null);
      duplicateTimerRef.current = null;
    }, DUPLICATE_MESSAGE_MS);
  };

  const addTag = (tag: string): void => {
    const trimmedTag = tag.trim().toLowerCase();
    if (!trimmedTag) {
      return;
    }
    if (value.includes(trimmedTag)) {
      showDuplicateWarning(trimmedTag);
      return;
    }
    if (value.length >= maxTags) {
      return;
    }

    onChange([...value, trimmedTag]);
    setInputValue('');
    setDuplicateMessage(null);
  };

  const removeTag = (tagToRemove: string): void => {
    onChange(value.filter((tag) => tag !== tagToRemove));
    setFocusedTagIndex(-1);
  };

  const handleTagKeyDown = (e: React.KeyboardEvent, index: number): void => {
    if (e.key === 'ArrowRight' && index < value.length - 1) {
      e.preventDefault();
      setFocusedTagIndex(index + 1);
      tagRefs.current[index + 1]?.focus();
    } else if (e.key === 'ArrowLeft' && index > 0) {
      e.preventDefault();
      setFocusedTagIndex(index - 1);
      tagRefs.current[index - 1]?.focus();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>): void => {
    if (e.key === 'Enter') {
      e.preventDefault();
      addTag(inputValue);
    } else if (e.key === 'Backspace' && !inputValue && value.length > 0) {
      removeTag(value.at(-1) ?? '');
    } else if (e.key === 'ArrowLeft' && !inputValue && value.length > 0) {
      e.preventDefault();
      const lastIndex = value.length - 1;
      setFocusedTagIndex(lastIndex);
      tagRefs.current[lastIndex]?.focus();
    }
  };

  const handleBlur = (): void => {
    if (inputValue.trim()) {
      addTag(inputValue);
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
    setInputValue(e.target.value);
    setDuplicateMessage(null);
  };

  return (
    <div className={cn('space-y-2', className)}>
      <ul className="flex min-h-9 list-none flex-wrap gap-1.5 p-0" aria-label={t('a11y.tags')}>
        {value.map((tag, index) => (
          <li key={tag}>
            <Badge variant="secondary" className="gap-1 py-0.5 pr-1 pl-2 font-normal text-xs">
              {tag}
              <button
                ref={(el: HTMLButtonElement | null) => {
                  tagRefs.current[index] = el;
                }}
                type="button"
                onClick={() => removeTag(tag)}
                onKeyDown={(e: React.KeyboardEvent) => handleTagKeyDown(e, index)}
                disabled={disabled}
                tabIndex={focusedTagIndex === index ? 0 : -1}
                className="ml-0.5 min-h-11 min-w-11 rounded-full p-2 hover:bg-muted-foreground/20 focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed"
                aria-label={`${t('actions.delete')} ${tag}`}
              >
                <X className="size-3" />
              </button>
            </Badge>
          </li>
        ))}
      </ul>
      <Input
        id={id}
        type="text"
        value={inputValue}
        onChange={handleInputChange}
        onKeyDown={handleKeyDown}
        onBlur={handleBlur}
        placeholder={value.length >= maxTags ? t('counts.more', { count: 0 }) : placeholder}
        disabled={disabled || value.length >= maxTags}
        aria-invalid={ariaInvalid}
        className={cn('h-9', shaking && 'animate-shake')}
        onAnimationEnd={() => setShaking(false)}
      />
      {duplicateMessage ? (
        <p className="text-amber-600 text-xs dark:text-amber-500" aria-live="assertive">
          {duplicateMessage}
        </p>
      ) : null}
    </div>
  );
}
