import type { JSX, ReactNode } from 'react';

function ArrayFieldItem({ children }: { readonly children: ReactNode }): JSX.Element {
  return <div className="flex-1">{children}</div>;
}

export { ArrayFieldItem };
