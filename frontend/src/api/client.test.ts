import { describe, expect, it, vi } from 'vitest';
import createClient from 'openapi-fetch';
import type { components, paths } from './types';

describe('api client types', () => {
  it('GET /api/verify/queue is typed and hits the right URL', async () => {
    const page: components['schemas']['QueuePage'] = {
      items: [],
      total: 0,
      counts: { pending: 0, auto_approved: 0, approved: 0, edited: 0, flagged_open: 0, skipped: 0, in_scope: 0 },
      docs: [],
      cursor: { sort: 'worst_first', view_threshold: null, doc_filter: null, current_block_id: null, trail: [] },
    };
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(page), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }));
    const client = createClient<paths>({ baseUrl: 'http://x', fetch: fetchMock as unknown as typeof fetch });
    const { data } = await client.GET('/api/verify/queue', { params: { query: { limit: 5 } } });
    expect(data?.total).toBe(0);
    const req = (fetchMock.mock.calls[0] as unknown as [Request])[0];
    expect(req.url).toBe('http://x/api/verify/queue?limit=5');
  });
});
