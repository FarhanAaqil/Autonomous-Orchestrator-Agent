import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, dispatch, parseEvent, request, setSession } from './api';
afterEach(() => vi.unstubAllGlobals());
describe('browser transport', () => {
  it('keeps CSRF in a header and uses same-origin cookies', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('{}'));
    vi.stubGlobal('fetch', fetcher);
    setSession({user: {id: 'u', username: 'test', role: 'operator'}, csrf_token: 'private-csrf'});
    await request('/jobs', 'POST', {goal: 'hello'});
    expect(fetcher.mock.calls[0][0]).toBe('/jobs');
    expect(fetcher.mock.calls[0][1].credentials).toBe('same-origin');
    expect(fetcher.mock.calls[0][1].headers['X-CSRF-Token']).toBe('private-csrf');
  });
  it('does not turn schedule validation errors into chat clarifications', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"detail":[{"msg":"Invalid cron"}]}', {status: 422})));
    await expect(request('/schedules', 'POST', {})).rejects.toBeInstanceOf(ApiError);
  });
  it('parses named events and ignores heartbeat comments', () => {
    expect(parseEvent(': ping')).toBeNull();
    expect(parseEvent('event: token\ndata: {"token":"hello"}')).toEqual({event:'token',data:{token:'hello'}});
  });
  it('handles events split across transport chunks', async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({start(controller) {
      for (const chunk of ['event: tok', 'en\ndata: {"token":"hello"}\n', '\nevent: done\ndata: {}\n\n']) controller.enqueue(encoder.encode(chunk));
      controller.close();
    }});
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(stream)));
    const seen: string[] = [];
    await dispatch('hello', 'conversation', event => seen.push(event), new AbortController().signal);
    expect(seen).toEqual(['token', 'done']);
  });
  it('reports interrupted output without a completion event', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('event: token\ndata: {"token":"partial"}\n\n')));
    await expect(dispatch('hello', null, () => {}, new AbortController().signal)).rejects.toThrow('before completion');
  });
});
