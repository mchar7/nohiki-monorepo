import type { JSX } from 'react';
import { cn } from '@/shared/lib/utils/utils.ts';
import { getPayloadConfigFromPayload, useChart } from './chart-context.tsx';

interface LegendPayloadItem {
  readonly value?: string;
  readonly dataKey?: string | number;
  readonly color?: string;
}

interface ChartLegendContentProps extends React.ComponentProps<'div'> {
  readonly hideIcon?: boolean;
  readonly payload?: readonly LegendPayloadItem[];
  readonly verticalAlign?: 'top' | 'bottom';
  readonly nameKey?: string;
}

function ChartLegendContent({
  className,
  hideIcon = false,
  payload,
  verticalAlign = 'bottom',
  nameKey,
}: ChartLegendContentProps): JSX.Element | null {
  const { config } = useChart();

  if (!payload || payload.length === 0) {
    return null;
  }

  return (
    <div
      className={cn(
        'flex items-center justify-center gap-4',
        verticalAlign === 'top' ? 'pb-3' : 'pt-3',
        className,
      )}
    >
      {payload.map((item) => {
        const key = `${nameKey ?? item.dataKey ?? 'value'}`;
        const itemConfig = getPayloadConfigFromPayload(config, item, key);

        return (
          <div
            key={item.value}
            className={cn(
              'flex items-center gap-1.5 [&>svg]:h-3 [&>svg]:w-3 [&>svg]:text-muted-foreground',
            )}
          >
            {itemConfig?.icon && !hideIcon ? (
              <itemConfig.icon />
            ) : (
              <div
                className="h-2 w-2 shrink-0 rounded-xs"
                style={{
                  backgroundColor: item.color,
                }}
              />
            )}
            {itemConfig?.label}
          </div>
        );
      })}
    </div>
  );
}

export type { ChartLegendContentProps, LegendPayloadItem };
export { ChartLegendContent };
