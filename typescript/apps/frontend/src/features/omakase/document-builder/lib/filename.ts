export function slugify(text: string): string {
  return text
    .toLowerCase()
    .trim()
    .replaceAll(/[^\w\s-]/gu, '') // Remove special characters except spaces and hyphens
    .replaceAll(/[\s_-]+/gu, '-') // Replace spaces, underscores, and multiple hyphens with single hyphen
    .replaceAll(/^-+|-+$/gu, ''); // Remove leading and trailing hyphens
}

export function generatePdfFilename(datasetName: string, templateName: string): string {
  const slugifiedDataset = slugify(datasetName);
  const slugifiedTemplate = slugify(templateName);
  return `${slugifiedDataset}-${slugifiedTemplate}.pdf`;
}
