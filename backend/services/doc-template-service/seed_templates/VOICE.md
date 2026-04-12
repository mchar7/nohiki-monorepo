# Voice & Writing Conventions

Authoritative writing-style reference for content generated against the
`resume` and `cover_letter` seed templates. Divided into two layers:

1. **Deterministic enforcement**: mechanical rules the tailor lint engine
   enforces automatically via `.lint.yaml` configs. These are listed here
   for human reference only; the YAML configs are the source of truth.
2. **Subjective guidelines**: judgement-based guidance for prose that
   cannot be reduced to a deterministic rule. These are the rules humans
   and LLM reviewers must still apply consciously.

## Authority

| Concern | Source of truth | Location |
|---|---|---|
| Deterministic mechanics (counts, patterns, bounds, cross-doc echoes) | YAML lint configs | `default_{resume,cover_letter}_template.lint.yaml` |
| Subjective voice (tone, narrative arc, verb/subject coherence) | This document | `VOICE.md` (this file) |
| Lint engine architecture | Code | `scripts/util/tailor/src/tailor/lint/` |

Do not duplicate a YAML-enforced rule here. If a mechanic becomes
deterministic, delete its prose description from this file.

## Deterministic Enforcement (see YAML configs)

The tailor lint engine enforces the following mechanics automatically.
Fix the YAML if behaviour needs to change; do not restate the rule here.

### Resume

| Mechanic | Rule ID | Severity |
|---|---|---|
| No em-dashes or en-dashes in bullets | `text.resume_bullets.banned_patterns_warning` | warning |
| Forbid AI-slop verb openers (`Architected`, `Engineered`, `Spearheaded`, `Leveraged`, `Utilized`, `Established`, `Validated`, `Orchestrated`) | `content.experience_bullets.banned_openers`, `content.project_bullets.banned_openers` | warning |
| Forbid weak ownership phrasing (`responsible for`, `assisted with`) | `text.resume_bullets.banned_patterns_warning` | warning |
| Flag lazy qualifiers (`various`, `utilized`) | `text.resume_bullets.banned_patterns_info` | info |
| Bullet counts, word counts, verb tense | `content.*_bullets.min_items`, `.max_items`, `.min_words_per_item`, `.max_words_per_item`, `.verb_tense` | mixed |
| Unique opening verb per entry | `content.*_bullets.unique_opening_words` (scope: entry) | warning |
| Skill-category constraints (name bans, counts, capitalization) | `content.skill_categories.*` (gated by `schema_has_path('skills.categories')`) | warning |
| Required sections present and ordered | `structure.required_sections`, `structure.section_order` | error / warning |
| Rendered document fits in max-pages | `layout.max_pages_exceeded.resume` (hard 2-page ceiling), `layout.page_overflow.resume` (soft with 5pt tolerance) | error / warning |

### Cover letter

| Mechanic | Rule ID | Severity |
|---|---|---|
| No em-dashes, "passionate about", "team player", meta-joiners | `text.cover_letter.banned_patterns_warning` | warning |
| Flag "I am writing to", cleft constructions | `text.cover_letter.banned_patterns_info` | info |
| Body-paragraph counts and word bounds | `content.body_paragraphs.min_items`, `.max_items`, `.min_words_per_item`, `.max_words_per_item`, `.min_total_words`, `.max_total_words` | mixed |
| Max 2 structural punctuation marks (`;`, `:`) per sentence | `content.body_paragraphs.max_structural_punctuation` | warning |
| No more than 2 consecutive sentences starting with `I` | `content.body_paragraphs.max_consecutive_i` | warning |
| Flat sentence-length rhythm (word-count mode) | `content.body_paragraphs.rhythm` | warning |
| Contraction density between 0.8 and 2.0 per 100 words | `content.body_paragraphs.contraction_density` | warning |
| Employer mentioned at least 3× when `has_tag('has_employer_var')` | `content.body_paragraphs.employer_mentions_min` (substitutes `{{ employer_name }}`) | warning |
| No more than 2 school/alma-mater mentions | `content.body_paragraphs.school_mentions_max` | warning |
| Synthesis paragraph must not re-enumerate numbers from prior paragraphs (gated by `has_tag('four_paragraph_structure')`) | `content.body_paragraphs.synthesis_re_enumeration` | warning |
| No 4-word phrase repeats across paragraphs | `content.body_paragraphs.cross_paragraph_echo` | warning |
| No 6-word phrase reused from sibling resume (gated by `has_sibling('resume')`) | `content.cover_letter.resume_echo_check` | warning |
| Last sentence does not end on a weak/generic word (risky-words list in YAML) | `content.body_paragraphs.orphan_final_word` | info |
| Rendered cover letter fits on one page; final paragraph does not widow | `layout.max_pages_exceeded.cover_letter`, `layout.orphan.body_paragraphs` | error / warning |

### _tailor_meta tags

Reserved tags the generator sets on input data to activate conditional
rules. Add new tags here when introducing new gated rules.

| Tag | Activates | Semantics |
|---|---|---|
| `has_employer_var` | `employer_mentions_min` | `lint_vars.employer_name` holds the target employer string |
| `four_paragraph_structure` | `synthesis_re_enumeration` | Body has exactly 4 paragraphs; `body_paragraphs[3]` is synthesis |
| `dev_role` | (reserved) | Technical individual-contributor role |
| `executive_role` | (reserved) | Executive / leadership role |
| `technical_hiring_manager` | (reserved) | Reviewer is a hands-on engineer |

## Subjective Guidelines (human/LLM judgement)

The following mechanics are **not** lintable and must still be reviewed
consciously. They are listed here (not in any YAML config) because no
deterministic rule can capture them without producing excessive false
positives or false negatives.

### 1. Verb/subject coherence (inanimate + human-verb pairings)

Inanimate subjects should not perform human actions. "The dashboard
decided to escalate" should become "Owners used the dashboard to
escalate." Watch especially for:

- **Tools as agents:** `The pipeline chose`, `the service believed`
- **Abstractions as agents:** `The strategy wanted`, `the roadmap felt`

A deterministic rule here would flag valid metaphorical uses; keep it
subjective.

### 2. Pronoun chains longer than 2

Sentences or paragraph stretches with more than two consecutive `I`/
`we`/`my`/`our` references become self-centred. Re-anchor to the
employer, the role, the problem. The `max_consecutive_i` lint rule
catches the easy case (3+ sentences starting with `I`); this
guideline covers the subtler cases within and across sentences.

### 3. Pull-quote sentences

Any sentence that would look good on a slide pulled out of context
 (bumper stickers, LinkedIn banners, or framed mission statements)
should be rewritten. These read as performative rather than
confident.

Examples to avoid:

- "Great code is honest code."
- "I lead by listening."
- "Excellence is the foundation of trust."

### 4. Two-step reader bridges

The reader should not have to cross-reference two sentences to
understand a claim. If sentence A introduces a metric and sentence B
interprets it, consider collapsing them.

### 5. Tone, voice, narrative arc

Paragraph-level coherence: does the opening paragraph earn the closing
paragraph? Does the voice stay in one register (confident-technical,
not oscillating between bravado and self-deprecation)? Does the cover
letter have a beginning, middle, and end?

### 6. Paragraph-level coherence

Each paragraph should have one argument. If a body paragraph starts
about impact and ends about technical stack, it is two paragraphs
glued together.

### 7. Strategic content decisions

What gets included is a strategic choice, not a mechanical one.
Subordinate accomplishments to the target role; prune anything that
does not serve the narrative. The lint engine cannot make this
judgement.

## Quick Reference

- **New writing mechanic** → add a YAML rule (extend this table after)
- **New subjective guideline** → add to this file only
- **Engine bug** → `scripts/util/tailor/src/tailor/lint/`
- **Full rule registry** → `scripts/util/tailor/src/tailor/lint/registry.py`
  (content rules) and `scripts/util/tailor/src/tailor/lint/layout/rules.py`
  (layout rules)

This document is the **authoritative source** for subjective voice
conventions. The YAML configs are the authoritative source for
mechanical rules. Neither replaces the other; both together define the
full set of writing expectations.
