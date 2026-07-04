import type { JSX } from 'react';
import { cn } from '@/shared/lib';
import { Card } from '@/shared/ui/card';
import { ListingCardContent } from '@/shared/ui/listing-card-content';
import type { AuthListingItem } from '../model/types';

/** Max skill badges shown on decorative auth cards for visual density. */
const MAX_DECORATIVE_SKILLS = 3;

interface AuthListingCardProps {
  readonly listing: AuthListingItem;
  readonly style?: React.CSSProperties;
  readonly className?: string;
}

export function AuthListingCard({ listing, style, className }: AuthListingCardProps): JSX.Element {
  return (
    <div
      aria-hidden="true"
      tabIndex={-1}
      className={cn('pointer-events-none select-none', className)}
      style={style}
    >
      <Card
        className={cn(
          // Frosted glass base: translucent background with strong blur
          'overflow-hidden border-white/10 bg-card/30 backdrop-blur-lg backdrop-saturate-150',
          'dark:border-white/10 dark:bg-card/20',
          // Depth: atmospheric shadow
          'shadow-black/10 shadow-lg dark:shadow-black/25',
          // Subtle inner edge highlight for glass rim effect
          'ring-1 ring-white/5 dark:ring-white/10',
          // Compact padding overrides target CardHeader, CardContent, CardFooter
          '[&>div:first-child]:p-3 [&>div:first-child]:pb-2',
          '[&>div:nth-child(2)]:px-3 [&>div:nth-child(2)]:pt-0 [&>div:nth-child(2)]:pb-2',
          '[&>div:last-child]:px-3 [&>div:last-child]:pt-0 [&>div:last-child]:pb-3',
          // Mute secondary text for decorative context
          '[&_.text-muted-foreground]:opacity-60',
        )}
      >
        <ListingCardContent
          title={listing.title}
          companyName={listing.company_name}
          locationRaw={listing.location_raw}
          workArrangement={listing.work_arrangement}
          requiredSkills={listing.required_skills.slice(0, MAX_DECORATIVE_SKILLS)}
          postedAt={listing.posted_at}
          language={listing.language}
        />
      </Card>
    </div>
  );
}
