import { useQuery } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { ArrowLeft, Download, FileText, Scale } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { CACHE_CONFIG } from '@/shared/api/index.ts';
import { useDocumentTitle } from '@/shared/lib/index.ts';
import { Badge } from '@/shared/ui/badge.tsx';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import { ScrollArea } from '@/shared/ui/scroll-area.tsx';
import { Separator } from '@/shared/ui/separator.tsx';
import { Skeleton } from '@/shared/ui/skeleton.tsx';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/shared/ui/tabs.tsx';
import { PageLayout } from '@/widgets/layout/index.ts';

// License type configuration
const LICENSE_TYPES = [
  { key: 'mit', pattern: /MIT License/giu, color: 'bg-emerald-500' },
  { key: 'apache', pattern: /Apache License/giu, color: 'bg-blue-500' },
  { key: 'isc', pattern: /ISC License/giu, color: 'bg-violet-500' },
  { key: 'bsd3', pattern: /BSD 3-Clause/giu, color: 'bg-orange-500' },
  { key: 'bsd2', pattern: /BSD 2-Clause/giu, color: 'bg-yellow-500' },
  { key: 'mpl', pattern: /Mozilla Public License/giu, color: 'bg-rose-500' },
] as const;

interface LicenseSummary {
  counts: Record<string, number>;
  total: number;
}

function parseLicenseSummary(content: string): LicenseSummary {
  const counts: Record<string, number> = {};

  for (const { key, pattern } of LICENSE_TYPES) {
    pattern.lastIndex = 0;

    let count = 0;
    while (pattern.exec(content) !== null) {
      count += 1;
    }

    pattern.lastIndex = 0;
    counts[key] = count;
  }

  const packageMatches = content.match(/The following npm package may be included/gu);
  const total = packageMatches?.length ?? 0;
  const knownCount = Object.values(counts).reduce((sum, n) => sum + n, 0);
  counts.other = Math.max(0, total - knownCount);

  return { counts, total };
}

async function fetchLicenses(): Promise<{ content: string; summary: LicenseSummary }> {
  const response = await fetch('/third-party-licenses.txt');
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  const content = await response.text();
  return { content, summary: parseLicenseSummary(content) };
}

function useLicenses(): ReturnType<typeof useQuery<{ content: string; summary: LicenseSummary }>> {
  return useQuery({
    queryKey: ['licenses'],
    queryFn: fetchLicenses,
    staleTime: CACHE_CONFIG.STATIC.staleTime,
    gcTime: CACHE_CONFIG.STATIC.gcTime,
  });
}

function DownloadButton(): JSX.Element {
  const { t } = useTranslation('legal');

  return (
    <Button variant="outline" size="sm" asChild={true}>
      <a href="/third-party-licenses.txt" download="third-party-licenses.txt">
        <Download className="mr-2 size-4" />
        {t('licenses.fullText.download')}
      </a>
    </Button>
  );
}

const LICENSE_LABEL_KEYS = {
  mit: 'licenses.licenses.mit',
  apache: 'licenses.licenses.apache',
  isc: 'licenses.licenses.isc',
  bsd3: 'licenses.licenses.bsd3',
  bsd2: 'licenses.licenses.bsd2',
  mpl: 'licenses.licenses.mpl',
  other: 'licenses.licenses.other',
} as const;

type LicenseKey = keyof typeof LICENSE_LABEL_KEYS;

function LicenseBadges({ summary }: { readonly summary: LicenseSummary }): JSX.Element | null {
  const { t } = useTranslation('legal');

  const badges = [
    ...LICENSE_TYPES.map(({ key, color }) => ({
      key: key as LicenseKey,
      color,
      count: summary.counts[key] ?? 0,
    })),
    { key: 'other' as LicenseKey, color: 'bg-gray-500', count: summary.counts.other ?? 0 },
  ].filter((b) => b.count > 0);

  return (
    <div className="flex flex-wrap gap-2">
      {badges.map(({ key, count, color }) => (
        <Badge key={key} variant="secondary" className="gap-1.5">
          <span className={`h-2 w-2 rounded-full ${color}`} />
          {`${t(LICENSE_LABEL_KEYS[key])} (${count})`}
        </Badge>
      ))}
    </div>
  );
}

function LoadingSkeleton(): JSX.Element {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-4 w-48" />
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-4 w-full" />
          <div className="flex gap-2">
            <Skeleton className="h-6 w-20" />
            <Skeleton className="h-6 w-24" />
            <Skeleton className="h-6 w-16" />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function ErrorState(): JSX.Element {
  const { t } = useTranslation('legal');

  return (
    <Card className="border-destructive">
      <CardContent className="flex items-center gap-3 pt-6 text-destructive">
        <FileText className="size-5" />
        <p>{t('licenses.fullText.error')}</p>
      </CardContent>
    </Card>
  );
}

function LicenseContent({
  content,
  summary,
}: {
  readonly content: string;
  readonly summary: LicenseSummary;
}): JSX.Element {
  const { t } = useTranslation('legal');

  return (
    <Tabs defaultValue="summary" className="space-y-4">
      <TabsList>
        <TabsTrigger value="summary">{t('licenses.summary.title')}</TabsTrigger>
        <TabsTrigger value="full">{t('licenses.fullText.title')}</TabsTrigger>
      </TabsList>

      <TabsContent value="summary" className="space-y-4">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Scale className="size-4" />
              {t('licenses.summary.title')}
            </CardTitle>
            <CardDescription>
              {t('licenses.summary.packages', { count: summary.total })}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-muted-foreground text-sm">{t('licenses.summary.breakdown')}</p>
            <LicenseBadges summary={summary} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('licenses.fullText.title')}</CardTitle>
            <CardDescription>{t('licenses.fullText.description')}</CardDescription>
          </CardHeader>
          <CardContent>
            <DownloadButton />
          </CardContent>
        </Card>
      </TabsContent>

      <TabsContent value="full">
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <div>
              <CardTitle className="text-base">{t('licenses.fullText.title')}</CardTitle>
              <CardDescription>
                {t('licenses.summary.packages', { count: summary.total })}
              </CardDescription>
            </div>
            <DownloadButton />
          </CardHeader>
          <Separator />
          <CardContent className="p-0">
            <ScrollArea className="h-[600px]">
              <pre className="wrap-break-word whitespace-pre-wrap p-4 font-mono text-xs">
                {content}
              </pre>
            </ScrollArea>
          </CardContent>
        </Card>
      </TabsContent>
    </Tabs>
  );
}

export function Licenses(): JSX.Element {
  const { t } = useTranslation('legal');
  const { data, isLoading, isError } = useLicenses();

  useDocumentTitle(t('licenses.title'));

  return (
    <PageLayout contentWidth="medium" className="py-8">
      <div className="mb-6">
        <Button variant="ghost" size="sm" asChild={true}>
          <Link to="/settings">
            <ArrowLeft className="mr-2 size-4" />
            {t('backToSettings')}
          </Link>
        </Button>
      </div>

      <div className="mb-6">
        <h1 className="font-bold text-2xl">{t('licenses.title')}</h1>
        <p className="mt-1 text-muted-foreground">{t('licenses.description')}</p>
      </div>

      {isLoading ? <LoadingSkeleton /> : null}
      {isError ? <ErrorState /> : null}
      {data ? <LicenseContent content={data.content} summary={data.summary} /> : null}
    </PageLayout>
  );
}
