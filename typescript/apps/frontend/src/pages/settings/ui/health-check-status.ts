/** Maps a service health status string to a Tailwind colour class set. */
function getStatusColor(status: string): string {
  const s = status.toLowerCase();
  if (s === 'up' || s === 'healthy' || s === 'ok') {
    return 'bg-green-100 text-green-800 border-green-200 dark:bg-green-950 dark:text-green-300 dark:border-green-800';
  }
  if (s === 'degraded' || s === 'warning') {
    return 'bg-yellow-100 text-yellow-800 border-yellow-200 dark:bg-yellow-950 dark:text-yellow-300 dark:border-yellow-800';
  }
  if (s === 'down' || s === 'error' || s === 'unhealthy') {
    return 'bg-red-100 text-red-800 border-red-200 dark:bg-red-950 dark:text-red-300 dark:border-red-800';
  }
  return 'bg-gray-100 text-gray-800 border-gray-200 dark:bg-gray-950 dark:text-gray-300 dark:border-gray-800';
}

export { getStatusColor };
