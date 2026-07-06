import type { JSX } from 'react';

interface HighlightProps {
  /** Full text to display */
  readonly text: string;
  /** Search query to highlight within the text */
  readonly query: string | null | undefined;
  /** CSS class applied to `<mark>` elements (default: "bg-yellow-200 dark:bg-yellow-500/30") */
  readonly className?: string;
}

/**
 * Highlights matched substrings within text by wrapping them in `<mark>` tags.
 * Case-insensitive matching. Returns plain text when no query is provided.
 *
 * @example
 * ```tsx
 * <Highlight text="Software Engineer" query="eng" />
 * // Renders: Software <mark>Eng</mark>ineer
 * ```
 */
export function Highlight({
  text,
  query,
  className = 'bg-yellow-200 dark:bg-yellow-500/30',
}: HighlightProps): JSX.Element {
  if (!query?.trim()) {
    return <>{text}</>;
  }

  const searchQuery = query.toLowerCase();
  const queryLength = query.length;
  const normalizedText = text.toLowerCase();

  const parts: Array<JSX.Element | string> = [];
  let startIndex = 0;
  let matchIndex = normalizedText.indexOf(searchQuery);

  while (matchIndex !== -1) {
    if (matchIndex > startIndex) {
      parts.push(text.slice(startIndex, matchIndex));
    }

    parts.push(
      <mark key={`match-${matchIndex}`} className={className}>
        {text.slice(matchIndex, matchIndex + queryLength)}
      </mark>,
    );

    startIndex = matchIndex + queryLength;
    matchIndex = normalizedText.indexOf(searchQuery, startIndex);
  }

  if (startIndex < text.length) {
    parts.push(text.slice(startIndex));
  }

  return <>{parts}</>;
}
