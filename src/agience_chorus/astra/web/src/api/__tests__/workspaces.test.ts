import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api', () => ({
	get: vi.fn(),
	getList: vi.fn(),
	LIST_PAGE: 500,
	post: vi.fn(),
	patch: vi.fn(),
	del: vi.fn(),
	put: vi.fn(),
}));

import { get, getList } from '../api';
import { listWorkspaceArtifacts } from '../workspaces';

const mockedGet = get as unknown as ReturnType<typeof vi.fn>;
const mockedGetList = getList as unknown as ReturnType<typeof vi.fn>;

describe('api/workspaces (TypeScript helpers)', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it('returns items envelope from API', async () => {
		mockedGet.mockResolvedValueOnce({
			items: [
				{ id: 'c1', content: 'Artifact 1', state: 'live', context: '{}', collection_ids: [] },
			],
			order_version: 3,
		});

		const result = await listWorkspaceArtifacts('ws-1');

		expect(result).toEqual({
			items: [
				expect.objectContaining({ id: 'c1' }),
			],
			order_version: 3,
		});
	});

	it('follows has_more past the first page, keeping order_version and each item once', async () => {
		mockedGet.mockResolvedValueOnce({
			items: [{ id: 'c1' }, { id: 'c2' }], order_version: 7, has_more: true,
		});
		mockedGetList.mockResolvedValueOnce([{ id: 'c2' }, { id: 'c3' }]);

		const result = await listWorkspaceArtifacts('ws-1');

		expect(mockedGetList).toHaveBeenCalledWith('/artifacts/ws-1/children', { params: { offset: 2 } });
		expect(result.order_version).toBe(7);
		expect(result.items.map((a) => a.id)).toEqual(['c1', 'c2', 'c3']);
	});
});
