type SortDirection = 'asc' | 'desc';

interface SortOption {
  readonly value: string;
  readonly label: string;
}

interface SortSelectProps {
  readonly options: readonly SortOption[];
  readonly value: string;
  readonly direction: SortDirection;
  readonly onValueChange: (value: string) => void;
  readonly onDirectionChange: (direction: SortDirection) => void;
  readonly className?: string;
}

export type { SortDirection, SortOption, SortSelectProps };
