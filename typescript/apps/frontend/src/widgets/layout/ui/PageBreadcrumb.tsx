import { useMatches } from '@tanstack/react-router';
import { Fragment, type JSX, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useIsMobileLayout } from '@/shared/lib/index.ts';
import { BottomSheet } from '@/shared/ui/bottom-sheet.tsx';
import {
  Breadcrumb,
  BreadcrumbEllipsis,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/shared/ui/breadcrumb.tsx';
import { Button } from '@/shared/ui/button.tsx';

interface BreadcrumbEntry {
  title: string;
  href: string;
  isActive: boolean;
  disabled?: boolean;
}

/** BottomSheet menu for collapsed middle breadcrumb items on mobile. */
function BreadcrumbEllipsisMenu({ items }: { readonly items: BreadcrumbEntry[] }): JSX.Element {
  const { t } = useTranslation(['common']);
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        className="flex items-center gap-1 text-muted-foreground transition-colors hover:text-foreground"
        onClick={() => setMenuOpen(true)}
      >
        <BreadcrumbEllipsis className="size-4" />
      </button>
      <BottomSheet
        open={menuOpen}
        onOpenChange={setMenuOpen}
        title={t('common:pagination.morePages')}
      >
        <div className="flex flex-col gap-1 py-2">
          {items.map((item) => (
            <Button key={item.href} variant="ghost" className="w-full justify-start" asChild={true}>
              <a href={item.href}>{item.title}</a>
            </Button>
          ))}
        </div>
      </BottomSheet>
    </>
  );
}

function renderBreadcrumbContent(item: BreadcrumbEntry, isLast: boolean): JSX.Element {
  if (item.isActive && isLast) {
    return <BreadcrumbPage>{item.title}</BreadcrumbPage>;
  }
  if (item.disabled) {
    return <span className="text-muted-foreground">{item.title}</span>;
  }
  return <BreadcrumbLink href={item.href}>{item.title}</BreadcrumbLink>;
}

export function PageBreadcrumb(): JSX.Element | null {
  const { t } = useTranslation(['common', 'navigation']);
  const isMobile = useIsMobileLayout();
  const matches = useMatches();
  const routeItems = matches.flatMap((match) => {
    const { breadcrumb } = match.staticData ?? {};
    if (!breadcrumb) {
      return [];
    }
    return [{ title: String(t(breadcrumb)), href: match.pathname }];
  });

  const items: BreadcrumbEntry[] = [
    { title: String(t('common:appName')), href: '#', isActive: false, disabled: true },
    ...routeItems.map((item, index) => ({
      ...item,
      isActive: index === routeItems.length - 1,
    })),
  ];

  // Collapse to ellipsis when there are 3+ breadcrumb items on mobile
  const MOBILE_ELLIPSIS_THRESHOLD: number = 3;
  if (isMobile && items.length >= MOBILE_ELLIPSIS_THRESHOLD) {
    const [firstItem, ...rest] = items;
    const middleItems = rest.slice(0, -1);
    const lastItem = rest.at(-1);
    if (!(firstItem && lastItem)) {
      return null;
    }

    return (
      <Breadcrumb>
        <BreadcrumbList>
          {/* First item - always visible but compact */}
          <BreadcrumbItem className="hidden sm:block">
            <span className="text-muted-foreground text-sm">{firstItem.title}</span>
          </BreadcrumbItem>
          <BreadcrumbSeparator className="hidden sm:block" />

          {/* Collapsed middle items */}
          {middleItems.length > 0 && (
            <>
              <BreadcrumbItem>
                <BreadcrumbEllipsisMenu items={middleItems} />
              </BreadcrumbItem>
              <BreadcrumbSeparator />
            </>
          )}

          {/* Current page - always visible */}
          <BreadcrumbItem>
            <BreadcrumbPage className="max-w-40 truncate">{lastItem.title}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>
    );
  }

  // Desktop: full breadcrumb
  return (
    <Breadcrumb>
      <BreadcrumbList>
        {items.map((item, index) => (
          <Fragment key={item.href}>
            {index > 0 && <BreadcrumbSeparator className="mx-2" />}
            <BreadcrumbItem>
              {renderBreadcrumbContent(item, index === items.length - 1)}
            </BreadcrumbItem>
          </Fragment>
        ))}
      </BreadcrumbList>
    </Breadcrumb>
  );
}
