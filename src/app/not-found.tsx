import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-24 sm:px-6">
      <h1 className="font-display text-5xl font-700 text-ink">Page not found</h1>
      <p className="mt-3 max-w-md text-mute">That address does not match any board. Try the NFL or NBA projections.</p>
      <div className="mt-6 flex gap-3">
        <Link href="/nfl" className="rounded-full bg-model px-5 py-2.5 font-600 text-navy-950">Open the NFL board</Link>
        <Link href="/" className="rounded-full border border-navy-600 px-5 py-2.5 font-600 text-ink">Go home</Link>
      </div>
    </div>
  );
}
