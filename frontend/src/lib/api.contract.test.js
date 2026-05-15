import { beforeEach, describe, expect, it, vi } from 'vitest';

const { mockApi, mockCreate, interceptorRef } = vi.hoisted(() => {
  const ref = { current: null };
  const apiInstance = {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    interceptors: {
      request: {
        use: vi.fn((handler) => {
          ref.current = handler;
        }),
      },
    },
  };
  return {
    mockApi: apiInstance,
    mockCreate: vi.fn(() => apiInstance),
    interceptorRef: ref,
  };
});

vi.mock('axios', () => ({
  default: {
    create: mockCreate,
  },
}));

import {
    approveSnapshot,
    clearSession,
    getDiff,
    getMemoryNode,
    getSnapshots,
    rollbackResource,
    runObservabilitySearch,
    listOrphanMemories,
    getOrphanMemoryDetail,
    deleteOrphanMemory,
    confirmVitalityCleanup,
    prepareForgettingArchive,
    confirmForgettingArchive,
    extractApiErrorCode,
    saveStoredMaintenanceAuth,
    clearStoredMaintenanceAuth,
    triggerIndexRebuild,
    triggerMemoryReindex,
    triggerSleepConsolidation,
} from './api';

describe('api contract regression', () => {
  beforeEach(() => {
    mockApi.get.mockReset();
    mockApi.post.mockReset();
    mockApi.put.mockReset();
    mockApi.delete.mockReset();
    delete window.__MEMORY_PALACE_RUNTIME__;
    delete window.__MCP_RUNTIME_CONFIG__;
    window.localStorage?.removeItem?.('memory-palace.dashboardAuth');
    window.sessionStorage?.removeItem?.('memory-palace.dashboardAuth');
  });

  it('normalizes memory node gist fields from backend payload', async () => {
    mockApi.get.mockResolvedValue({
      data: {
        node: {
          uri: 'core://agent/index',
          gist_text: 'Index summary',
          gist_method: 'llm',
          gist_quality: '0.72',
          source_hash: 'abc',
        },
        children: [
          {
            uri: 'core://agent/index/child',
            gist_text: '',
            gist_method: '',
            gist_quality: 'NaN',
          },
        ],
        breadcrumbs: null,
      },
    });

    const result = await getMemoryNode({ path: 'agent/index', domain: 'core' });

    expect(mockApi.get).toHaveBeenCalledWith('/browse/node', {
      params: { path: 'agent/index', domain: 'core' },
    });
    expect(result.node.gist_quality).toBe(0.72);
    expect(result.node.source_hash).toBe('abc');
    expect(result.children[0].gist_text).toBeNull();
    expect(result.children[0].gist_method).toBeNull();
    expect(result.children[0].gist_quality).toBeNull();
    expect(result.children[0].source_hash).toBeNull();
    expect(result.breadcrumbs).toEqual([]);
  });

  it('extracts normalized api error code from structured detail', () => {
    const code = extractApiErrorCode({
      response: {
        data: {
          detail: {
            error: 'CONFIRMATION_PHRASE_MISMATCH',
            message: 'phrase mismatch',
          },
        },
      },
    });

    expect(code).toBe('confirmation_phrase_mismatch');
  });

  it('returns null when detail does not contain code-like token', () => {
    const code = extractApiErrorCode({
      response: {
        data: {
          detail: 'job not found',
        },
      },
    });

    expect(code).toBeNull();
  });

  it('preserves observability search response contract', async () => {
    mockApi.post.mockResolvedValue({
      data: {
        ok: true,
        mode_requested: 'hybrid',
        mode_applied: 'hybrid',
        degraded: false,
        results: [],
      },
    });

    const payload = { query: 'release plan', mode: 'hybrid', include_session: false };
    const result = await runObservabilitySearch(payload);

    expect(mockApi.post).toHaveBeenCalledWith(
      '/maintenance/observability/search',
      payload,
      { timeout: 60000 }
    );
    expect(result.ok).toBe(true);
    expect(result.mode_requested).toBe('hybrid');
    expect(result.mode_applied).toBe('hybrid');
    expect(result.degraded).toBe(false);
    expect(result.results).toEqual([]);
  });

  it('encodes session and resource path segments for review APIs', async () => {
    mockApi.get.mockResolvedValueOnce({ data: [] });
    mockApi.get.mockResolvedValueOnce({ data: { diff: [] } });
    mockApi.post.mockResolvedValueOnce({ data: { ok: true } });
    mockApi.delete.mockResolvedValueOnce({ data: { ok: true } });
    mockApi.delete.mockResolvedValueOnce({ data: { ok: true } });

    await getSnapshots('session/a b');
    await getDiff('session/a b', 'core://node/with space');
    await rollbackResource('session/a b', 'core://node/with space');
    await approveSnapshot('session/a b', 'core://node/with space');
    await clearSession('session/a b');

    expect(mockApi.get).toHaveBeenNthCalledWith(
      1,
      '/review/sessions/session%2Fa%20b/snapshots'
    );
    expect(mockApi.get).toHaveBeenNthCalledWith(
      2,
      '/review/sessions/session%2Fa%20b/diff/core%3A%2F%2Fnode%2Fwith%20space'
    );
    expect(mockApi.post).toHaveBeenCalledWith(
      '/review/sessions/session%2Fa%20b/rollback/core%3A%2F%2Fnode%2Fwith%20space',
      {}
    );
    expect(mockApi.delete).toHaveBeenNthCalledWith(
      1,
      '/review/sessions/session%2Fa%20b/snapshots/core%3A%2F%2Fnode%2Fwith%20space'
    );
    expect(mockApi.delete).toHaveBeenNthCalledWith(
      2,
      '/review/sessions/session%2Fa%20b'
    );
  });

  it('uses extended timeout for long-running index maintenance operations', async () => {
    mockApi.post.mockResolvedValue({ data: { ok: true } });

    await triggerIndexRebuild({ reason: 'test' });
    await triggerMemoryReindex(42, { reason: 'test' });
    await triggerSleepConsolidation({ reason: 'test' });

    expect(mockApi.post).toHaveBeenNthCalledWith(1, '/maintenance/index/rebuild', null, {
      params: { reason: 'test' },
      timeout: 60000,
    });
    expect(mockApi.post).toHaveBeenNthCalledWith(2, '/maintenance/index/reindex/42', null, {
      params: { reason: 'test' },
      timeout: 60000,
    });
    expect(mockApi.post).toHaveBeenNthCalledWith(3, '/maintenance/index/sleep-consolidation', null, {
      params: { reason: 'test' },
      timeout: 60000,
    });
  });

  it('encodes memory ids for reindex endpoints', async () => {
    mockApi.post.mockResolvedValue({ data: { ok: true } });

    await triggerMemoryReindex('memory/42 with space', { reason: 'test' });

    expect(mockApi.post).toHaveBeenCalledWith(
      '/maintenance/index/reindex/memory%2F42%20with%20space',
      null,
      {
        params: { reason: 'test' },
        timeout: 60000,
      }
    );
  });

  it('uses extended timeout for vitality cleanup confirmation', async () => {
    mockApi.post.mockResolvedValue({ data: { deleted: 12 } });

    await confirmVitalityCleanup({ confirmation_phrase: 'DELETE 12', candidate_ids: [1, 2] });

    expect(mockApi.post).toHaveBeenCalledWith(
      '/maintenance/vitality/cleanup/confirm',
      { confirmation_phrase: 'DELETE 12', candidate_ids: [1, 2] },
      { timeout: 60000 }
    );
  });

  it('uses reviewed prepare/confirm endpoints for forgetting archive', async () => {
    mockApi.post.mockResolvedValue({ data: { ok: true } });

    await prepareForgettingArchive({ memory_ids: [1], threshold: 0.35, days: 30 });
    await confirmForgettingArchive({
      review_id: 'cleanup-abc',
      token: '0123456789abcdef',
      confirmation_phrase: 'CONFIRM ARCHIVE 1',
    });

    expect(mockApi.post).toHaveBeenNthCalledWith(
      1,
      '/forgetting/archive/prepare',
      { memory_ids: [1], threshold: 0.35, days: 30 }
    );
    expect(mockApi.post).toHaveBeenNthCalledWith(
      2,
      '/forgetting/archive/confirm',
      {
        review_id: 'cleanup-abc',
        token: '0123456789abcdef',
        confirmation_phrase: 'CONFIRM ARCHIVE 1',
      },
      { timeout: 60000 }
    );
  });

  it('routes orphan maintenance APIs through unified client', async () => {
    mockApi.get.mockResolvedValueOnce({ data: [{ id: 1 }] });
    mockApi.get.mockResolvedValueOnce({ data: { id: 1, content: 'content' } });
    mockApi.delete.mockResolvedValueOnce({ data: { deleted: true } });

    const list = await listOrphanMemories();
    const detail = await getOrphanMemoryDetail(1);
    const deleted = await deleteOrphanMemory(1);

    expect(mockApi.get).toHaveBeenNthCalledWith(1, '/maintenance/orphans');
    expect(mockApi.get).toHaveBeenNthCalledWith(2, '/maintenance/orphans/1');
    expect(mockApi.delete).toHaveBeenCalledWith('/maintenance/orphans/1');
    expect(list).toEqual([{ id: 1 }]);
    expect(detail).toEqual({ id: 1, content: 'content' });
    expect(deleted).toEqual({ deleted: true });
  });

  it('does not inject maintenance key by default', () => {
    const interceptor = interceptorRef.current;

    const config = interceptor({
      url: '/maintenance/orphans',
      headers: {},
    });

    expect(config.headers?.Authorization).toBeUndefined();
    expect(config.headers?.['X-MCP-API-Key']).toBeUndefined();
  });

  it('supports runtime-only maintenance key injection without VITE env', () => {
    const interceptor = interceptorRef.current;
    window.__MEMORY_PALACE_RUNTIME__ = {
      maintenanceApiKey: 'runtime-key',
      maintenanceApiKeyMode: 'bearer',
    };

    const maintenanceConfig = interceptor({
      url: '/maintenance/orphans',
      headers: {},
    });
    const browseConfig = interceptor({
      url: '/browse/node',
      headers: {},
    });

    expect(maintenanceConfig.headers.Authorization).toBe('Bearer runtime-key');
    expect(maintenanceConfig.headers['X-MCP-API-Key']).toBeUndefined();
    expect(browseConfig.headers.Authorization).toBe('Bearer runtime-key');
    expect(browseConfig.headers['X-MCP-API-Key']).toBeUndefined();
  });

  it('falls back to stored maintenance key when runtime config is absent', () => {
    const interceptor = interceptorRef.current;
    window.sessionStorage.setItem(
      'memory-palace.dashboardAuth',
      JSON.stringify({
        maintenanceApiKey: 'stored-key',
        maintenanceApiKeyMode: 'header',
      })
    );

    const config = interceptor({
      url: '/maintenance/orphans',
      headers: {},
      method: 'get',
    });

    expect(config.headers['X-MCP-API-Key']).toBe('stored-key');
    expect(config.headers.Authorization).toBeUndefined();
  });

  it('treats setup endpoints as protected and injects stored auth headers', () => {
    const interceptor = interceptorRef.current;
    window.sessionStorage.setItem(
      'memory-palace.dashboardAuth',
      JSON.stringify({
        maintenanceApiKey: 'stored-key',
        maintenanceApiKeyMode: 'header',
      })
    );

    const config = interceptor({
      url: '/setup/status',
      headers: {},
      method: 'get',
    });

    expect(config.headers['X-MCP-API-Key']).toBe('stored-key');
  });

  it('treats search quality endpoint as protected and injects stored auth headers', () => {
    const interceptor = interceptorRef.current;
    window.sessionStorage.setItem(
      'memory-palace.dashboardAuth',
      JSON.stringify({
        maintenanceApiKey: 'stored-key',
        maintenanceApiKeyMode: 'header',
      })
    );

    const config = interceptor({
      url: '/search/quality-metrics',
      headers: {},
      method: 'get',
    });

    expect(config.headers['X-MCP-API-Key']).toBe('stored-key');
  });

  it('prefers runtime maintenance key over stored fallback', () => {
    const interceptor = interceptorRef.current;
    window.sessionStorage.setItem(
      'memory-palace.dashboardAuth',
      JSON.stringify({
        maintenanceApiKey: 'stored-key',
        maintenanceApiKeyMode: 'header',
      })
    );
    window.__MEMORY_PALACE_RUNTIME__ = {
      maintenanceApiKey: 'runtime-key',
      maintenanceApiKeyMode: 'bearer',
    };

    const config = interceptor({
      url: '/maintenance/orphans',
      headers: {},
      method: 'get',
    });

    expect(config.headers.Authorization).toBe('Bearer runtime-key');
    expect(config.headers['X-MCP-API-Key']).toBeUndefined();
  });

  it('removes stale api-key headers when switching to bearer auth', () => {
    const interceptor = interceptorRef.current;
    window.__MEMORY_PALACE_RUNTIME__ = {
      maintenanceApiKey: 'runtime-key',
      maintenanceApiKeyMode: 'bearer',
    };

    const config = interceptor({
      url: '/maintenance/orphans',
      headers: {
        'X-MCP-API-Key': 'stale-key',
      },
      method: 'get',
    });

    expect(config.headers.Authorization).toBe('Bearer runtime-key');
    expect(config.headers['X-MCP-API-Key']).toBeUndefined();
  });

  it('removes stale bearer headers when switching back to header auth', () => {
    const interceptor = interceptorRef.current;
    window.__MEMORY_PALACE_RUNTIME__ = {
      maintenanceApiKey: 'runtime-key',
      maintenanceApiKeyMode: 'header',
    };

    const config = interceptor({
      url: '/maintenance/orphans',
      headers: {
        authorization: 'Bearer stale-key',
      },
      method: 'get',
    });

    expect(config.headers['X-MCP-API-Key']).toBe('runtime-key');
    expect(config.headers.Authorization).toBeUndefined();
    expect(config.headers.authorization).toBeUndefined();
  });

  it('uses a newly browser-saved key for protected requests immediately, even when runtime auth exists', () => {
    const interceptor = interceptorRef.current;
    window.__MEMORY_PALACE_RUNTIME__ = {
      maintenanceApiKey: 'runtime-key',
      maintenanceApiKeyMode: 'bearer',
    };

    const saved = saveStoredMaintenanceAuth('stored-key', 'header');
    const config = interceptor({
      url: '/maintenance/orphans',
      headers: {},
      method: 'get',
    });

    expect(saved).toMatchObject({
      key: 'stored-key',
      mode: 'header',
      source: 'stored',
    });
    expect(config.headers['X-MCP-API-Key']).toBe('stored-key');
    expect(config.headers.Authorization).toBeUndefined();
  });

  it('does not inject key to cross-origin URLs even with protected path', () => {
    const interceptor = interceptorRef.current;
    window.__MEMORY_PALACE_RUNTIME__ = {
      maintenanceApiKey: 'runtime-key',
      maintenanceApiKeyMode: 'header',
    };

    const config = interceptor({
      url: 'https://evil.example/maintenance/orphans',
      headers: {},
      method: 'get',
    });

    expect(config.headers.Authorization).toBeUndefined();
    expect(config.headers['X-MCP-API-Key']).toBeUndefined();
  });

  it('injects key for protected requests resolved through a configured cross-origin API base', () => {
    const interceptor = interceptorRef.current;
    window.sessionStorage.setItem(
      'memory-palace.dashboardAuth',
      JSON.stringify({
        maintenanceApiKey: 'stored-key',
        maintenanceApiKeyMode: 'header',
      })
    );

    const config = interceptor({
      url: '/maintenance/orphans',
      baseURL: 'https://api.example.com/api',
      headers: {},
      method: 'get',
    });

    expect(config.headers['X-MCP-API-Key']).toBe('stored-key');
    expect(config.headers.Authorization).toBeUndefined();
  });

  it('injects key for protected requests under a same-origin API base path prefix', () => {
    const interceptor = interceptorRef.current;
    window.__MEMORY_PALACE_RUNTIME__ = {
      maintenanceApiKey: 'runtime-key',
      maintenanceApiKeyMode: 'bearer',
    };

    const config = interceptor({
      url: '/browse/node',
      baseURL: '/memory-palace/api',
      headers: {},
      method: 'get',
    });

    expect(config.headers.Authorization).toBe('Bearer runtime-key');
    expect(config.headers['X-MCP-API-Key']).toBeUndefined();
  });

  it('injects key for protected requests when the API base path prefix keeps a trailing slash', () => {
    const interceptor = interceptorRef.current;
    window.__MEMORY_PALACE_RUNTIME__ = {
      maintenanceApiKey: 'runtime-key',
      maintenanceApiKeyMode: 'bearer',
    };

    const config = interceptor({
      url: '/browse/node',
      baseURL: '/memory-palace/api/',
      headers: {},
      method: 'get',
    });

    expect(config.headers.Authorization).toBe('Bearer runtime-key');
    expect(config.headers['X-MCP-API-Key']).toBeUndefined();
  });

  it('injects key for protected requests when a cross-origin API base keeps a trailing slash', () => {
    const interceptor = interceptorRef.current;
    window.sessionStorage.setItem(
      'memory-palace.dashboardAuth',
      JSON.stringify({
        maintenanceApiKey: 'stored-key',
        maintenanceApiKeyMode: 'header',
      })
    );

    const config = interceptor({
      url: '/maintenance/orphans',
      baseURL: 'https://api.example.com/memory-palace/api/',
      headers: {},
      method: 'get',
    });

    expect(config.headers['X-MCP-API-Key']).toBe('stored-key');
    expect(config.headers.Authorization).toBeUndefined();
  });

  it('injects runtime key for review and browse read/write requests', () => {
    const interceptor = interceptorRef.current;
    window.__MEMORY_PALACE_RUNTIME__ = {
      maintenanceApiKey: 'runtime-key',
      maintenanceApiKeyMode: 'header',
    };

    const reviewConfig = interceptor({
      url: '/review/sessions',
      headers: {},
      method: 'get',
    });
    const browseWriteConfig = interceptor({
      url: '/browse/node',
      headers: {},
      method: 'post',
    });
    const browseReadConfig = interceptor({
      url: '/browse/node',
      headers: {},
      method: 'get',
    });

    expect(reviewConfig.headers['X-MCP-API-Key']).toBe('runtime-key');
    expect(browseWriteConfig.headers['X-MCP-API-Key']).toBe('runtime-key');
    expect(browseReadConfig.headers['X-MCP-API-Key']).toBe('runtime-key');
  });

  it('merges getMemoryNode params safely with requestConfig', async () => {
    mockApi.get.mockResolvedValue({
      data: {
        node: { uri: 'core://agent/index' },
        children: [],
        breadcrumbs: [],
      },
    });

    await getMemoryNode(
      { path: 'agent/index', domain: 'core' },
      { params: { path: 'evil/path', domain: 'evil' }, signal: 'sig' }
    );

    expect(mockApi.get).toHaveBeenCalledWith('/browse/node', {
      signal: 'sig',
      params: { path: 'agent/index', domain: 'core' },
    });
  });

  it('migrates legacy localStorage auth into session storage', () => {
    const interceptor = interceptorRef.current;
    window.localStorage.setItem(
      'memory-palace.dashboardAuth',
      JSON.stringify({
        maintenanceApiKey: 'legacy-key',
        maintenanceApiKeyMode: 'header',
      })
    );

    const config = interceptor({
      url: '/maintenance/orphans',
      headers: {},
      method: 'get',
    });

    expect(config.headers['X-MCP-API-Key']).toBe('legacy-key');
    expect(window.localStorage.getItem('memory-palace.dashboardAuth')).toBeNull();
    expect(window.sessionStorage.getItem('memory-palace.dashboardAuth')).toContain('legacy-key');
  });

  it('returns false instead of throwing when saving browser auth hits storage failure', () => {
    const originalStorage = window.sessionStorage;
    Object.defineProperty(window, 'sessionStorage', {
      configurable: true,
      writable: true,
      value: {
        getItem: originalStorage.getItem.bind(originalStorage),
        setItem: (key, value) => {
          if (key === 'memory-palace.dashboardAuth') {
            throw new Error('quota');
          }
          return originalStorage.setItem(key, value);
        },
        removeItem: originalStorage.removeItem.bind(originalStorage),
        clear: originalStorage.clear.bind(originalStorage),
      },
    });

    expect(saveStoredMaintenanceAuth('stored-key')).toBe(false);
    Object.defineProperty(window, 'sessionStorage', {
      configurable: true,
      writable: true,
      value: originalStorage,
    });
  });

  it('returns false instead of throwing when clearing browser auth hits storage failure', () => {
    const originalSessionStorage = window.sessionStorage;
    Object.defineProperty(window, 'sessionStorage', {
      configurable: true,
      writable: true,
      value: {
        getItem: originalSessionStorage.getItem.bind(originalSessionStorage),
        setItem: originalSessionStorage.setItem.bind(originalSessionStorage),
        removeItem: () => {
          throw new Error('quota');
        },
        clear: originalSessionStorage.clear.bind(originalSessionStorage),
      },
    });

    expect(clearStoredMaintenanceAuth()).toBe(false);
    Object.defineProperty(window, 'sessionStorage', {
      configurable: true,
      writable: true,
      value: originalSessionStorage,
    });
  });

  it('supports overriding the API base URL via VITE_API_BASE_URL', async () => {
    vi.resetModules();
    mockCreate.mockClear();
    vi.stubEnv('VITE_API_BASE_URL', '/memory-palace/api');

    await import('./api');

    expect(mockCreate).toHaveBeenCalledWith(
      expect.objectContaining({
        baseURL: '/memory-palace/api',
        timeout: 15000,
      })
    );

    vi.unstubAllEnvs();
  });
});
