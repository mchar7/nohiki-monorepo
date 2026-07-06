import type { ComponentType, Context, ReactNode } from 'react';
import { createContext, useContext } from 'react';

type ChartConfig = Record<
  string,
  {
    label?: ReactNode;
    icon?: ComponentType;
  } & (
    | { color?: string; theme?: never }
    | { color?: never; theme: Record<'light' | 'dark', string> }
  )
>;

type ChartConfigItem = ChartConfig[string];

interface ChartContextProps {
  config: ChartConfig;
}

const ChartContext: Context<ChartContextProps | null> = createContext<ChartContextProps | null>(
  null,
);

function useChart(): ChartContextProps {
  const context = useContext(ChartContext);

  if (!context) {
    throw new Error('useChart must be used within a <ChartContainer />');
  }

  return context;
}

function getPayloadConfigFromPayload(
  config: ChartConfig,
  payload: unknown,
  key: string,
): ChartConfigItem | undefined {
  if (typeof payload !== 'object' || payload === null) {
    return;
  }

  const payloadPayload =
    'payload' in payload && typeof payload.payload === 'object' && payload.payload !== null
      ? payload.payload
      : undefined;

  let configLabelKey: string = key;

  if (key in config) {
    configLabelKey = key;
  } else if (payloadPayload && key in payloadPayload) {
    configLabelKey = payloadPayload[key as keyof typeof payloadPayload] as string;
  }

  return configLabelKey in config ? config[configLabelKey] : config[key];
}

export type { ChartConfig, ChartConfigItem };
export { ChartContext, getPayloadConfigFromPayload, useChart };
