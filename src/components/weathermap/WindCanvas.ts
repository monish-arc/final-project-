import L from 'leaflet';

/**
 * Windy-style particle overlay for Leaflet. Draws real wind vectors (u/v m/s)
 * sampled from the live grid as advected particles with fading trails.
 *
 * The layer is teardown-safe: removal cancels the rAF loop and detaches the
 * canvas. All geometry math runs in a lat/lon grid projected to screen each
 * frame, so pan/zoom stays correct without re-seeding.
 */

export interface WindField {
  lat: number[];   // rows, north -> south
  lon: number[];   // cols, west -> east
  u: number[][];   // eastward component, m/s
  v: number[][];   // northward component, m/s
  validTime?: string | null;
  source: string;
}

interface ParticleState {
  lat: number;
  lon: number;
  age: number;
}

interface WindCanvasOptions {
  particleCount?: number;
  speedFactor?: number;
  maxAge?: number;
}

const DEFAULT_COUNT = 2200;
const DEFAULT_SPEED = 0.9;
const DEFAULT_MAX_AGE = 130;

export class WindCanvas extends L.Layer {
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D | null = null;
  private map: L.Map | null = null;
  private field: WindField | null = null;
  private particles: ParticleState[] = [];
  private rafId: number | null = null;
  private running = false;
  private count = DEFAULT_COUNT;
  private speed = DEFAULT_SPEED;
  private maxAge = DEFAULT_MAX_AGE;
  private onFrame?: () => void;

  constructor(options: WindCanvasOptions = {}) {
    super();
    this.count = options.particleCount ?? DEFAULT_COUNT;
    this.speed = options.speedFactor ?? DEFAULT_SPEED;
    this.maxAge = options.maxAge ?? DEFAULT_MAX_AGE;
    this.canvas = document.createElement('canvas');
    this.canvas.style.position = 'absolute';
    this.canvas.style.inset = '0';
    this.canvas.style.width = '100%';
    this.canvas.style.height = '100%';
    this.canvas.style.pointerEvents = 'none';
  }

  onAdd(map: L.Map): this {
    this.map = map;
    const pane = map.getPane('overlayPane');
    if (!pane) return this;
    pane.appendChild(this.canvas);
    map.on('move zoom zoomend resize', this._resize, this);
    map.on('movestart', this._onMoveStart, this);
    this._resize();
    this.running = true;
    this._loop();
    return this;
  }

  onRemove(map: L.Map): this {
    map.off('move zoom zoomend resize', this._resize, this);
    map.off('movestart', this._onMoveStart, this);
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
    this.running = false;
    if (this.canvas.parentNode === map.getPane('overlayPane')) {
      this.canvas.remove();
    }
    return this;
  }

  /** Replace the underlying wind field; reseeds particles when geometry changes. */
  setData(field: WindField): void {
    const changed = !this.field || this.field.lat.length !== field.lat.length || this.field.lon.length !== field.lon.length;
    this.field = field;
    if (changed) this._seed();
  }

  setParticleCount(n: number): void {
    const clamped = Math.max(200, Math.min(6000, Math.round(n)));
    if (clamped === this.count) return;
    this.count = clamped;
    this._seed();
  }

  setSpeed(s: number): void {
    this.speed = Math.max(0.1, Math.min(4, s));
  }

  setMaxAge(a: number): void {
    this.maxAge = Math.max(20, Math.min(600, Math.round(a)));
  }

  pause(): void {
    this.running = false;
  }

  resume(): void {
    if (!this.running) {
      this.running = true;
      this._loop();
    }
  }

  setOnFrame(cb?: () => void): void {
    this.onFrame = cb;
  }

  isRunning(): boolean {
    return this.running;
  }

  getField(): WindField | null {
    return this.field;
  }

  // ---------------- internals ----------------

  private _resize(): void {
    if (!this.map) return;
    const size = this.map.getSize();
    const parent = this.canvas.parentElement;
    const w = parent?.clientWidth ?? size.x;
    const h = parent?.clientHeight ?? size.y;
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = Math.max(1, Math.round(w * dpr));
    this.canvas.height = Math.max(1, Math.round(h * dpr));
    this.canvas.style.width = `${w}px`;
    this.canvas.style.height = `${h}px`;
    this.ctx = this.canvas.getContext('2d');
    this.ctx?.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  private _onMoveStart(): void {
    // Clear the trail residue during pan/zoom for a crisp redraw.
    if (this.ctx && this.map && this.running) {
      this._clearCanvas();
      this._seed();
    }
  }

  private _clearCanvas(): void {
    if (!this.ctx || !this.map) return;
    const size = this.map.getSize();
    this.ctx.clearRect(0, 0, size.x, size.y);
  }

  private _seed(): void {
    if (!this.field) return;
    const { lat, lon } = this.field;
    this.particles = [];
    for (let i = 0; i < this.count; i++) {
      const li = i % lat.length;
      const lj = (i * 7919) % lon.length;
      this.particles.push({
        lat: lat[li],
        lon: lon[lj],
        age: Math.floor(Math.random() * this.maxAge),
      });
    }
  }

  /** Bilinear sample of u/v at (lat, lon); returns [u, v] or null. */
  private _sample(lat: number, lon: number): [number, number] | null {
    const f = this.field;
    if (!f) return null;
    const rows = f.lat.length;
    const cols = f.lon.length;
    let i1 = -1;
    let j1 = -1;
    for (let i = 0; i < rows; i++) {
      if (i === rows - 1 || (f.lat[i] >= lat && lat >= f.lat[i + 1])) {
        i1 = i;
        break;
      }
    }
    for (let j = 0; j < cols; j++) {
      if (j === cols - 1 || (f.lon[j] <= lon && lon <= f.lon[j + 1])) {
        j1 = j;
        break;
      }
    }
    if (i1 < 0 || j1 < 0) return null;
    const i2 = Math.min(i1 + 1, rows - 1);
    const j2 = Math.min(j1 + 1, cols - 1);
    const spanLat = f.lat[i2] - f.lat[i1] || 1;
    const spanLon = f.lon[j2] - f.lon[j1] || 1;
    const tLat = Math.max(0, Math.min(1, (lat - f.lat[i1]) / spanLat));
    const tLon = Math.max(0, Math.min(1, (lon - f.lon[j1]) / spanLon));
    const b00 = [f.u[i1][j1], f.v[i1][j1]];
    const b10 = [f.u[i2][j1], f.v[i2][j1]];
    const b01 = [f.u[i1][j2], f.v[i1][j2]];
    const b11 = [f.u[i2][j2], f.v[i2][j2]];
    const u =
      (b00[0] * (1 - tLat) + b10[0] * tLat) * (1 - tLon) +
      (b01[0] * (1 - tLat) + b11[0] * tLat) * tLon;
    const v =
      (b00[1] * (1 - tLat) + b10[1] * tLat) * (1 - tLon) +
      (b01[1] * (1 - tLat) + b11[1] * tLat) * tLon;
    return [u, v];
  }

  private _loop(): void {
    if (!this.running) return;
    const tick = (): void => {
      this._step();
      if (this.running) {
        this.rafId = requestAnimationFrame(tick);
      }
    };
    this.rafId = requestAnimationFrame(tick);
  }

  private _step(): void {
    const map = this.map;
    const ctx = this.ctx;
    const f = this.field;
    if (!map || !ctx || !f || !this.particles.length) {
      if (this.onFrame) this.onFrame();
      return;
    }
    const size = map.getSize();
    const alpha = 0.08;
    ctx.fillStyle = `rgba(9, 13, 26, ${alpha})`;
    ctx.fillRect(0, 0, size.x, size.y);

    const degPerFrame = (this.speed * 0.035) / (map.getZoom() - 4 < 1 ? 1 : map.getZoom() - 3.2);
    this.particles.forEach((p) => {
      const vec = this._sample(p.lat, p.lon);
      if (!vec) {
        p.age += 1;
        if (p.age > this.maxAge) this._respawn(p);
        return;
      }
      const [u, v] = vec;
      // Only move particles where the field has meaningful u/v; cells with no
      // wind (0,0) do not animate — they simply despawn instead of hovering.
      if (Math.hypot(u, v) < 0.02) {
        p.age += 1;
        if (p.age > this.maxAge) this._respawn(p);
        return;
      }
      p.lat += v * degPerFrame;
      p.lon += u * degPerFrame;
      p.age += 1;
      if (p.age > this.maxAge || p.lat < f.lat[f.lat.length - 1] - 0.5 || p.lat > f.lat[0] + 0.5) {
        this._respawn(p);
        return;
      }
      const a = Math.max(0, 1 - p.age / this.maxAge);
      const aHex = Math.round(255 * a).toString(16).padStart(2, '0');
      const point = map.latLngToContainerPoint([p.lat, p.lon]);
      ctx.fillStyle = `#8ec9ff${aHex}`;
      ctx.fillRect(point.x - 0.5, point.y - 0.5, 1.6, 1.6);
    });
    if (this.onFrame) this.onFrame();
  }

  private _respawn(p: ParticleState): void {
    const f = this.field;
    if (!f) return;
    p.lat = f.lat[0];
    p.lon = f.lon[0] + Math.random() * (f.lon[f.lon.length - 1] - f.lon[0]);
    p.age = 0;
  }
}