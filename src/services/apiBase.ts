const API_BASE_URL: string | undefined = import.meta.env.VITE_API_BASE_URL;

export function apiUrl(path: string): string {
  if (!API_BASE_URL || !path.startsWith('/')) return path;
  const base = API_BASE_URL.replace(/\/+$/, '').replace(/\/api$/i, '');
  return `${base}${path}`;
}