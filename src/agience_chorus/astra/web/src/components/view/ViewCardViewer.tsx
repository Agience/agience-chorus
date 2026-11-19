import { useEffect, useMemo, useState } from 'react';
import type { Artifact } from '@/context/workspace/workspace.types';
import { artifactTitle } from '@/utils/artifactContext';
import { getContentType, type ViewMode } from '@/registry/content-types';
import { runSavedView } from '@/api/savedViews';

interface ViewCardViewerProps {
	artifact: Artifact;
	mode?: ViewMode;
	onOpenCollection?: (collectionId: string) => void;
}

/**
 * A saved view: Crystal runs it and names the collection it views; this shows that and offers to
 * open the collection.
 */
export function ViewCardViewer({ artifact, mode = 'floating', onOpenCollection }: ViewCardViewerProps) {
	const contentType = useMemo(() => getContentType(artifact), [artifact]);
	const [targetId, setTargetId] = useState<string | null>(null);
	const [failed, setFailed] = useState(false);

	useEffect(() => {
		let live = true;
		setTargetId(null);
		setFailed(false);
		runSavedView(String(artifact.id))
			.then(r => { if (live) setTargetId(r.target_id || null); })
			.catch(() => { if (live) setFailed(true); });
		return () => { live = false; };
	}, [artifact.id]);

	const title = artifactTitle(artifact) || contentType.label || 'View';

	return (
		<div className="h-full w-full flex flex-col bg-white">
			<div className="px-4 py-2 border-b flex items-center justify-between">
				<div className="flex items-center gap-2 min-w-0">
					<contentType.icon size={16} />
					<div className="text-sm font-semibold text-gray-900 truncate" title={title}>
						{title}
					</div>
				</div>
				<div className="text-xs text-gray-500 capitalize ml-4 flex-shrink-0">{mode}</div>
			</div>

			<div className="flex-1 flex flex-col items-center justify-center px-6 py-4 text-center text-sm text-gray-600">
				{targetId ? (
					<button
						type="button"
						className="inline-flex items-center px-3 py-1.5 rounded border border-teal-500 text-teal-700 text-xs font-medium hover:bg-teal-50 transition-colors"
						onClick={() => onOpenCollection?.(targetId)}
					>
						Open the collection this view shows
					</button>
				) : (
					<p className="text-xs text-gray-500">
						{failed ? 'This view names nothing you can open.' : 'Loading…'}
					</p>
				)}
			</div>
		</div>
	);
}

export default ViewCardViewer;
