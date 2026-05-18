import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  bindEventSourceListeners,
  createEventSource,
  DEFAULT_SSE_REFRESH_EVENT_NAMES,
  resolveSseUrl,
} from './sse';

const createMockReadableBody = (chunks) => ({
  getReader() {
    let index = 0;
    return {
      async read() {
        if (index >= chunks.length) {
          return { value: undefined, done: true };
        }
        const value = chunks[index];
        index += 1;
        return { value, done: false };
      },
    };
  },
});

const createAbortError = () => Object.assign(new Error('Aborted'), { name: 'AbortError' });

const createAbortableIdleResponse = (signal) => ({
  ok: true,
  status: 200,
  body: {
    getReader() {
      return {
        read() {
          return new Promise((resolve, reject) => {
            if (signal.aborted) {
              reject(createAbortError());
              return;
            }
            signal.addEventListener(
              'abort',
              () => {
                reject(createAbortError());
              },
              { once: true },
            );
          });
        },
      };
    },
  },
});

const flushQueuedReconnects = async (cycles = 3) => {
  for (let index = 0; index < cycles; index += 1) {
    await Promise.resolve();
  }
};

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe('resolveSseUrl', () => {
  it('resolves relative SSE paths against an explicit base URL', () => {
    expect(resolveSseUrl('/sse/messages', 'http://127.0.0.1:5173')).toBe(
      'http://127.0.0.1:5173/sse/messages'
    );
  });

  it('keeps absolute SSE endpoints intact', () => {
    expect(resolveSseUrl('http://127.0.0.1:8010/sse', 'http://127.0.0.1:5173')).toBe(
      'http://127.0.0.1:8010/sse'
    );
  });

  it('keeps same-origin path prefixes from configured API bases when resolving default SSE path', () => {
    vi.stubEnv('VITE_API_BASE_URL', '/memory-palace/api/');

    expect(resolveSseUrl('/sse', 'http://127.0.0.1:5173')).toBe(
      'http://127.0.0.1:5173/memory-palace/sse'
    );
  });

  it('uses the configured cross-origin API base for relative SSE paths', () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.test/memory-palace/api/');

    expect(resolveSseUrl('/sse', 'http://127.0.0.1:5173')).toBe(
      'https://api.example.test/memory-palace/sse'
    );
  });
});

describe('createEventSource', () => {
  it('creates an EventSource instance with resolved URL and credentials option', () => {
    const factory = vi.fn((url, init) => ({ url, init }));

    const client = createEventSource('/sse', {
      baseUrl: 'http://127.0.0.1:5173',
      withCredentials: true,
      EventSourceImpl: factory,
    });

    expect(factory).toHaveBeenCalledWith('http://127.0.0.1:5173/sse', {
      withCredentials: true,
    });
    expect(client).toEqual({
      url: 'http://127.0.0.1:5173/sse',
      init: { withCredentials: true },
    });
  });

  it('fails closed when EventSource is unavailable', () => {
    expect(() => createEventSource('/sse', { EventSourceImpl: undefined })).toThrow(
      'EventSource is not available in this environment.'
    );
  });

  it('uses fetch streaming with auth headers when maintenance auth is provided', async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(
          encoder.encode('event: endpoint\ndata: /messages?session_id=auth-stream\n\n')
        );
        controller.close();
      },
    });
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      body: stream,
      status: 200,
    }));

    const client = createEventSource('/sse', {
      auth: { key: 'secret-token', mode: 'header' },
      baseUrl: 'http://127.0.0.1:5173',
      fetchImpl,
      EventSourceImpl: vi.fn(() => {
        throw new Error('native EventSource should not be used');
      }),
    });
    const listener = vi.fn();
    const openListener = vi.fn();
    client.addEventListener('open', openListener);
    client.addEventListener('endpoint', listener);

    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(fetchImpl).toHaveBeenCalledWith(
      'http://127.0.0.1:5173/sse',
      expect.objectContaining({
        method: 'GET',
        headers: { 'X-MCP-API-Key': 'secret-token' },
      })
    );
    expect(openListener).toHaveBeenCalledWith(expect.objectContaining({ type: 'open' }));
    expect(listener).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'endpoint',
        data: '/messages?session_id=auth-stream',
      })
    );
  });

  it('uses bearer auth when the SSE client is configured for bearer mode', async () => {
    const stream = new ReadableStream({
      start(controller) {
        controller.close();
      },
    });
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      body: stream,
      status: 200,
    }));

    createEventSource('/sse', {
      auth: { key: 'secret-token', mode: 'bearer' },
      baseUrl: 'http://127.0.0.1:5173',
      fetchImpl,
    });

    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(fetchImpl).toHaveBeenCalledWith(
      'http://127.0.0.1:5173/sse',
      expect.objectContaining({
        headers: { Authorization: 'Bearer secret-token' },
      })
    );
  });

  it('reconnects after an authenticated SSE stream ends unexpectedly', async () => {
    const encoder = new TextEncoder();
    let callCount = 0;
    const fetchImpl = vi.fn(async () => {
      callCount += 1;
      return {
        ok: true,
        body: createMockReadableBody([
          encoder.encode(
            `event: endpoint\ndata: /messages?session_id=reconnect-${callCount}\n\n`
          ),
        ]),
        status: 200,
      };
    });

    const client = createEventSource('/sse', {
      auth: { key: 'secret-token', mode: 'header' },
      baseUrl: 'http://127.0.0.1:5173',
      fetchImpl,
      retryDelayMs: 1,
    });
    const listener = vi.fn();
    await new Promise((resolve) => {
      client.addEventListener('endpoint', (event) => {
        listener(event);
        if (listener.mock.calls.length >= 2) {
          client.close();
          resolve();
        }
      });
    });

    expect(fetchImpl.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(listener).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        data: '/messages?session_id=reconnect-2',
      })
    );
  });

  it('reuses the most recent SSE event id as Last-Event-ID on authenticated reconnects', async () => {
    const encoder = new TextEncoder();
    let callCount = 0;
    const fetchImpl = vi.fn(async () => {
      callCount += 1;
      return {
        ok: true,
        body: createMockReadableBody([
          encoder.encode(
            `id: endpoint-${callCount}\nevent: endpoint\ndata: /messages?session_id=reconnect-${callCount}\n\n`
          ),
        ]),
        status: 200,
      };
    });

    const client = createEventSource('/sse', {
      auth: { key: 'secret-token', mode: 'header' },
      baseUrl: 'http://127.0.0.1:5173',
      fetchImpl,
      retryDelayMs: 1,
    });

    await new Promise((resolve) => {
      let seen = 0;
      client.addEventListener('endpoint', (event) => {
        seen += 1;
        if (seen >= 2) {
          expect(event).toEqual(
            expect.objectContaining({
              lastEventId: 'endpoint-2',
            })
          );
          client.close();
          resolve();
        }
      });
    });

    expect(fetchImpl).toHaveBeenNthCalledWith(
      2,
      'http://127.0.0.1:5173/sse',
      expect.objectContaining({
        headers: {
          'X-MCP-API-Key': 'secret-token',
          'Last-Event-ID': 'endpoint-1',
        },
      })
    );
  });

  it('refreshes authenticated reconnect headers from current auth state instead of the initial snapshot', async () => {
    const encoder = new TextEncoder();
    let callCount = 0;
    let currentAuth = { key: 'initial-secret', mode: 'header' };
    const fetchImpl = vi.fn(async () => {
      callCount += 1;
      return {
        ok: true,
        body: createMockReadableBody([
          encoder.encode(
            `id: endpoint-${callCount}\nevent: endpoint\ndata: /messages?session_id=refresh-${callCount}\n\n`
          ),
        ]),
        status: 200,
      };
    });

    const client = createEventSource('/sse', {
      auth: { key: 'initial-secret', mode: 'header' },
      baseUrl: 'http://127.0.0.1:5173',
      fetchImpl,
      resolveAuth: () => currentAuth,
      retryDelayMs: 1,
    });

    await new Promise((resolve) => {
      let seen = 0;
      client.addEventListener('endpoint', () => {
        seen += 1;
        if (seen === 1) {
          currentAuth = { key: 'rotated-secret', mode: 'header' };
        }
        if (seen >= 2) {
          client.close();
          resolve();
        }
      });
    });

    expect(fetchImpl).toHaveBeenNthCalledWith(
      2,
      'http://127.0.0.1:5173/sse',
      expect.objectContaining({
        headers: {
          'X-MCP-API-Key': 'rotated-secret',
          'Last-Event-ID': 'endpoint-1',
        },
      })
    );
  });

  it('uses exponential backoff instead of a fixed retry interval for repeated authenticated SSE reconnects', async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      body: createMockReadableBody([]),
      status: 200,
    }));

    const client = createEventSource('/sse', {
      auth: { key: 'secret-token', mode: 'header' },
      baseUrl: 'http://127.0.0.1:5173',
      fetchImpl,
      retryDelayMs: 100,
      maxRetryDelayMs: 400,
      retryBackoffFactor: 2,
      retryJitterRatio: 0,
    });

    await flushQueuedReconnects();
    expect(fetchImpl).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(99);
    expect(fetchImpl).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(1);
    expect(fetchImpl).toHaveBeenCalledTimes(2);

    await vi.advanceTimersByTimeAsync(199);
    expect(fetchImpl).toHaveBeenCalledTimes(2);

    await vi.advanceTimersByTimeAsync(1);
    expect(fetchImpl).toHaveBeenCalledTimes(3);

    await vi.advanceTimersByTimeAsync(399);
    expect(fetchImpl).toHaveBeenCalledTimes(3);

    await vi.advanceTimersByTimeAsync(1);
    expect(fetchImpl).toHaveBeenCalledTimes(4);

    client.close();
  });

  it('tears down authenticated SSE on page hide and reconnects once the page becomes visible again', async () => {
    vi.useFakeTimers();
    let hidden = false;
    const originalHidden = Object.getOwnPropertyDescriptor(document, 'hidden');
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      get: () => hidden,
    });

    const fetchImpl = vi.fn(async (_url, init) => createAbortableIdleResponse(init.signal));

    try {
      const client = createEventSource('/sse', {
        auth: { key: 'secret-token', mode: 'header' },
        baseUrl: 'http://127.0.0.1:5173',
        fetchImpl,
        retryDelayMs: 20,
        retryBackoffFactor: 1,
        retryJitterRatio: 0,
        idleTimeoutMs: 1_000,
      });

      await flushQueuedReconnects();
      expect(fetchImpl).toHaveBeenCalledTimes(1);

      hidden = true;
      document.dispatchEvent(new Event('visibilitychange'));
      window.dispatchEvent(new Event('pagehide'));

      await vi.advanceTimersByTimeAsync(100);
      expect(fetchImpl).toHaveBeenCalledTimes(1);

      hidden = false;
      window.dispatchEvent(new Event('pageshow'));
      document.dispatchEvent(new Event('visibilitychange'));

      await flushQueuedReconnects();
      expect(fetchImpl).toHaveBeenCalledTimes(2);

      client.close();
    } finally {
      if (originalHidden) {
        Object.defineProperty(document, 'hidden', originalHidden);
      } else {
        delete document.hidden;
      }
    }
  });

  it('cancels pending authenticated SSE reconnects while the page is unloading', async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      body: createMockReadableBody([]),
      status: 200,
    }));

    const client = createEventSource('/sse', {
      auth: { key: 'secret-token', mode: 'header' },
      baseUrl: 'http://127.0.0.1:5173',
      fetchImpl,
      retryDelayMs: 100,
      retryBackoffFactor: 1,
      retryJitterRatio: 0,
    });

    await flushQueuedReconnects();
    expect(fetchImpl).toHaveBeenCalledTimes(1);

    window.dispatchEvent(new Event('beforeunload'));
    await vi.advanceTimersByTimeAsync(500);

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    client.close();
  });

  it('retries authenticated SSE streams that go idle for too long', async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn(async (_url, init) => createAbortableIdleResponse(init.signal));

    const client = createEventSource('/sse', {
      auth: { key: 'secret-token', mode: 'header' },
      baseUrl: 'http://127.0.0.1:5173',
      fetchImpl,
      retryDelayMs: 10,
      retryBackoffFactor: 1,
      retryJitterRatio: 0,
      idleTimeoutMs: 50,
    });
    const errorListener = vi.fn();
    client.addEventListener('error', errorListener);

    await flushQueuedReconnects();
    expect(fetchImpl).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(49);
    expect(fetchImpl).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(1);
    expect(errorListener).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'error',
      }),
    );

    await vi.advanceTimersByTimeAsync(10);
    expect(fetchImpl).toHaveBeenCalledTimes(2);

    client.close();
  });

  it('stops retrying when authenticated SSE receives a terminal auth error', async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: false,
      status: 401,
      body: createMockReadableBody([]),
    }));

    const client = createEventSource('/sse', {
      auth: { key: 'secret-token', mode: 'header' },
      baseUrl: 'http://127.0.0.1:5173',
      fetchImpl,
      retryDelayMs: 1,
    });
    const errorListener = vi.fn();
    client.addEventListener('error', errorListener);

    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(errorListener).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'error',
      })
    );
    client.close();
  });
});

describe('bindEventSourceListeners', () => {
  it('attaches and removes deduplicated event listeners', () => {
    const eventSource = {
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    };
    const listener = vi.fn();

    const detach = bindEventSourceListeners(
      eventSource,
      [...DEFAULT_SSE_REFRESH_EVENT_NAMES, 'message'],
      listener,
    );

    expect(eventSource.addEventListener).toHaveBeenCalledTimes(2);
    expect(eventSource.addEventListener).toHaveBeenNthCalledWith(1, 'endpoint', listener);
    expect(eventSource.addEventListener).toHaveBeenNthCalledWith(2, 'message', listener);

    detach();

    expect(eventSource.removeEventListener).toHaveBeenCalledTimes(2);
    expect(eventSource.removeEventListener).toHaveBeenNthCalledWith(1, 'endpoint', listener);
    expect(eventSource.removeEventListener).toHaveBeenNthCalledWith(2, 'message', listener);
  });
});
