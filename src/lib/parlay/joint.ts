/**
 * Joint probability of a parlay under a Gaussian copula (TEST, Moose 2026-11-27). TypeScript twin of
 * modeling/modelroom/parlay/joint.py: the Python file runs the backtest, this one runs on the site; tests check that
 * both give the same numbers.
 *
 * A leg is an event on one latent variable: side * Z > Phi^-1(1 - p). Several legs can sit on one variable (points
 * 20+ and points 25+; a spread and a moneyline are both the home margin). Variables are linked by correlations from
 * the historical table. Two one-sided variables: exact bivariate normal (Genz). Otherwise Genz's seeded
 * separation-of-variables integration, so the same parlay always gets the same number. Pure: no I/O.
 */

export type Side = 1 | -1;
export interface JointLeg { variable: number; side: Side; p: number }
export interface JointResult { p: number; se: number; method: string }

// ------------------------------------------------------------------------------------------------- normal helpers
/** Standard normal CDF: Taylor series for erf near zero, continued fraction for erfc in the tails (about 1e-15). */
export function phi(x: number): number {
  if (x === Infinity) return 1;
  if (x === -Infinity) return 0;
  return 0.5 * erfc(-x / Math.SQRT2);
}

function erfc(x: number): number {
  const z = Math.abs(x);
  let r: number;
  if (z < 2.5) {
    // erf(z) = 2/sqrt(pi) * sum_n (-1)^n z^(2n+1) / (n! (2n+1))
    let term = z;
    let sum = z;
    const zz = z * z;
    for (let n = 1; n < 200; n++) {
      term *= -zz / n;
      const add = term / (2 * n + 1);
      sum += add;
      if (Math.abs(add) < 1e-17 * Math.abs(sum)) break;
    }
    r = 1 - (2 / Math.sqrt(Math.PI)) * sum;
  } else {
    // erfc(z) = exp(-z^2)/sqrt(pi) / (z + (1/2)/(z + 1/(z + (3/2)/(z + 2/(z + ...)))))
    let t = 0;
    for (let k = 120; k >= 1; k--) t = k / 2 / (z + t);
    r = Math.exp(-z * z) / Math.sqrt(Math.PI) / (z + t);
  }
  return x < 0 ? 2 - r : r;
}

/** Inverse standard normal CDF (Acklam's approximation, one Halley step: about 1e-15 relative error). */
export function invPhi(p: number): number {
  if (p <= 0) return -Infinity;
  if (p >= 1) return Infinity;
  const a = [-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2, 1.38357751867269e2, -3.066479806614716e1, 2.506628277459239];
  const b = [-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2, 6.680131188771972e1, -1.328068155288572e1];
  const c = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
  const d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996, 3.754408661907416];
  const lo = 0.02425;
  let x: number;
  if (p < lo) {
    const q = Math.sqrt(-2 * Math.log(p));
    x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  } else if (p <= 1 - lo) {
    const q = p - 0.5;
    const r = q * q;
    x = ((((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q) / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
  } else {
    const q = Math.sqrt(-2 * Math.log(1 - p));
    x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }
  const e = phi(x) - p;
  const u = e * Math.sqrt(2 * Math.PI) * Math.exp((x * x) / 2);
  return x - u / (1 + (x * u) / 2);
}

// ------------------------------------------------------------------------------------------------- bivariate normal
const GL = {
  6: { w: [0.1713244923791705, 0.3607615730481384, 0.4679139345726904], x: [0.9324695142031522, 0.6612093864662647, 0.238619186083197] },
  12: {
    w: [0.04717533638651177, 0.1069393259953183, 0.1600783285433464, 0.2031674267230659, 0.2334925365383547, 0.2491470458134029],
    x: [0.9815606342467191, 0.904117256370475, 0.769902674194305, 0.5873179542866171, 0.3678314989981802, 0.1252334085114692],
  },
  20: {
    w: [0.01761400713915212, 0.04060142980038694, 0.06267204833410906, 0.08327674157670475, 0.1019301198172404, 0.1181945319615184,
      0.1316886384491766, 0.1420961093183821, 0.1491729864726037, 0.1527533871307259],
    x: [0.9931285991850949, 0.9639719272779138, 0.9122344282513259, 0.8391169718222188, 0.7463319064601508, 0.636053680726515,
      0.5108670019508271, 0.3737060887154196, 0.2277858511416451, 0.07652652113349733],
  },
};

/** P(X > h, Y > k) for a standard bivariate normal with correlation r (Genz 2004). */
export function bvnu(h: number, k: number, r: number): number {
  if (h === Infinity || k === Infinity) return 0;
  if (h === -Infinity) return k === -Infinity ? 1 : phi(-k);
  if (k === -Infinity) return phi(-h);
  if (r === 0) return phi(-h) * phi(-k);
  const g = Math.abs(r) < 0.3 ? GL[6] : Math.abs(r) < 0.75 ? GL[12] : GL[20];
  const W = [...g.w, ...g.w];
  const X = [...g.x.map((v) => 1 - v), ...g.x.map((v) => 1 + v)];
  const tp = 2 * Math.PI;
  let hk = h * k;
  let bvn = 0;
  if (Math.abs(r) < 0.925) {
    const hs = (h * h + k * k) / 2;
    const asr = Math.asin(r) / 2;
    for (let i = 0; i < X.length; i++) {
      const sn = Math.sin(asr * X[i]);
      bvn += W[i] * Math.exp((sn * hk - hs) / (1 - sn * sn));
    }
    bvn = (bvn * asr) / tp + phi(-h) * phi(-k);
  } else {
    if (r < 0) {
      k = -k;
      hk = -hk;
    }
    if (Math.abs(r) < 1) {
      const as = 1 - r * r;
      let a = Math.sqrt(as);
      const bs = (h - k) ** 2;
      const c = (4 - hk) / 8;
      const d = (12 - hk) / 80;
      let asr = -(bs / as + hk) / 2;
      if (asr > -100) bvn = a * Math.exp(asr) * (1 - (c * (bs - as) * (1 - d * bs)) / 3 + c * d * as * as);
      if (hk > -100) {
        const b = Math.sqrt(bs);
        const sp = Math.sqrt(tp) * phi(-b / a);
        bvn -= Math.exp(-hk / 2) * sp * b * (1 - (c * bs * (1 - d * bs)) / 3);
      }
      a /= 2;
      let sum = 0;
      for (let i = 0; i < X.length; i++) {
        const xs = (a * X[i]) ** 2;
        asr = -(bs / xs + hk) / 2;
        if (asr <= -100) continue;
        const sp = 1 + c * xs * (1 + 5 * d * xs);
        const rs = Math.sqrt(1 - xs);
        const ep = Math.exp((-(hk / 2) * xs) / (1 + rs) ** 2) / rs;
        sum += W[i] * Math.exp(asr) * (sp - ep);
      }
      bvn = (a * sum - bvn) / tp;
    }
    if (r > 0) bvn += phi(-Math.max(h, k));
    else if (h >= k) bvn = -bvn;
    else {
      const L = h < 0 ? phi(k) - phi(h) : phi(-h) - phi(-k);
      bvn = L - bvn;
    }
  }
  return Math.max(0, Math.min(1, bvn));
}

// ------------------------------------------------------------------------------------------------- matrices
/** Jacobi eigen-decomposition of a small symmetric matrix. */
function eigSym(A: number[][]): { values: number[]; vectors: number[][] } {
  const n = A.length;
  const a = A.map((r) => [...r]);
  const v: number[][] = Array.from({ length: n }, (_, i) => Array.from({ length: n }, (_, j) => (i === j ? 1 : 0)));
  for (let sweep = 0; sweep < 100; sweep++) {
    let off = 0;
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) off += a[i][j] ** 2;
    if (off < 1e-22) break;
    for (let p = 0; p < n; p++) {
      for (let q = p + 1; q < n; q++) {
        if (Math.abs(a[p][q]) < 1e-300) continue;
        const theta = (a[q][q] - a[p][p]) / (2 * a[p][q]);
        const t = Math.sign(theta || 1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1));
        const c = 1 / Math.sqrt(t * t + 1);
        const s = t * c;
        for (let k = 0; k < n; k++) {
          const akp = a[k][p], akq = a[k][q];
          a[k][p] = c * akp - s * akq;
          a[k][q] = s * akp + c * akq;
        }
        for (let k = 0; k < n; k++) {
          const apk = a[p][k], aqk = a[q][k];
          a[p][k] = c * apk - s * aqk;
          a[q][k] = s * apk + c * aqk;
        }
        for (let k = 0; k < n; k++) {
          const vkp = v[k][p], vkq = v[k][q];
          v[k][p] = c * vkp - s * vkq;
          v[k][q] = s * vkp + c * vkq;
        }
      }
    }
  }
  return { values: a.map((r, i) => r[i]), vectors: v };
}

/** Nearest valid correlation matrix by eigenvalue clipping (pooled pairwise coefficients need not be jointly valid). */
export function nearestCorr(R: number[][]): number[][] {
  const n = R.length;
  const S = R.map((r, i) => r.map((x, j) => (x + R[j][i]) / 2));
  const { values, vectors } = eigSym(S);
  if (Math.min(...values) >= 1e-8) return S;
  const w = values.map((x) => Math.max(x, 1e-6));
  const M = Array.from({ length: n }, (_, i) => Array.from({ length: n }, (_, j) => {
    let s = 0;
    for (let k = 0; k < n; k++) s += vectors[i][k] * w[k] * vectors[j][k];
    return s;
  }));
  return M.map((r, i) => r.map((x, j) => x / Math.sqrt(M[i][i] * M[j][j])));
}

export function cholesky(R: number[][]): number[][] {
  const n = R.length;
  const L = Array.from({ length: n }, () => new Array<number>(n).fill(0));
  for (let i = 0; i < n; i++) {
    for (let j = 0; j <= i; j++) {
      let s = R[i][j];
      for (let k = 0; k < j; k++) s -= L[i][k] * L[j][k];
      L[i][j] = i === j ? Math.sqrt(Math.max(s, 1e-12)) : s / L[j][j];
    }
  }
  return L;
}

/** Small, fast, seeded PRNG (mulberry32). */
export function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ------------------------------------------------------------------------------------------------- joint
/** Per variable, the interval of latent values that satisfies every leg on it. */
export function intervals(legs: JointLeg[]): Map<number, [number, number]> {
  const m = new Map<number, [number, number]>();
  for (const l of legs) {
    const t = invPhi(1 - l.p);
    const cur = m.get(l.variable) ?? [-Infinity, Infinity];
    if (l.side > 0) cur[0] = Math.max(cur[0], t);
    else cur[1] = Math.min(cur[1], -t);
    m.set(l.variable, cur);
  }
  return m;
}

export function joint(legs: JointLeg[], R: number[][], sims = 20_000, seed = 20261127): JointResult {
  if (legs.some((l) => l.p <= 0)) return { p: 0, se: 0, method: "exact" };
  const live = legs.filter((l) => l.p < 1);
  if (!live.length) return { p: 1, se: 0, method: "exact" };
  const iv = intervals(live);
  const vars = [...iv.keys()].sort((a, b) => a - b);
  const L = vars.map((v) => iv.get(v)![0]);
  const H = vars.map((v) => iv.get(v)![1]);
  if (L.some((x, i) => x >= H[i])) return { p: 0, se: 0, method: "exact" };
  if (vars.length === 1) return { p: Math.max(0, phi(H[0]) - phi(L[0])), se: 0, method: "exact" };
  const sub = vars.map((i) => vars.map((j) => R[i][j]));
  const oneSided = vars.every((_, i) => (L[i] === -Infinity) !== (H[i] === Infinity));
  if (vars.length === 2 && oneSided) {
    const s = [0, 1].map((i) => (L[i] > -Infinity ? 1 : -1));
    const t = [0, 1].map((i) => (s[i] > 0 ? L[i] : -H[i]));
    return { p: bvnu(t[0], t[1], s[0] * s[1] * sub[0][1]), se: 0, method: "exact" };
  }
  return genz(L, H, nearestCorr(sub), sims, seed);
}

/**
 * P(L < Z < H) for Z ~ N(0, R): Genz's separation-of-variables estimator (much lower variance than counting hits).
 * Variables go narrowest interval first. Seeded uniforms, so the same input always gives the same number.
 */
export function genz(L0: number[], H0: number[], R0: number[][], sims = 20_000, seed = 20261127): JointResult {
  const n = L0.length;
  const order = L0.map((_, i) => i).sort((a, b) => (phi(H0[a]) - phi(L0[a])) - (phi(H0[b]) - phi(L0[b])));
  const L = order.map((i) => L0[i]);
  const H = order.map((i) => H0[i]);
  const C = cholesky(order.map((i) => order.map((j) => R0[i][j])));
  const u = rng(seed);
  const y = new Float64Array(n);
  const d0 = phi(L[0] / C[0][0]);
  const e0 = phi(H[0] / C[0][0]);
  let sum = 0;
  let sum2 = 0;
  for (let s = 0; s < sims; s++) {
    let d = d0, e = e0, f = e0 - d0;
    for (let i = 1; i < n && f > 0; i++) {
      const q = Math.min(Math.max(d + u() * (e - d), 1e-15), 1 - 1e-15);
      y[i - 1] = invPhi(q);
      let t = 0;
      for (let k = 0; k < i; k++) t += C[i][k] * y[k];
      d = phi((L[i] - t) / C[i][i]);
      e = phi((H[i] - t) / C[i][i]);
      f *= e - d;
    }
    sum += f;
    sum2 += f * f;
  }
  const p = sum / sims;
  const v = Math.max(sum2 / sims - p * p, 0) * (sims / (sims - 1));
  return { p: Math.max(0, Math.min(1, p)), se: Math.sqrt(v / sims), method: `genz_${sims}` };
}

/** Bounds on P(all legs) that hold whatever the dependence (Fréchet). */
export function frechet(ps: number[]): [number, number] {
  return [Math.max(0, ps.reduce((a, b) => a + b, 0) - (ps.length - 1)), Math.min(...ps)];
}

// ------------------------------------------------------------------------------------------------- odds
export function fairAmerican(p: number): number | null {
  if (!(p > 0 && p < 1)) return null;
  return p >= 0.5 ? Math.round((-100 * p) / (1 - p)) : Math.round((100 * (1 - p)) / p);
}
export const americanToDecimal = (a: number) => (a > 0 ? 1 + a / 100 : 1 + 100 / -a);
export function decimalToAmerican(d: number): number | null {
  if (!(d > 1)) return null;
  return d >= 2 ? Math.round((d - 1) * 100) : Math.round(-100 / (d - 1));
}
export const impliedFromAmerican = (a: number) => 1 / americanToDecimal(a);
