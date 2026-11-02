import { getViewer, isTierPreviewEnabled } from "@/server/viewer";
import { TierPreviewButtons } from "./TierPreviewButtons";

/** Dev-only plan switcher. Renders nothing unless ENABLE_TIER_PREVIEW=true. */
export async function TierPreview() {
  if (!isTierPreviewEnabled()) return null;
  const viewer = await getViewer();
  return (
    <div className="border-t border-navy-700/70">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-4 text-sm sm:px-6">
        <span className="text-mute">Developer preview. View the site as:</span>
        <TierPreviewButtons current={viewer.tier} />
      </div>
    </div>
  );
}
