export type LiveProviderKind = 'open-meteo' | 'ecmwf' | 'noaa' | 'nws' | 'other';

export interface LiveProviderConfig {
  id: string;
  name: string;
  kind: LiveProviderKind;
  baseUrl?: string;
  note?: string;
  /** Always false/absent in this project — the backend has
   *  WEATHER_LIVE_ENABLED=False, so no provider can ever be switched on.
   *  Kept for future opt-in. */
  enabled?: false;
}

/** Curated, optional live-provider templates. Selecting one never fires any
 *  network call; it is only stored locally for a future backend opt-in. */
export const LIVE_PROVIDER_TEMPLATES: LiveProviderConfig[] = [
  {
    id: 'open-meteo',
    name: 'Open-Meteo',
    kind: 'open-meteo',
    baseUrl: 'https://api.open-meteo.com/v1',
    note: 'Free, no key required',
  },
  {
    id: 'ecmwf',
    name: 'ECMWF (MARS/IFS)',
    kind: 'ecmwf',
    note: 'Requires institutional credentials',
  },
  {
    id: 'noaa',
    name: 'NOAA NDFD',
    kind: 'noaa',
    baseUrl: 'https://graphical.weather.gov/xml/SOAP_server/ndfdSOAPclient.php',
    note: 'US-centric grid; no India coverage',
  },
  {
    id: 'nws',
    name: 'NWS National Weather Service',
    kind: 'nws',
    baseUrl: 'https://api.weather.gov',
    note: 'US-only point endpoints; not an India grid',
  },
  {
    id: 'other',
    name: 'Custom provider',
    kind: 'other',
    note: 'Bring your own endpoint',
  },
];

const STORAGE_KEY = 'safe-move/live-providers';

let memoryFallback: LiveProviderConfig[] | null = null;

function store(): Storage | null {
  try {
    return typeof window !== 'undefined' && window.localStorage ? window.localStorage : null;
  } catch {
    return null;
  }
}

function persist(providers: LiveProviderConfig[]): void {
  memoryFallback = providers;
  const s = store();
  if (s) {
    try {
      s.setItem(STORAGE_KEY, JSON.stringify(providers));
    } catch {
      /* keep in-memory fallback only */
    }
  }
}

export function getLiveProviders(): LiveProviderConfig[] {
  if (memoryFallback) return memoryFallback;
  const s = store();
  if (s) {
    try {
      const raw = s.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as LiveProviderConfig[];
        if (Array.isArray(parsed)) return parsed;
      }
    } catch {
      /* fall through */
    }
  }
  return [];
}

/** Upsert a provider, always keeping `enabled` false (backend opt-in only). */
export function saveLiveProvider(cfg: LiveProviderConfig): LiveProviderConfig[] {
  const providers = getLiveProviders();
  const next = [
    ...providers.filter((p) => p.id !== cfg.id),
    { ...cfg, enabled: false as const },
  ];
  persist(next);
  return next;
}

export function removeLiveProvider(id: string): LiveProviderConfig[] {
  const next = getLiveProviders().filter((p) => p.id !== id);
  persist(next);
  return next;
}

/** Providers that could actually be queried right now — always empty since
 *  `enabled` is hard-typed false. */
export function enabledLiveProviders(providers: LiveProviderConfig[]): LiveProviderConfig[] {
  return providers.filter((p) => (p as { enabled?: boolean }).enabled === true);
}

export function liveProviderStatus(_cfg: LiveProviderConfig): 'disabled' {
  return 'disabled';
}

/** Clears the stored provider list (localStorage + memory fallback). Used by
 *  tests and available as a UI reset. */
export function resetLiveProviderStore(): void {
  memoryFallback = null;
  const s = store();
  if (s) {
    try {
      s.removeItem(STORAGE_KEY);
    } catch {
      /* no-op */
    }
  }
}