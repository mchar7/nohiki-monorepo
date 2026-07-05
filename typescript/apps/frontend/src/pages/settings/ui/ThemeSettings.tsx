import { Check, Monitor, Moon, Sun } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { cn, THEME_COLORS, type ThemeColor, useTheme, useThemeColor } from '@/shared/lib/index.ts';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import { Label } from '@/shared/ui/label.tsx';

interface ThemeModeOption {
  readonly value: 'light' | 'dark' | 'system';
  readonly label: string;
  readonly icon: typeof Sun;
  readonly description: string;
}

interface ThemeModeButtonProps {
  readonly option: ThemeModeOption;
  readonly isSelected: boolean;
  readonly onSelect: (value: 'light' | 'dark' | 'system') => void;
}

function ThemeModeButton({ option, isSelected, onSelect }: ThemeModeButtonProps): JSX.Element {
  const Icon = option.icon;

  const handleClick = (): void => {
    onSelect(option.value);
  };

  return (
    <button
      key={option.value}
      type="button"
      onClick={handleClick}
      className={cn(
        'relative flex flex-col items-center gap-2 rounded-xl border-2 p-4 transition-all hover:bg-accent/50',
        isSelected ? 'border-primary bg-primary/5' : 'border-border/50 bg-card hover:border-border',
      )}
    >
      <div
        className={cn(
          'flex size-10 items-center justify-center rounded-lg transition-colors',
          isSelected ? 'bg-primary/10' : 'bg-muted',
        )}
      >
        <Icon className={cn('size-5', isSelected ? 'text-primary' : 'text-muted-foreground')} />
      </div>
      <div className="text-center">
        <p className={cn('font-medium text-sm', isSelected && 'text-primary')}>{option.label}</p>
        <p className="text-muted-foreground text-xs">{option.description}</p>
      </div>
      {isSelected ? (
        <div className="absolute top-2 right-2">
          <Check className="size-4 text-primary" />
        </div>
      ) : null}
    </button>
  );
}

interface ThemeColorButtonProps {
  readonly themeKey: ThemeColor;
  readonly colorConfig: (typeof THEME_COLORS)[ThemeColor];
  readonly isSelected: boolean;
  readonly disabled: boolean;
  readonly onSelect: (key: ThemeColor) => void;
}

function ThemeColorButton({
  themeKey,
  colorConfig,
  isSelected,
  disabled,
  onSelect,
}: ThemeColorButtonProps): JSX.Element {
  const { t } = useTranslation('settings');

  const handleClick = (): void => {
    onSelect(themeKey);
  };

  return (
    <button
      key={themeKey}
      type="button"
      onClick={handleClick}
      disabled={disabled}
      className={cn(
        'group relative flex flex-col items-center gap-2 rounded-xl border-2 p-3 transition-all',
        disabled ? 'cursor-not-allowed opacity-50' : 'hover:bg-accent/50',
        isSelected ? 'border-primary bg-primary/5' : 'border-border/50 bg-card hover:border-border',
      )}
    >
      <div
        className={cn(
          'size-8 rounded-full ring-2 ring-offset-2 ring-offset-background transition-transform',
          isSelected ? 'scale-110 ring-primary' : 'ring-transparent group-hover:scale-105',
        )}
        style={{ backgroundColor: colorConfig.previewColor }}
      />
      <span
        className={cn('font-medium text-xs', isSelected ? 'text-primary' : 'text-muted-foreground')}
      >
        {t(colorConfig.nameKey)}
      </span>
      {isSelected ? (
        <div className="absolute top-1.5 right-1.5">
          <Check className="size-3.5 text-primary" />
        </div>
      ) : null}
    </button>
  );
}

export function ThemeSettings(): JSX.Element {
  const { t } = useTranslation('settings');
  const { theme, setTheme } = useTheme();
  const { themeColor, setThemeColor, useSystemTheme, setUseSystemTheme } = useThemeColor();

  const modeOptions: ThemeModeOption[] = [
    {
      value: 'light',
      label: t('appearance.theme.light'),
      icon: Sun,
      description: t('appearance.modeDescription.light'),
    },
    {
      value: 'dark',
      label: t('appearance.theme.dark'),
      icon: Moon,
      description: t('appearance.modeDescription.dark'),
    },
    {
      value: 'system',
      label: t('appearance.theme.system'),
      icon: Monitor,
      description: t('appearance.modeDescription.system'),
    },
  ];

  const handleToggleSystemTheme = (): void => {
    setUseSystemTheme(!useSystemTheme);
  };

  return (
    <div className="space-y-6">
      {/* Appearance Mode */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('appearance.title')}</CardTitle>
          <CardDescription>{t('appearance.description')}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 gap-3">
            {modeOptions.map((option) => (
              <ThemeModeButton
                key={option.value}
                option={option}
                isSelected={theme === option.value}
                onSelect={setTheme}
              />
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Color Theme */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('appearance.accentColor.title')}</CardTitle>
          <CardDescription>{t('appearance.accentColor.description')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* System Theme Toggle */}
          <div className="flex items-center justify-between rounded-lg border bg-muted/30 p-3">
            <div className="flex items-center gap-3">
              <Monitor className="size-4 text-muted-foreground" />
              <div>
                <Label className="font-medium text-sm">
                  {t('appearance.accentColor.useSystem')}
                </Label>
                <p className="text-muted-foreground text-xs">
                  {t('appearance.accentColor.useSystemDescription')}
                </p>
              </div>
            </div>
            <Button
              variant={useSystemTheme ? 'default' : 'outline'}
              size="sm"
              onClick={handleToggleSystemTheme}
            >
              {useSystemTheme ? t('appearance.enabled') : t('appearance.disabled')}
            </Button>
          </div>

          {/* Color Options */}
          <div className="grid grid-cols-5 gap-3">
            {(
              Object.entries(THEME_COLORS) as [ThemeColor, (typeof THEME_COLORS)[ThemeColor]][]
            ).map(([key, colorConfig]) => (
              <ThemeColorButton
                key={key}
                themeKey={key}
                colorConfig={colorConfig}
                isSelected={!useSystemTheme && themeColor === key}
                disabled={useSystemTheme}
                onSelect={setThemeColor}
              />
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
