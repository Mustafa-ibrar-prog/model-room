"use client";

/**
 * Per-viewer conveniences kept in this browser only: favorite players and recently viewed contracts.
 * Storage can be unavailable (private mode, blocked site data), so every access is guarded and the page
 * works without it.
 */
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

const FAV = "mr:favorites:v1";
const RECENT = "mr:recent:v1";
const EVT = "mr:local-change";

function read<T>(key: string, fallback: T): T {
  try {
    const v = window.localStorage.getItem(key);
    return v ? (JSON.parse(v) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // storage unavailable: the change just isn't remembered
  }
  window.dispatchEvent(new Event(EVT));
}

function useStored<T>(key: string, fallback: T): T {
  const [v, setV] = useState<T>(fallback);
  useEffect(() => {
    const load = () => setV(read(key, fallback));
    load();
    window.addEventListener(EVT, load);
    window.addEventListener("storage", load);
    return () => {
      window.removeEventListener(EVT, load);
      window.removeEventListener("storage", load);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return v;
}

/** Star toggle for a player ("nfl:<id>"). */
export function FavoriteStar({ id, name }: { id: string; name: string }) {
  const favs = useStored<string[]>(FAV, []);
  const on = favs.includes(id);
  const toggle = useCallback(() => {
    const cur = read<string[]>(FAV, []);
    write(FAV, cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id].slice(-200));
  }, [id]);
  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={on}
      aria-label={on ? `Remove ${name} from favorites` : `Add ${name} to favorites`}
      className={`shrink-0 rounded p-0.5 text-base leading-none ${on ? "text-edge" : "text-faint hover:text-mute"}`}
    >
      {on ? "★" : "☆"}
    </button>
  );
}

/** "Favorites only" switch: hides rows (data-fav-id) that aren't starred. */
export function FavoritesScope({ children }: { children: ReactNode }) {
  const favs = useStored<string[]>(FAV, []);
  const [only, setOnly] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const rows = ref.current?.querySelectorAll<HTMLElement>("[data-fav-id]") ?? [];
    let shown = 0;
    rows.forEach((r) => {
      const hide = only && !favs.includes(r.dataset.favId ?? "");
      r.hidden = hide;
      if (!hide) shown++;
    });
    const empty = ref.current?.querySelector<HTMLElement>("[data-fav-empty]");
    if (empty) empty.hidden = !(only && shown === 0);
  }, [only, favs, children]);
  return (
    <div ref={ref}>
      <label className="mb-2 inline-flex cursor-pointer items-center gap-2 text-sm text-mute">
        <input type="checkbox" checked={only} onChange={(e) => setOnly(e.target.checked)} className="accent-[var(--mr-edge)]" />
        Favorites only {favs.length ? <span className="text-faint">({favs.length})</span> : null}
      </label>
      {children}
      <p data-fav-empty hidden className="px-1 py-6 text-center text-sm text-mute">
        No favorites in this list. Star a player to keep them here; favorites stay in this browser.
      </p>
    </div>
  );
}

export interface RecentItem {
  href: string;
  label: string;
  sub: string;
}

/** Records the open contract in the recently-viewed list. Renders nothing. */
export function TrackView({ item }: { item: RecentItem }) {
  useEffect(() => {
    const cur = read<RecentItem[]>(RECENT, []).filter((x) => x.href !== item.href);
    write(RECENT, [item, ...cur].slice(0, 8));
  }, [item]);
  return null;
}

export function RecentlyViewed() {
  const items = useStored<RecentItem[]>(RECENT, []);
  if (!items.length) return <p className="px-2 text-xs text-faint">Contracts you open appear here.</p>;
  return (
    <ul className="space-y-0.5">
      {items.map((x) => (
        <li key={x.href}>
          <Link href={x.href} scroll={false} className="block rounded-md px-2 py-1.5 hover:bg-navy-800">
            <span className="block truncate text-sm text-ink">{x.label}</span>
            <span className="block truncate text-[0.7rem] text-faint">{x.sub}</span>
          </Link>
        </li>
      ))}
      <li>
        <button type="button" onClick={() => write(RECENT, [])} className="px-2 pt-1 text-[0.7rem] text-faint hover:text-mute">Clear</button>
      </li>
    </ul>
  );
}
