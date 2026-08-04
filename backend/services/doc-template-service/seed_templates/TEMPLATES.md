# Seed Templates Reference

Technical reference for the seed templates used by the tailor CLI and the
doc-template-service. Covers the shared design system, template architecture,
layout engines, and schema conventions.

## Overview

Seed templates are bundled with the doc-template-service and seeded on startup.
They live in `seed_templates/` with corresponding schemas in `seed_schemas/`.

- **Discovery:** The tailor CLI's file adapter globs `*.html` (flat, not recursive) in the templates directory.
- **Naming:** Each template has a `TMPL_META` JSON block in an HTML comment
  at the top of the file. The `"name"` field is used for CLI matching
  (`--template resume`, `--template cover_letter`).
- **Schema matching:** Schemas in `seed_schemas/` are matched to templates by name.

### TMPL_META Format

Every template starts with a metadata block:

```html
<!-- TMPL_META
{
  "name": "cover_letter",
  "title": "Cover Letter Template",
  "description": "Professional cover letter with adaptive layout...",
  "namespace": "cover_letter",
  "visibility": "public",
  "version": "2.0.0",
  "access_scope": "SYSTEM",
  "requires_javascript": {
    "required": true,
    "reason": "Adaptive layout engine that adjusts line spacing..."
  }
}
-->
```

Fields: `name` (CLI match key), `title`, `description`, `namespace`, `visibility`
(`public` or `internal`), `version`, `access_scope`. `requires_javascript` is
optional; include it if the template has a layout engine or other JS.

### Current Templates

| Template | File | Schema | Visibility |
| --- | --- | --- | --- |
| `resume` | `default_resume_template.html` | `default_resume_schema.json` | public |
| `cover_letter` | `default_cover_letter_template.html` | `default_cover_letter_schema.json` | public |
| `job_notification` | `default_job_notification_template.html` | (none) | internal |

The `job_notification` template is an email template (namespace `messaging-service`),
not a document template. It has no schema and is not used by the tailor CLI.

## Design System

Shared visual language across all templates. Any new template should follow
these conventions for visual consistency.

### Typography

- **Font:** Noto Sans (loaded via Google Fonts CDN)
- **Weights:** 300 (light/metadata), 400 (body text), 600 (labels/entry titles), 900 (section titles, resume only)
- **Icons:** Font Awesome 6.0 (loaded via CDN)
  - Contact icons: `fa-envelope`, `fa-phone`, `fa-map-marker-alt`, `fa-code`

### Color Palette

| Token | Hex | Usage |
| --- | --- | --- |
| Heading | `#1a1a1a` | Section titles, entry titles, name, labels |
| Body | `#333333` | Body text, contact items |
| Secondary | `#444444` | Subtitle, organization names |
| Background | `#f0f0f0` | Header background, footer bar |
| Icon | `#000000` | Font Awesome icons, bullet markers |

### Header

Both templates share an identical header design:

- Gray `#f0f0f0` background, full width
- Left: name in 36pt, weight 400, uppercase, letter-spacing 0.05em
- Left below name: professional title in 13pt, weight 400, uppercase, letter-spacing 0.1em, color #444444
- Right: contact items with Font Awesome icons, right-aligned, 10pt

## Cover Letter Template

### Container Strategy

The container fills the entire page with zero margin. Visual margins are
created by padding inside child elements. This eliminates gaps between the
container and page edges.

```css
.letter-container {
    width: 8.5in;    /* US Letter width */
    height: 11in;    /* US Letter height */
    margin: 0;       /* NO external margin */
    display: flex;
    flex-direction: column;
    overflow: hidden;
}
```

**Why inches, not mm:** mm-based dimensions cause sub-pixel rounding gaps in
Gotenberg's Chromium renderer. Inches are the native unit for US Letter and
avoid this problem entirely.

**Why zero margin:** Container margin creates white gaps between the content
and the page edge. The footer and header need to extend to the page edges,
so the container must BE the page.

### Layout Structure

```text
.letter-container
  .header         (gray background, padding: 0.7in top, 0.75in sides)
  .body           (flex: 1, padding: 0.3in top, 1.1in sides)
    .position-line
    .salutation
    .letter-content
      <p> (body paragraphs)
      <p class="closing-line"> (optional thank-you line)
    .closing
      <p class="sign-off">   (e.g., "Sincerely,")
      <p class="signature-name"> (e.g., "Matt Chard")
  .footer         (0.15in gray bar, full page width)
```

**Key structural decisions:**

- `closing_line` is inside `.letter-content`, not `.closing`. It's semantically
  a body paragraph and gets paragraph-gap spacing from the layout engine.
- `.closing` only contains the sign-off unit (sign-off + name) with 4pt fixed internal spacing.
- Body side padding (1.1in) is wider than header side padding (0.75in), creating a "full-bleed header / indented body" effect.

### CSS Conventions

All body text inherits `font-family`, `font-size`, `line-height`, and `color`
from the `body` element (#333333, weight 400). Only elements that need to
differ have overrides:

| Element | Override | Reason |
| --- | --- | --- |
| `.position-line` | `font-weight: 300` | Value text is lighter than body |
| `.position-label` | `font-weight: 600; color: #1a1a1a` | Label stands out from value |
| `.closing .sign-off` | `margin-bottom: 4pt` | Fixed gap to signature name |

No redundant `font-family` declarations. No stray color overrides.

### CSS Variables

```css
:root {
    --line-height: 1.42;   /* adjusted by layout engine */
    --font-size: 10pt;     /* adjusted by layout engine */
}
```

### Layout Engine

JavaScript that adapts typography and spacing so every generated cover letter
fills the page naturally, regardless of content length.

#### Modules

Each module is a frozen object literal with a single responsibility:

| Module | Responsibility | Stateful? |
| --- | --- | --- |
| `LayoutConfig` | Frozen tuning constants | No |
| `DomUtils` | DOM queries and mutations | No |
| `CssVariables` | CSS custom property management | No |
| `MeasurementEngine` | Content height and slack calculation | No |
| `ShrinkEngine` | Progressive typography shrinking | Yes (lineHeight, fontSize) |
| `GapDistributor` | Proportional gap distribution with min/max clamping | No |
| `LayoutOrchestrator` | Pipeline coordinator + typography expansion | No |

#### Pipeline

```text
1. CssVariables.reset()          Set defaults (line-height 1.42, font-size 10pt)
2. DomUtils.resetGaps()          Clear all inline margins to 0
3. ShrinkEngine.reset() + fit()  If content + minGaps > available: shrink
4. expandTypography()            If slack remains: modestly boost line-height
5. DomUtils.resetGaps()          Clear margins before fresh distribution
6. GapDistributor.distribute()   Proportionally fill section/paragraph/footer gaps
```

Runs on `DOMContentLoaded` -> `document.fonts.ready` -> run + 100ms retry.

#### Config Values

| Parameter | Value | Rationale |
| --- | --- | --- |
| `lineHeightStart` | 1.42 | Higher than resume (1.35); prose needs more leading than bullets |
| `lineHeightMin` | 1.3 | Minimum readable for continuous paragraphs |
| `lineHeightMax` | 1.55 | Comfortable max; prevents overly loose text |
| `fontSizeStart` | 10pt | Standard body text |
| `fontSizeMin` | 9pt | Higher floor than resume (8.5pt); paragraphs need readability |
| `sectionGapMin / Max` | 10 / 20pt | Between structural blocks (position, salutation, body, closing) |
| `paragraphGapMin / Max` | 6 / 12pt | Between body paragraphs |
| `footerGapMin / Max` | 25 / 65pt | Between last content and footer; absorbs remaining slack |
| `section ratio` | 2 | Section gaps get 2x weight in proportional distribution |
| `paragraph ratio` | 1.5 | Paragraph gaps get 1.5x weight |
| `expansionThreshold` | 30pt | Minimum slack before line-height expansion triggers |
| Expansion damping | 0.65 | Controls how aggressively line-height expands toward max |

#### GapDistributor Algorithm

Distributes available slack across section gaps, paragraph gaps, and footer gap
using weighted proportional allocation with iterative min/max clamping:

1. Calculate budget: `available - contentHeight - footerGapMin`
2. Distribute proportionally: `unitSize = budget / weightedSum`
3. If any gap exceeds its min/max bound: pin it, subtract from budget, redistribute
4. Remaining budget after all gaps are assigned goes to footer gap (capped at footerGapMax)

Maximum 4 clamping passes. O(1) for any realistic input.

## Resume Template

Brief comparison for reference. The resume uses the same design system but
has a more complex layout.

| Aspect | Resume | Cover Letter |
| --- | --- | --- |
| Layout | Two-column with gray left sidebar | Single column |
| Container | `216mm x 279mm` with `10mm` margin (rounded from US Letter 215.9 x 279.4mm) | `8.5in x 11in` with zero margin |
| Line-height default | 1.35 | 1.42 |
| Font-size minimum | 8.5pt | 9pt |
| Additional JS modules | EquationSolver, SkillsFormatter, alignBottoms | (none) |
| Gap types | Section, entry, line | Section, paragraph, footer |
| Column balancing | Yes (alignBottoms) | N/A |
| Word-wrap optimization | Yes (SkillsFormatter) | N/A |

The resume container uses mm dimensions with external margin because it has no
elements that need to reach the page edges. The cover letter uses inches with
zero margin because the header and footer extend edge-to-edge.

## Schema Conventions

Patterns shared by the resume and cover letter schemas. Follow these when
creating new schemas.

- `additionalProperties: false` on all objects (strict validation)
- `full_name`, `professional_title`, and `contact` use **identical structure**
  across schemas (same field names, same nesting, same required fields)
- Every field gets `title`, `description`, and `examples`
- `required` arrays are explicit on all objects
- Cover letter `body_paragraphs` is a flat string array (not nested objects)
- `closing_line` is optional; `sign_off` defaults to `"Sincerely,"`

### Cover Letter Schema Fields

```text
full_name            string (required)
professional_title   string (required)
contact              object (required) { email, phone, location, website? }
position             string (required) - job title, optionally with ref number
salutation           string (required) - e.g. "Dear Hiring Manager,"
body_paragraphs      string[] (required, 1-6 items)
closing_line         string (optional) - e.g. "Thank you very much..."
sign_off             string (required) - e.g. "Sincerely,"
```
