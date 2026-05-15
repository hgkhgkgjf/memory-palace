export const DEFAULT_SSE_PATH = '/sse';
export const DEFAULT_SSE_REFRESH_EVENT_NAMES = ['endpoint', 'message'];
export const DEFAULT_SSE_RETRY_DELAY_MS = 1000;
export const DEFAULT_SSE_MAX_RETRY_DELAY_MS = 30_000;
export const DEFAULT_SSE_RETRY_BACKOFF_FACTOR = 2;
export const DEFAULT_SSE_RETRY_JITTER_RATIO = 0.2;
export const DEFAULT_SSE_IDLE_TIMEOUT_MS = 45_000;

const ABSOLUTE_URL_PATTERN = /^([a-z][a-z\d+\-.]*:)?\/\//i;

const normalizeBasePath = (value) => {
  if (typeof value !== 'string') return '';
  const trimmed = value.trim();
  if (!trimmed || trimmed === '/') return '';
  return trimmed.replace(/^\/+/, '/').replace(/\/+$/, '');
};

const resolvePrefixedSsePath = (path, baseUrl) => {
  if (typeof path !== 'string' || ABSOLUTE_URL_PATTERN.test(path)) {
    return path;
  }

  const configuredApiBase = import.meta.env?.VITE_API_BASE_URL;
  if (typeof configuredApiBase !== 'string' || !configuredApiBase.trim()) {
    return path;
  }

  try {
    const originFallback =
      (typeof window !== 'undefined' && window.location?.origin) || 'http://localhost';
    const resolvedBaseUrl = new URL(String(baseUrl || originFallback).trim(), originFallback);
    const resolvedApiBase = new URL(configuredApiBase.trim(), resolvedBaseUrl);

    const normalizedApiPath = normalizeBasePath(resolvedApiBase.pathname);
    if (!normalizedApiPath.endsWith('/api')) {
      return path;
    }

    const prefix = normalizedApiPath.slice(0, -'/api'.length);
    const normalizedSsePath = path.startsWith('/') ? path : `/${path}`;
    if (resolvedApiBase.origin !== resolvedBaseUrl.origin) {
      return new URL(`${prefix}${normalizedSsePath}`, resolvedApiBase.origin).toString();
    }

    if (!prefix) {
      return path;
    }

    return `${prefix}${normalizedSsePath}`;
  } catch (_error) {
    return path;
  }
};

export const resolveSseUrl = (path = DEFAULT_SSE_PATH, baseUrl) => {
  const normalizedPath = String(path || DEFAULT_SSE_PATH).trim() || DEFAULT_SSE_PATH;
  const normalizedBaseUrl = String(
    baseUrl
      || (typeof window !== 'undefined' && window.location?.origin)
      || 'http://localhost'
  ).trim();
  const resolvedPath = resolvePrefixedSsePath(normalizedPath, normalizedBaseUrl);
  return new URL(resolvedPath, normalizedBaseUrl).toString();
};

const normalizeSseAuth = (auth) => {
  if (!auth || typeof auth !== 'object') return null;
  const key = typeof auth.key === 'string' ? auth.key.trim() : '';
  if (!key) return null;
  const mode = String(auth.mode || 'header').trim().toLowerCase() === 'bearer'
    ? 'bearer'
    : 'header';
  return { key, mode };
};

const buildSseAuthHeaders = (auth) => {
  const normalizedAuth = normalizeSseAuth(auth);
  if (!normalizedAuth) return null;
  return normalizedAuth.mode === 'bearer'
    ? { Authorization: `Bearer ${normalizedAuth.key}` }
    : { 'X-MCP-API-Key': normalizedAuth.key };
};

const dispatchEventSourceMessage = (listeners, eventName, event) => {
  const entries = listeners.get(eventName);
  if (!entries || entries.size === 0) {
    return;
  }
  entries.forEach((listener) => {
    listener(event);
  });
};

const clampPositiveNumber = (value, fallback, minimum = 0) => {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) {
    return fallback;
  }
  return Math.max(minimum, numericValue);
};

const createFetchEventSource = (url, options = {}) => {
  const {
    auth,
    fetchImpl = globalThis.fetch,
    resolveAuth,
    retryDelayMs = DEFAULT_SSE_RETRY_DELAY_MS,
    maxRetryDelayMs = DEFAULT_SSE_MAX_RETRY_DELAY_MS,
    retryBackoffFactor = DEFAULT_SSE_RETRY_BACKOFF_FACTOR,
    retryJitterRatio = DEFAULT_SSE_RETRY_JITTER_RATIO,
    idleTimeoutMs = DEFAULT_SSE_IDLE_TIMEOUT_MS,
    withCredentials = false,
  } = options;

  if (typeof fetchImpl !== 'function') {
    throw new Error('fetch is not available in this environment.');
  }

  const decoder = new TextDecoder();
  const listeners = new Map();
  let closed = false;
  const normalizedRetryDelayMs = clampPositiveNumber(retryDelayMs, DEFAULT_SSE_RETRY_DELAY_MS);
  const normalizedMaxRetryDelayMs = clampPositiveNumber(
    maxRetryDelayMs,
    Math.max(DEFAULT_SSE_MAX_RETRY_DELAY_MS, normalizedRetryDelayMs),
    normalizedRetryDelayMs,
  );
  const normalizedRetryBackoffFactor = clampPositiveNumber(retryBackoffFactor, 1, 1);
  const normalizedRetryJitterRatio = Math.min(
    1,
    clampPositiveNumber(retryJitterRatio, DEFAULT_SSE_RETRY_JITTER_RATIO),
  );
  const normalizedIdleTimeoutMs = clampPositiveNumber(
    idleTimeoutMs,
    DEFAULT_SSE_IDLE_TIMEOUT_MS,
  );
  const windowTarget = typeof window !== 'undefined' ? window : null;
  const documentTarget = typeof document !== 'undefined' ? document : null;
  let reconnectTimer = null;
  let idleTimer = null;
  let retryAttempt = 0;
  let pageLifecyclePaused = false;
  let lifecyclePaused = false;
  let currentController = null;
  let currentAbortReason = null;
  let lastEventId = '';

  const emit = (eventName, payload = {}) => {
    dispatchEventSourceMessage(listeners, eventName, {
      ...payload,
      type: eventName,
    });
  };

  const flushEvent = (state) => {
    if (state.pendingLastEventId !== null) {
      lastEventId = state.pendingLastEventId;
    }
    if (!state.dataLines.length) return;
    retryAttempt = 0;
    emit(state.eventName || 'message', {
      data: state.dataLines.join('\n'),
      lastEventId,
    });
  };

  const parseChunk = (buffer, state) => {
    let working = buffer;
    while (true) {
      const newlineIndex = working.indexOf('\n');
      if (newlineIndex < 0) {
        break;
      }
      let line = working.slice(0, newlineIndex);
      working = working.slice(newlineIndex + 1);
      if (line.endsWith('\r')) {
        line = line.slice(0, -1);
      }
      if (!line) {
        flushEvent(state);
        state.eventName = 'message';
        state.dataLines = [];
        state.pendingLastEventId = null;
        continue;
      }
      if (line.startsWith(':')) {
        continue;
      }
      const separatorIndex = line.indexOf(':');
      const field = separatorIndex >= 0 ? line.slice(0, separatorIndex) : line;
      let value = separatorIndex >= 0 ? line.slice(separatorIndex + 1) : '';
      if (value.startsWith(' ')) {
        value = value.slice(1);
      }
      if (field === 'event') {
        state.eventName = value || 'message';
      } else if (field === 'data') {
        state.dataLines.push(value);
      } else if (field === 'id' && !value.includes('\0')) {
        state.pendingLastEventId = value;
      }
    }
    return working;
  };

  const state = {
    eventName: 'message',
    dataLines: [],
    pendingLastEventId: null,
  };

  const resolveCurrentAuthHeaders = () => {
    const currentAuth = normalizeSseAuth(resolveAuth?.()) || normalizeSseAuth(auth);
    return buildSseAuthHeaders(currentAuth) || {};
  };

  const buildRequestHeaders = () => {
    const authHeaders = resolveCurrentAuthHeaders();
    return lastEventId
      ? { ...authHeaders, 'Last-Event-ID': lastEventId }
      : authHeaders;
  };

  const clearReconnectTimer = () => {
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  const clearIdleTimer = () => {
    if (idleTimer !== null) {
      clearTimeout(idleTimer);
      idleTimer = null;
    }
  };

  const scheduleIdleWatchdog = () => {
    clearIdleTimer();
    if (closed || lifecyclePaused || normalizedIdleTimeoutMs <= 0) {
      return;
    }

    idleTimer = setTimeout(() => {
      if (closed || lifecyclePaused || !currentController) {
        return;
      }
      currentAbortReason = {
        type: 'idle-timeout',
        error: new Error(`SSE stream was idle for ${normalizedIdleTimeoutMs}ms`),
      };
      currentAbortReason.error.name = 'SSEIdleTimeoutError';
      currentController.abort();
    }, normalizedIdleTimeoutMs);
  };

  const markStreamActivity = () => {
    retryAttempt = 0;
    scheduleIdleWatchdog();
  };

  const getReconnectDelay = () => {
    const exponentialDelay = Math.min(
      normalizedMaxRetryDelayMs,
      normalizedRetryDelayMs * (normalizedRetryBackoffFactor ** retryAttempt),
    );
    retryAttempt += 1;

    if (normalizedRetryJitterRatio === 0 || exponentialDelay === 0) {
      return exponentialDelay;
    }

    const jitterWindow = exponentialDelay * normalizedRetryJitterRatio;
    const jitteredDelay = exponentialDelay + ((Math.random() * jitterWindow * 2) - jitterWindow);
    return Math.max(0, Math.round(jitteredDelay));
  };

  const abortCurrentConnection = (reason) => {
    clearIdleTimer();
    clearReconnectTimer();
    if (!currentController) {
      return;
    }
    currentAbortReason = reason;
    currentController.abort();
  };

  const scheduleReconnect = (connect, options = {}) => {
    const { immediate = false, resetBackoff = false } = options;
    if (closed || lifecyclePaused) {
      return;
    }
    if (resetBackoff) {
      retryAttempt = 0;
    }

    clearReconnectTimer();
    if (immediate) {
      queueMicrotask(() => {
        if (closed || lifecyclePaused) {
          return;
        }
        void connect();
      });
      return;
    }

    const delayMs = getReconnectDelay();
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      if (closed || lifecyclePaused) {
        return;
      }
      void connect();
    }, delayMs);
  };

  const connect = async () => {
    let shouldRetry = true;
    const controller = new AbortController();
    let abortReason = null;
    try {
      if (closed || lifecyclePaused) {
        return;
      }

      state.eventName = 'message';
      state.dataLines = [];
      state.pendingLastEventId = null;
      currentController = controller;
      currentAbortReason = null;
      scheduleIdleWatchdog();

      const response = await fetchImpl(url, {
        method: 'GET',
        headers: buildRequestHeaders(),
        signal: controller.signal,
        credentials: withCredentials ? 'include' : 'same-origin',
        cache: 'no-store',
      });
      if (!response.ok) {
        const error = /** @type {Error & { retryable?: boolean }} */ (
          new Error(`SSE request failed with status ${response.status}`)
        );
        if (response.status >= 400 && response.status < 500) {
          error.retryable = false;
        }
        throw error;
      }
      if (!response.body || typeof response.body.getReader !== 'function') {
        throw new Error('SSE response body is not readable.');
      }

      const reader = response.body.getReader();
      let buffer = '';
      while (!closed) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }
        markStreamActivity();
        buffer += decoder.decode(value, { stream: true });
        buffer = parseChunk(buffer, state);
      }
      buffer += decoder.decode();
      buffer = parseChunk(buffer, state);
      if (!closed && (buffer || state.dataLines.length > 0 || state.pendingLastEventId !== null)) {
        if (buffer) {
          state.dataLines.push(buffer.replace(/\r$/, ''));
        }
        flushEvent(state);
      }
    } catch (error) {
      abortReason = currentAbortReason;
      if (closed) {
        return;
      }
      if (abortReason?.type === 'lifecycle-pause' || abortReason?.type === 'manual-close') {
        return;
      }
      if (error?.name === 'AbortError' && !abortReason) {
        return;
      }
      if (abortReason?.type === 'idle-timeout') {
        emit('error', { error: abortReason.error });
      } else {
        emit('error', { error });
      }
      const normalizedError = /** @type {Error & { retryable?: boolean }} */ (error);
      if (normalizedError.retryable === false) {
        shouldRetry = false;
      }
    } finally {
      clearIdleTimer();
      if (currentController === controller) {
        currentController = null;
        currentAbortReason = null;
      }
    }

    if (!shouldRetry || closed) {
      return;
    }
    scheduleReconnect(connect);
  };

  const syncLifecycleState = () => {
    const documentHidden = Boolean(documentTarget?.hidden);
    const shouldPause = documentHidden || pageLifecyclePaused;
    if (shouldPause) {
      lifecyclePaused = true;
      abortCurrentConnection({ type: 'lifecycle-pause' });
      return;
    }
    if (!lifecyclePaused || closed) {
      return;
    }
    lifecyclePaused = false;
    scheduleReconnect(connect, { immediate: true, resetBackoff: true });
  };

  const detachLifecycleListeners = (() => {
    if (!windowTarget?.addEventListener && !documentTarget?.addEventListener) {
      return () => {};
    }

    const handleVisibilityChange = () => {
      syncLifecycleState();
    };
    const handlePageHide = () => {
      pageLifecyclePaused = true;
      syncLifecycleState();
    };
    const handlePageShow = () => {
      pageLifecyclePaused = false;
      syncLifecycleState();
    };
    const handleBeforeUnload = () => {
      pageLifecyclePaused = true;
      syncLifecycleState();
    };

    documentTarget?.addEventListener?.('visibilitychange', handleVisibilityChange);
    windowTarget?.addEventListener?.('pagehide', handlePageHide);
    windowTarget?.addEventListener?.('pageshow', handlePageShow);
    windowTarget?.addEventListener?.('beforeunload', handleBeforeUnload);

    return () => {
      documentTarget?.removeEventListener?.('visibilitychange', handleVisibilityChange);
      windowTarget?.removeEventListener?.('pagehide', handlePageHide);
      windowTarget?.removeEventListener?.('pageshow', handlePageShow);
      windowTarget?.removeEventListener?.('beforeunload', handleBeforeUnload);
    };
  })();

  queueMicrotask(() => {
    if (closed) {
      return;
    }
    lifecyclePaused = Boolean(documentTarget?.hidden);
    syncLifecycleState();
    if (!lifecyclePaused) {
      scheduleReconnect(connect, { immediate: true, resetBackoff: true });
    }
  });

  return {
    addEventListener(eventName, listener) {
      const name = String(eventName || '').trim();
      if (!name || typeof listener !== 'function') {
        return;
      }
      const entries = listeners.get(name) || new Set();
      entries.add(listener);
      listeners.set(name, entries);
    },
    removeEventListener(eventName, listener) {
      const name = String(eventName || '').trim();
      const entries = listeners.get(name);
      if (!name || !entries) {
        return;
      }
      entries.delete(listener);
      if (entries.size === 0) {
        listeners.delete(name);
      }
    },
    close() {
      if (closed) {
        return;
      }
      closed = true;
      detachLifecycleListeners();
      abortCurrentConnection({ type: 'manual-close' });
      clearIdleTimer();
    },
  };
};

/**
 * @typedef {{
 *   baseUrl?: string,
 *   withCredentials?: boolean,
 *   EventSourceImpl?: typeof EventSource,
 *   fetchImpl?: typeof fetch,
 *   auth?: { key: string, mode?: 'header' | 'bearer' } | null,
 *   resolveAuth?: () => ({ key: string, mode?: 'header' | 'bearer' } | null),
 *   retryDelayMs?: number,
 *   maxRetryDelayMs?: number,
 *   retryBackoffFactor?: number,
 *   retryJitterRatio?: number,
 *   idleTimeoutMs?: number,
 * }} CreateEventSourceOptions
 */

/**
 * @param {string} path
 * @param {CreateEventSourceOptions} [options]
 */
export const createEventSource = (
  path = DEFAULT_SSE_PATH,
  options = {}
) => {
  const {
    auth = null,
    baseUrl,
    withCredentials = false,
    EventSourceImpl = globalThis.EventSource,
    fetchImpl = globalThis.fetch,
    resolveAuth,
    retryDelayMs = DEFAULT_SSE_RETRY_DELAY_MS,
    maxRetryDelayMs = DEFAULT_SSE_MAX_RETRY_DELAY_MS,
    retryBackoffFactor = DEFAULT_SSE_RETRY_BACKOFF_FACTOR,
    retryJitterRatio = DEFAULT_SSE_RETRY_JITTER_RATIO,
    idleTimeoutMs = DEFAULT_SSE_IDLE_TIMEOUT_MS,
  } = options;
  const url = resolveSseUrl(path, baseUrl);
  if (normalizeSseAuth(auth)) {
    return createFetchEventSource(url, {
      auth,
      fetchImpl,
      resolveAuth,
      retryDelayMs,
      maxRetryDelayMs,
      retryBackoffFactor,
      retryJitterRatio,
      idleTimeoutMs,
      withCredentials,
    });
  }
  if (typeof EventSourceImpl !== 'function') {
    throw new Error('EventSource is not available in this environment.');
  }

  return new EventSourceImpl(url, { withCredentials });
};

/**
 * @param {{ addEventListener?: Function, removeEventListener?: Function } | null | undefined} eventSource
 * @param {string[] | string} eventNames
 * @param {(event: MessageEvent) => void} listener
 */
export const bindEventSourceListeners = (eventSource, eventNames, listener) => {
  if (!eventSource || typeof listener !== 'function') {
    return () => {};
  }

  const normalizedEventNames = [
    ...new Set(
      (Array.isArray(eventNames) ? eventNames : [eventNames])
        .map((eventName) => String(eventName || '').trim())
        .filter(Boolean)
    ),
  ];

  if (typeof eventSource.addEventListener === 'function') {
    normalizedEventNames.forEach((eventName) => {
      eventSource.addEventListener(eventName, listener);
    });
  }

  return () => {
    if (typeof eventSource.removeEventListener !== 'function') {
      return;
    }
    normalizedEventNames.forEach((eventName) => {
      eventSource.removeEventListener(eventName, listener);
    });
  };
};
