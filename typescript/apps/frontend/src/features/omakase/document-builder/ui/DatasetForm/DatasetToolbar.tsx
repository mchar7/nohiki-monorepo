import { Button } from '@shared/ui/button.tsx';
import { Input } from '@shared/ui/input.tsx';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@shared/ui/select.tsx';
import { Search } from 'lucide-react';
import type React from 'react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import type { TemplateFamilyResponse } from '@/shared/api';

interface DatasetToolbarProps {
  readonly searchTerm: string;
  readonly onSearchChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  readonly selectedTemplateFilter: string;
  readonly onTemplateFilterChange: (value: string) => void;
  readonly sortValue: string;
  readonly onSortChange: (value: string) => void;
  readonly uniqueTemplateVersionIds: string[];
  readonly templateFamilyIndex: Map<string, TemplateFamilyResponse>;
  readonly hasDatasets: boolean;
  readonly showCreateButton: boolean;
  readonly onBulkExport: () => void;
  readonly onCreateNew: () => void;
}

function DatasetToolbar({
  searchTerm,
  onSearchChange,
  selectedTemplateFilter,
  onTemplateFilterChange,
  sortValue,
  onSortChange,
  uniqueTemplateVersionIds,
  templateFamilyIndex,
  hasDatasets,
  showCreateButton,
  onBulkExport,
  onCreateNew,
}: DatasetToolbarProps): JSX.Element {
  const { t } = useTranslation(['omakase.editor', 'common']);

  return (
    <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
      <div className="max-w-md flex-1">
        <div className="relative">
          <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 transform text-muted-foreground" />
          <Input
            type="text"
            placeholder={t('datasets.searchPlaceholder')}
            value={searchTerm}
            onChange={onSearchChange}
            className="w-full pl-10"
          />
        </div>
      </div>

      <div className="flex w-full gap-3 sm:w-auto">
        <Select value={selectedTemplateFilter} onValueChange={onTemplateFilterChange}>
          <SelectTrigger className="flex-1 sm:flex-none">
            <SelectValue placeholder={t('datasets.allTemplates')} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('datasets.allTemplates')}</SelectItem>
            {uniqueTemplateVersionIds.map((versionId) => {
              const family = templateFamilyIndex.get(versionId);
              return (
                <SelectItem key={versionId} value={versionId}>
                  {family?.display_name || t('common:unavailable')}
                </SelectItem>
              );
            })}
          </SelectContent>
        </Select>

        <Select value={sortValue} onValueChange={onSortChange}>
          <SelectTrigger className="flex-1 sm:flex-none">
            <SelectValue placeholder={t('datasets.sortBy')} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="updated-desc">{t('datasets.sort.recentlyUpdated')}</SelectItem>
            <SelectItem value="updated-asc">{t('datasets.sort.oldestUpdated')}</SelectItem>
            <SelectItem value="created-desc">{t('datasets.sort.recentlyCreated')}</SelectItem>
            <SelectItem value="created-asc">{t('datasets.sort.oldestCreated')}</SelectItem>
            <SelectItem value="name-asc">{t('datasets.sort.nameAsc')}</SelectItem>
            <SelectItem value="name-desc">{t('datasets.sort.nameDesc')}</SelectItem>
          </SelectContent>
        </Select>

        <div className="flex gap-2">
          {hasDatasets ? (
            <Button onClick={onBulkExport} variant="outline" className="whitespace-nowrap">
              {t('datasets.exportAll')}
            </Button>
          ) : null}
          {showCreateButton ? (
            <Button onClick={onCreateNew} className="whitespace-nowrap">
              {t('datasets.newDataset')}
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export { DatasetToolbar };
