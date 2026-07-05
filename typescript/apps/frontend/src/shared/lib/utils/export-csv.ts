/**
 * Exports an array of objects as a CSV file download.
 * Headers are derived from the keys of the first data row.
 * String values containing commas are wrapped in double quotes.
 */
function exportToCsv(
  data: readonly Record<string, string | number | undefined>[],
  filename: string,
): void {
  const [firstRow] = data;
  if (!firstRow) {
    return;
  }

  const headers = Object.keys(firstRow);
  const csvRows = [
    headers.join(','),
    ...data.map((row) =>
      headers
        .map((h) => {
          const val = row[h];
          return typeof val === 'string' && val.includes(',') ? `"${val}"` : String(val);
        })
        .join(','),
    ),
  ];

  const blob = new Blob([csvRows.join('\n')], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${filename}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

export { exportToCsv };
