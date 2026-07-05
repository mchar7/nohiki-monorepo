interface MatchExplanation {
  readonly strengths: string[];
  readonly concerns: string[];
}

const EMPTY_EXPLANATION: MatchExplanation = { strengths: [], concerns: [] };

/** Lazy capture of section body uses lookahead to stop at the next section boundary or end of string. */
const STRENGTHS_PATTERN = /Strengths:\s*(.*?)(?=\.\s*(?:Concerns:|$))/su;
const CONCERNS_PATTERN = /Concerns:\s*(.*?)(?=\.\s*(?:Strengths:|$))/su;

/** Regex extracting just the factor name from entries like "skill_match (+0.5)". */
const FACTOR_NAME_PATTERN = /^\s*([a-z_]+)/iu;

/** Converts a snake_case identifier to Title Case (e.g. "skill_match" → "Skill Match"). */
function toTitleCase(snakeCase: string): string {
  return snakeCase
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ');
}

/** Extracts factor names from a comma-separated section body and converts to Title Case. */
function parseFactors(raw: string): string[] {
  return raw
    .split(',')
    .map((entry) => {
      const nameMatch = FACTOR_NAME_PATTERN.exec(entry);
      return nameMatch?.[1] ? toTitleCase(nameMatch[1]) : '';
    })
    .filter(Boolean);
}

/**
 * Parses an ML explanation string into structured strengths and concerns.
 *
 * Expected format: "Strengths: skill_match (+0.5), location_fit (+0.3). Concerns: experience_gap (-0.2)."
 *
 * Returns empty arrays for null, undefined, empty, or malformed input; never throws.
 */
function parseMatchExplanation(explanation: string | undefined | null): MatchExplanation {
  if (!explanation?.trim()) {
    return EMPTY_EXPLANATION;
  }

  const strengthsMatch = STRENGTHS_PATTERN.exec(explanation);
  const concernsMatch = CONCERNS_PATTERN.exec(explanation);

  const strengths = strengthsMatch?.[1] ? parseFactors(strengthsMatch[1]) : [];
  const concerns = concernsMatch?.[1] ? parseFactors(concernsMatch[1]) : [];

  return { strengths, concerns };
}

export { parseMatchExplanation };
