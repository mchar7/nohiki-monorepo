import type { JSX, ReactNode } from 'react';
import { useId } from 'react';
import { Legend, ResponsiveContainer, Tooltip } from 'recharts';

import { cn } from '@/shared/lib/utils/utils.ts';
import type { ChartConfig } from './chart-context.tsx';
import { ChartContext } from './chart-context.tsx';

const THEMES = { light: '', dark: '.dark' } as const;

interface ChartContainerProps extends Omit<React.ComponentProps<'div'>, 'children'> {
  readonly config: ChartConfig;
  readonly children: ReactNode;
}

function ChartContainer({
  id,
  className,
  children,
  config,
  ...props
}: ChartContainerProps): JSX.Element {
  const uniqueId = useId();
  const chartId = `chart-${id ?? uniqueId.replaceAll(':', '')}`;

  return (
    <ChartContext.Provider value={{ config }}>
      <div
        data-chart={chartId}
        className={cn(
          "flex aspect-video justify-center text-xs [&_.recharts-cartesian-axis-tick_text]:fill-muted-foreground [&_.recharts-cartesian-grid_line[stroke='#ccc']]:stroke-border/50 [&_.recharts-curve.recharts-tooltip-cursor]:stroke-border [&_.recharts-dot[stroke='#fff']]:stroke-transparent [&_.recharts-layer]:outline-none [&_.recharts-polar-grid_[stroke='#ccc']]:stroke-border [&_.recharts-radial-bar-background-sector]:fill-muted [&_.recharts-rectangle.recharts-tooltip-cursor]:fill-muted [&_.recharts-reference-line_[stroke='#ccc']]:stroke-border [&_.recharts-sector[stroke='#fff']]:stroke-transparent [&_.recharts-sector]:outline-none [&_.recharts-surface]:outline-none",
          className,
        )}
        {...props}
      >
        <ChartStyle id={chartId} config={config} />
        <ResponsiveContainer minWidth={0}>{children}</ResponsiveContainer>
      </div>
    </ChartContext.Provider>
  );
}

interface ChartStyleProps {
  readonly id: string;
  readonly config: ChartConfig;
}

function ChartStyle({ id, config }: ChartStyleProps): JSX.Element | null {
  const colorConfig = Object.entries(config).filter(([, cfg]) => cfg.color ?? cfg.theme);

  if (colorConfig.length === 0) {
    return null;
  }

  return (
    <style
      // biome-ignore lint/security/noDangerouslySetInnerHtml: Chart CSS variables are generated from config, not user input
      dangerouslySetInnerHTML={{
        __html: Object.entries(THEMES)
          .map(
            ([theme, prefix]) => `
${prefix} [data-chart=${id}] {
${colorConfig
  .map(([key, itemConfig]) => {
    const color = itemConfig.theme?.[theme as keyof typeof THEMES] ?? itemConfig.color;
    return color ? `  --color-${key}: ${color};` : null;
  })
  .filter(Boolean)
  .join('\n')}
}
`,
          )
          .join('\n'),
      }}
    />
  );
}

const ChartTooltip: typeof Tooltip = Tooltip;
export const ChartLegend: typeof Legend = Legend;

export type { ChartConfig } from './chart-context.tsx';
export { ChartTooltipContent } from './chart-tooltip.tsx';
export { ChartContainer, ChartTooltip };
