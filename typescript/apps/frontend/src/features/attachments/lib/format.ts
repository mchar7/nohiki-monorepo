/**
 * Get file extension from filename.
 */
export function getFileExtension(filename: string): string {
  const parts = filename.split('.');
  if (parts.length > 1) {
    return parts.pop()?.toLowerCase() ?? '';
  }
  return '';
}

/**
 * Get content type category for icon display.
 */
export function getFileCategory(
  contentType: string,
): 'pdf' | 'word' | 'image' | 'text' | 'unknown' {
  if (contentType === 'application/pdf') {
    return 'pdf';
  }
  if (
    contentType === 'application/msword' ||
    contentType === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
  ) {
    return 'word';
  }
  if (contentType.startsWith('image/')) {
    return 'image';
  }
  if (contentType.startsWith('text/')) {
    return 'text';
  }
  return 'unknown';
}
