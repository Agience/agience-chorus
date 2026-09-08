import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { RecordedRequest } from './requestRecorder';
import { recordRequests } from './requestRecorder';

vi.mock('../../config/runtime', () => ({
	getRuntimeConfig: () => ({
		mantleUri: 'https://api.example.com',
		originUri: 'https://origin.example.com',
		crystalUri: 'https://crystal.example.com',
		clientId: '',
		title: 'Agience',
		favicon: '/favicon.png',
	}),
}));

// Import postForm after mocking runtime config so it picks up the stub URI
import api, { postForm, postList, onMantle, onOrigin } from '../api';

const MANTLE = 'https://api.example.com';
const ORIGIN = 'https://origin.example.com';
const CRYSTAL = 'https://crystal.example.com';

describe('api/postForm', () => {
	afterEach(() => {
		vi.restoreAllMocks();
		vi.unstubAllGlobals();
	});

	it('submits /auth/token to ORIGIN_URI (Origin owns identity)', async () => {
		const fetchMock = vi.fn().mockResolvedValue({
			ok: true,
			json: vi.fn().mockResolvedValue({ token: 'abc' }),
		});
		vi.stubGlobal('fetch', fetchMock);

		const form = new URLSearchParams({ code: '123' });
		const result = await postForm('/auth/token', form);

		expect(fetchMock).toHaveBeenCalledWith('https://origin.example.com/auth/token', {
			method: 'POST',
			headers: {
				'Content-Type': 'application/x-www-form-urlencoded',
			},
			body: form,
		});
		expect(result).toEqual({ token: 'abc' });
	});

	it('submits the /auth/authorizer/* carve-out to ORIGIN_URI', async () => {
		const fetchMock = vi.fn().mockResolvedValue({
			ok: true,
			json: vi.fn().mockResolvedValue({}),
		});
		vi.stubGlobal('fetch', fetchMock);

		await postForm('/auth/authorizer/complete-oauth', new URLSearchParams());
		expect(fetchMock).toHaveBeenLastCalledWith(
			'https://api.example.com/auth/authorizer/complete-oauth',
			expect.any(Object),
		);
	});

	it('submits /auth/passkey/* to ORIGIN_URI (moved in 1.1b)', async () => {
		const fetchMock = vi.fn().mockResolvedValue({
			ok: true,
			json: vi.fn().mockResolvedValue({}),
		});
		vi.stubGlobal('fetch', fetchMock);

		await postForm('/auth/passkey/login-options', new URLSearchParams());
		expect(fetchMock).toHaveBeenLastCalledWith(
			'https://origin.example.com/auth/passkey/login-options',
			expect.any(Object),
		);
	});

	it('throws when the backend returns a non-ok response', async () => {
		const fetchMock = vi.fn().mockResolvedValue({
			ok: false,
			json: vi.fn().mockResolvedValue({ detail: 'invalid' }),
		});
		vi.stubGlobal('fetch', fetchMock);

		const form = new URLSearchParams();

		await expect(postForm('/auth/token', form)).rejects.toThrow('invalid');
	});
});

// Which service answers a call is a wire contract, so it is pinned here rather
// than left to whoever next edits the interceptor. The adapter is stubbed and
// the real instance is used, so these assert the baseURL a request actually
// leaves with — interceptor included.
describe('api request routing', () => {
	let seen: RecordedRequest[] = [];
	let restore = () => {};

	beforeEach(() => {
		({ requests: seen, restore } = recordRequests(() => ({})));
	});

	afterEach(() => restore());

	it('sends /auth/* to Origin and the /auth/authorizer/* carve-out to Mantle', async () => {
		await api.get('/auth/userinfo');
		await api.get('/auth/authorizer/status');
		expect(seen.map(c => c.baseURL)).toEqual([ORIGIN, MANTLE]);
	});

	it('sends /setup/* and /server-credentials to Origin', async () => {
		await api.get('/setup/status');
		await api.get('/server-credentials');
		expect(seen.map(c => c.baseURL)).toEqual([ORIGIN, ORIGIN]);
	});

	it('dispatches artifact ops to Crystal and leaves plain CRUD on Mantle', async () => {
		await api.post('/artifacts/abc/op/summarize');
		await api.get('/artifacts/abc');
		expect(seen.map(c => c.baseURL)).toEqual([CRYSTAL, MANTLE]);
	});

	// The load-bearing one: Origin and Mantle both serve `/system/*`, so nothing
	// about the path may pick between them. A rule that reads `/system` — in
	// either direction — sends half this surface to the wrong service.
	it('never infers a service from a /system path', async () => {
		await api.get('/system/settings');
		await api.get('/system/users');
		await api.get('/system');
		expect(seen.map(c => c.baseURL)).toEqual([MANTLE, MANTLE, MANTLE]);
	});

	it('routes a /system call to the service its call site names', async () => {
		await api.get('/system/settings', onOrigin);
		await api.get('/system/users', onMantle);
		expect(seen.map(c => c.baseURL)).toEqual([ORIGIN, MANTLE]);
	});
});

describe('api/postList', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// ⛔ WHY THIS EXISTS. `/artifacts/batch` used to answer `{ artifacts: [...] }` and moved to the
	// `{ items, total, has_more }` page shape. Two callers still read `res.artifacts`, so the read
	// returned `undefined` and their `?? []` turned it into an empty list -- global search across
	// collections and workspaces silently found nothing, with no error anywhere. `postList` owns the
	// unwrapping now, so there is one place for it to be right.

	it('unwraps the { items } envelope', async () => {
		vi.spyOn(api, 'post').mockResolvedValue({
			data: { items: [{ id: 'a' }, { id: 'b' }], total: 2, has_more: false },
		} as never);
		await expect(postList('/artifacts/batch', { artifact_ids: ['a', 'b'] })).resolves.toEqual([
			{ id: 'a' },
			{ id: 'b' },
		]);
	});

	it('still accepts a bare array, for an older node or a mixed fleet', async () => {
		vi.spyOn(api, 'post').mockResolvedValue({ data: [{ id: 'a' }] } as never);
		await expect(postList('/artifacts/batch', {})).resolves.toEqual([{ id: 'a' }]);
	});

	it('returns [] rather than undefined when the envelope carries no rows', async () => {
		vi.spyOn(api, 'post').mockResolvedValue({ data: { items: [], total: 0, has_more: false } } as never);
		await expect(postList('/artifacts/batch', {})).resolves.toEqual([]);
	});

	it('returns [] when the body has neither shape, instead of throwing', async () => {
		// A caller mid-rollout must not crash on a response it does not recognise -- but it must
		// also not receive `undefined`, which is what started this.
		vi.spyOn(api, 'post').mockResolvedValue({ data: { unexpected: true } } as never);
		await expect(postList('/artifacts/batch', {})).resolves.toEqual([]);
	});
});
