import type { JSX } from 'react';
import type { ToasterProps } from 'sonner';
import { Toaster as Sonner } from 'sonner';
import { useTheme } from '@/shared/lib/theme/theme.ts';

interface AppToasterProps {
  readonly position?: ToasterProps['position'] | undefined;
  readonly richColors?: boolean | undefined;
  readonly closeButton?: boolean | undefined;
}

function buildSonnerProps(appProps: AppToasterProps): Partial<ToasterProps> {
  const props: Partial<ToasterProps> = {};
  if (appProps.position !== undefined) {
    props.position = appProps.position;
  }
  if (appProps.richColors !== undefined) {
    props.richColors = appProps.richColors;
  }
  if (appProps.closeButton !== undefined) {
    props.closeButton = appProps.closeButton;
  }
  return props;
}

const Toaster = (appProps: AppToasterProps): JSX.Element => {
  const { theme = 'system' } = useTheme();
  const extraProps = buildSonnerProps(appProps);

  return (
    <Sonner
      theme={theme as 'light' | 'dark' | 'system'}
      className="toaster group"
      {...extraProps}
      style={
        {
          '--normal-bg': 'var(--popover)',
          '--normal-text': 'var(--popover-foreground)',
          '--normal-border': 'var(--border)',
        } as React.CSSProperties
      }
    />
  );
};

export { Toaster };
