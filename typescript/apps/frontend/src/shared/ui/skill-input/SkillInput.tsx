import { X } from 'lucide-react';
import type { JSX } from 'react';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { SkillSearchResponse } from '@/shared/api/index.ts';
import { $api, CACHE_CONFIG } from '@/shared/api/index.ts';

import { Badge } from '../badge.tsx';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '../command.tsx';
import { Popover, PopoverContent, PopoverTrigger } from '../popover.tsx';
import type { SkillInputProps } from './SkillInput.types.ts';

interface SkillBadgeProps {
  readonly skill: SkillSearchResponse['skills'][number];
  readonly disabled: boolean;
  readonly onRemove: (skillId: string) => void;
  readonly onOpen: () => void;
}

function SkillBadge({ skill, disabled, onRemove, onOpen }: SkillBadgeProps): JSX.Element {
  const { t } = useTranslation('common');
  const label = skill.display_name || skill.name;

  return (
    <Badge
      variant="secondary"
      className="h-7 max-w-full gap-1 rounded-md border border-border/70 px-2 font-medium"
    >
      <button
        type="button"
        className="max-w-48 truncate outline-none focus-visible:underline"
        title={label}
        onClick={onOpen}
        disabled={disabled}
      >
        {label}
      </button>
      <button
        type="button"
        className="-mr-1 inline-flex size-5 shrink-0 items-center justify-center rounded-sm text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
        onClick={() => onRemove(skill.id)}
        disabled={disabled}
        aria-label={`${t('actions.delete')} ${label}`}
      >
        <X className="size-3" aria-hidden="true" />
      </button>
    </Badge>
  );
}

interface SkillCommandItemProps {
  readonly skill: SkillSearchResponse['skills'][number];
  readonly query: string;
  readonly onSelect: (skill: SkillSearchResponse['skills'][number]) => void;
}

function SkillCommandItem({ skill, query, onSelect }: SkillCommandItemProps): JSX.Element {
  const label = skill.display_name || skill.name;
  const matchStart = label.toLocaleLowerCase().indexOf(query.toLocaleLowerCase());
  const matchEnd = matchStart + query.length;

  return (
    <CommandItem
      value={skill.id}
      onSelect={() => onSelect(skill)}
      className="min-w-0 items-start px-3 py-2.5"
    >
      <div className="min-w-0 flex-1 space-y-0.5">
        <div className="truncate font-medium leading-5" title={label}>
          {matchStart >= 0 ? (
            <>
              {label.slice(0, matchStart)}
              <mark className="rounded-sm bg-primary/15 text-foreground">
                {label.slice(matchStart, matchEnd)}
              </mark>
              {label.slice(matchEnd)}
            </>
          ) : (
            label
          )}
        </div>
        {skill.description ? (
          <p className="line-clamp-1 text-muted-foreground text-xs leading-4 sm:line-clamp-2">
            {skill.description}
          </p>
        ) : null}
        {skill.category ? (
          <p
            className="truncate text-[11px] text-muted-foreground/80 leading-4"
            title={skill.category}
          >
            {skill.category}
          </p>
        ) : null}
      </div>
    </CommandItem>
  );
}

function useSkillSearch(searchQuery: string): {
  searchResults: SkillSearchResponse | undefined;
  isLoading: boolean;
  isError: boolean;
  retry: () => void;
} {
  const {
    data: searchResults,
    isLoading,
    isError,
    refetch,
  } = $api.useQuery(
    'get',
    '/api/v1/skills/search',
    { params: { query: { q: searchQuery, limit: 10 } } },
    {
      enabled: searchQuery.length >= 2,
      staleTime: CACHE_CONFIG.STATIC.staleTime,
      gcTime: CACHE_CONFIG.STATIC.gcTime,
      retry: false,
    },
  );

  return { searchResults, isLoading, isError, retry: () => void refetch() };
}

function SkillSuggestionList({
  isLoading,
  isError,
  searchQuery,
  availableSkills,
  onRetry,
  onSelect,
}: {
  readonly isLoading: boolean;
  readonly isError: boolean;
  readonly searchQuery: string;
  readonly availableSkills: SkillSearchResponse['skills'];
  readonly onRetry: () => void;
  readonly onSelect: (skill: SkillSearchResponse['skills'][number]) => void;
}): JSX.Element {
  const { t } = useTranslation('common');

  return (
    <CommandList className="max-h-60 sm:max-h-72" aria-busy={isLoading}>
      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {isLoading
          ? t('states.loading')
          : t('skills.resultCount', { count: availableSkills.length })}
      </div>
      {isLoading && searchQuery.length >= 2 ? (
        <output className="block px-3 py-5 text-center text-muted-foreground text-sm">
          {t('states.loading')}
        </output>
      ) : null}
      {isError && searchQuery.length >= 2 && !isLoading ? (
        <div className="flex items-center justify-between gap-3 px-3 py-4 text-sm" role="alert">
          <span className="text-muted-foreground">{t('skills.searchError')}</span>
          <button
            type="button"
            className="shrink-0 rounded-sm font-medium text-primary underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
            onClick={onRetry}
          >
            {t('actions.retry')}
          </button>
        </div>
      ) : null}
      {!isLoading && !isError && searchQuery.length >= 2 && availableSkills.length === 0 ? (
        <CommandEmpty>{t('skills.noResults')}</CommandEmpty>
      ) : null}
      {searchQuery.length < 2 ? (
        <div className="px-3 py-5 text-center text-muted-foreground text-sm">
          {t('skills.typeToSearch')}
        </div>
      ) : null}
      {!isLoading && !isError && availableSkills.length > 0 ? (
        <CommandGroup>
          {availableSkills.slice(0, 8).map((skill) => (
            <SkillCommandItem
              key={skill.id}
              skill={skill}
              query={searchQuery}
              onSelect={onSelect}
            />
          ))}
        </CommandGroup>
      ) : null}
    </CommandList>
  );
}

function SkillInput({
  value,
  onChange,
  placeholder,
  maxSkills = 20,
  disabled = false,
}: Readonly<SkillInputProps>): JSX.Element {
  const { t } = useTranslation('common');
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const triggerRef = useRef<HTMLButtonElement>(null);

  const { searchResults, isLoading, isError, retry } = useSkillSearch(searchQuery);

  const selectedIds = new Set(value.map((s) => s.id));

  const handleSelect = (skill: SkillSearchResponse['skills'][number]): void => {
    if (selectedIds.has(skill.id) || value.length >= maxSkills) {
      return;
    }
    onChange([...value, skill]);
    setSearchQuery('');
    setOpen(false);
  };

  const handleRemove = (skillId: string): void => {
    onChange(value.filter((s) => s.id !== skillId));
    triggerRef.current?.focus();
  };

  const availableSkills = searchResults?.skills.filter((s) => !selectedIds.has(s.id)) ?? [];

  return (
    <div className="space-y-2">
      <Popover open={open} onOpenChange={setOpen}>
        <div
          className="flex min-h-10 w-full flex-wrap gap-1 rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2 data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50"
          data-disabled={disabled === true ? true : undefined}
        >
          {value.map((skill) => (
            <SkillBadge
              key={skill.id}
              skill={skill}
              disabled={disabled}
              onRemove={handleRemove}
              onOpen={() => setOpen(true)}
            />
          ))}
          <PopoverTrigger asChild={true}>
            <button
              ref={triggerRef}
              type="button"
              className="min-w-24 flex-1 cursor-text self-stretch text-left outline-none disabled:cursor-not-allowed"
              disabled={disabled}
              aria-label={
                placeholder !== undefined && placeholder.length > 0
                  ? placeholder
                  : t('skills.placeholder')
              }
            >
              {value.length === 0 ? (
                <span className="text-muted-foreground">
                  {placeholder !== undefined && placeholder.length > 0
                    ? placeholder
                    : t('skills.placeholder')}
                </span>
              ) : null}
            </button>
          </PopoverTrigger>
        </div>
        <PopoverContent
          className="w-[var(--radix-popover-trigger-width)] max-w-[calc(100vw-1rem)] p-0"
          align="start"
          collisionPadding={8}
        >
          <Command shouldFilter={false}>
            <CommandInput
              placeholder={t('skills.searchPlaceholder')}
              value={searchQuery}
              onValueChange={setSearchQuery}
            />
            <SkillSuggestionList
              isLoading={isLoading}
              isError={isError}
              searchQuery={searchQuery}
              availableSkills={availableSkills}
              onRetry={retry}
              onSelect={handleSelect}
            />
          </Command>
        </PopoverContent>
      </Popover>
      {value.length >= maxSkills && (
        <p className="text-muted-foreground text-xs">
          {t('skills.maxReached', { max: maxSkills })}
        </p>
      )}
    </div>
  );
}

export { SkillInput };
