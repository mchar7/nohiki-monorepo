import type { CSSProperties, JSX, ReactNode } from 'react';
import { cn } from '@/shared/lib/utils/utils.ts';
import type { ChartConfig, ChartConfigItem } from './chart-context.tsx';
import { getPayloadConfigFromPayload, useChart } from './chart-context.tsx';

interface TooltipPayloadItem {
  readonly name?: string;
  readonly value?: number;
  readonly dataKey?: string | number;
  readonly color?: string;
  readonly payload?: Record<string, unknown>;
}

interface ChartTooltipContentProps {
  readonly active?: boolean;
  readonly payload?: readonly TooltipPayloadItem[];
  readonly label?: string;
  readonly className?: string;
  readonly indicator?: 'line' | 'dot' | 'dashed';
  readonly hideLabel?: boolean;
  readonly hideIndicator?: boolean;
  readonly labelClassName?: string;
  readonly labelFormatter?: (value: ReactNode, payload: readonly TooltipPayloadItem[]) => ReactNode;
  readonly color?: string;
  readonly nameKey?: string;
  readonly labelKey?: string;
}

function TooltipIndicator({
  indicator,
  indicatorColor,
  nestLabel,
}: {
  readonly indicator: 'line' | 'dot' | 'dashed';
  readonly indicatorColor: string | undefined;
  readonly nestLabel: boolean;
}): JSX.Element {
  return (
    <div
      className={cn('shrink-0 rounded-xs border-[--color-border] bg-[--color-bg]', {
        'h-2.5 w-2.5': indicator === 'dot',
        'w-1': indicator === 'line',
        'w-0 border-[1.5px] border-dashed bg-transparent': indicator === 'dashed',
        'my-0.5': nestLabel && indicator === 'dashed',
      })}
      style={
        {
          '--color-bg': indicatorColor,
          '--color-border': indicatorColor,
        } as CSSProperties
      }
    />
  );
}

function TooltipPayloadRow({
  item,
  indicator,
  hideIndicator,
  nestLabel,
  tooltipLabel,
  indicatorColor,
  itemConfig,
}: {
  readonly item: TooltipPayloadItem;
  readonly indicator: 'line' | 'dot' | 'dashed';
  readonly hideIndicator: boolean;
  readonly nestLabel: boolean;
  readonly tooltipLabel: ReactNode;
  readonly indicatorColor: string | undefined;
  readonly itemConfig: ChartConfigItem | undefined;
}): JSX.Element {
  return (
    <div
      key={String(item.dataKey)}
      className={cn(
        'flex w-full flex-wrap items-stretch gap-2 [&>svg]:h-2.5 [&>svg]:w-2.5 [&>svg]:text-muted-foreground',
        indicator === 'dot' && 'items-center',
      )}
    >
      {itemConfig?.icon ? (
        <itemConfig.icon />
      ) : (
        !hideIndicator && (
          <TooltipIndicator
            indicator={indicator}
            indicatorColor={indicatorColor}
            nestLabel={nestLabel}
          />
        )
      )}
      <div
        className={cn(
          'flex flex-1 justify-between leading-none',
          nestLabel ? 'items-end' : 'items-center',
        )}
      >
        <div className="grid gap-1.5">
          {nestLabel ? tooltipLabel : null}
          <span className="text-muted-foreground">{itemConfig?.label ?? item.name}</span>
        </div>
        {item.value !== undefined && (
          <span className="font-medium font-mono text-foreground tabular-nums">
            {item.value.toLocaleString()}
          </span>
        )}
      </div>
    </div>
  );
}

interface TooltipLabelOptions {
  readonly config: ChartConfig;
  readonly payload: readonly TooltipPayloadItem[] | undefined;
  readonly hideLabel: boolean;
  readonly label: string | undefined;
  readonly labelFormatter: ChartTooltipContentProps['labelFormatter'];
  readonly labelClassName: string | undefined;
  readonly labelKey: string | undefined;
}

function useTooltipLabel(options: TooltipLabelOptions): JSX.Element | null {
  const { config, payload, hideLabel, label, labelFormatter, labelClassName, labelKey } = options;

  if (hideLabel || !payload || payload.length === 0) {
    return null;
  }

  const [item] = payload;
  const key = `${labelKey ?? item?.dataKey ?? item?.name ?? 'value'}`;
  const itemConfig = getPayloadConfigFromPayload(config, item, key);
  const value =
    !labelKey && typeof label === 'string'
      ? (config[label as keyof typeof config]?.label ?? label)
      : itemConfig?.label;

  if (labelFormatter) {
    return (
      <div className={cn('font-medium', labelClassName)}>{labelFormatter(value, payload)}</div>
    );
  }

  if (!value) {
    return null;
  }

  return <div className={cn('font-medium', labelClassName)}>{value}</div>;
}

function ChartTooltipContent({
  active,
  payload,
  className,
  indicator = 'dot',
  hideLabel = false,
  hideIndicator = false,
  label,
  labelFormatter,
  labelClassName,
  color,
  nameKey,
  labelKey,
}: ChartTooltipContentProps): JSX.Element | null {
  const { config } = useChart();
  const tooltipLabel = useTooltipLabel({
    config,
    payload,
    hideLabel,
    label,
    labelFormatter,
    labelClassName,
    labelKey,
  });

  if (!(active && payload && payload.length > 0)) {
    return null;
  }

  const nestLabel = payload.length === 1 && indicator !== 'dot';

  return (
    <div
      className={cn(
        'grid min-w-32 items-start gap-1.5 rounded-lg border border-border/50 bg-background px-2.5 py-1.5 text-xs shadow-xl',
        className,
      )}
    >
      {/* biome-ignore lint/suspicious/noLeakedRender: tooltipLabel is JSX.Element | null, never a leakable primitive */}
      {nestLabel ? null : tooltipLabel}
      <div className="grid gap-1.5">
        {payload.map((item) => {
          const key = `${nameKey ?? item.name ?? item.dataKey ?? 'value'}`;
          const itemConfig = getPayloadConfigFromPayload(config, item, key);
          const indicatorColor = color ?? (item.payload?.fill as string) ?? item.color;

          return (
            <TooltipPayloadRow
              key={String(item.dataKey)}
              item={item}
              indicator={indicator}
              hideIndicator={hideIndicator}
              nestLabel={nestLabel}
              tooltipLabel={tooltipLabel}
              indicatorColor={indicatorColor}
              itemConfig={itemConfig}
            />
          );
        })}
      </div>
    </div>
  );
}

export { ChartTooltipContent };
