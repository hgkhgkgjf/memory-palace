import axios from 'axios';
import i18n from '../i18n';

const resolveApiBaseURL = () => {
  const configured = import.meta.env?.VITE_API_BASE_URL;
  return typeof configured === 'string' && configured.trim()
    ? configured.trim()
    : '/api';
};

const api = axios.create({
  baseURL: resolveApiBaseURL(),
  timeout: 15000,
});

const LONG_RUNNING_REQUEST_TIMEOUT_MS = 60000;

const DASHBOARD_AUTH_STORAGE_KEY = 'memory-palace.dashboardAuth';
const STORED_AUTH_RUNTIME_OVERRIDE_KEY = 'preferStoredOverRuntime';
const MAINTENANCE_AUTH_CHANGED_EVENT = 'memory-palace:maintenance-auth-changed';

// Handle URI encoding for resource IDs which might contain special chars
const encodeId = (id) => encodeURIComponent(id);

const getBrowserStorage = (kind) => {
  if (typeof window === 'undefined') return null;
  try {
    if (kind === 'sessionStorage') return window.sessionStorage;
    if (kind === 'localStorage') return window.localStorage;
    return null;
  } catch (_error) {
    return null;
  }
};

const normalizeMaintenanceAuth = (runtimeConfig) => {
  if (!runtimeConfig || typeof runtimeConfig !== 'object') return null;
  const rawKey = runtimeConfig.maintenanceApiKey ?? runtimeConfig.mcpApiKey;
  const key = typeof rawKey === 'string' ? rawKey.trim() : '';
  if (!key) return null;
  const rawMode =
    runtimeConfig.maintenanceApiKeyMode ??
    runtimeConfig.mcpApiKeyMode ??
    'header';
  const mode =
    String(rawMode).trim().toLowerCase() === 'bearer' ? 'bearer' : 'header';
  return { key, mode };
};

const readWindowRuntimeMaintenanceAuth = () => {
  if (typeof window === 'undefined') return null;
  const runtimeConfig =
    window.__MEMORY_PALACE_RUNTIME__ || window.__MCP_RUNTIME_CONFIG__ || null;
  return normalizeMaintenanceAuth(runtimeConfig);
};

const readStoredMaintenanceAuthFrom = (storage) => {
  if (!storage) return null;
  try {
    const raw = storage.getItem(DASHBOARD_AUTH_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const auth = normalizeMaintenanceAuth(parsed);
    if (!auth) return null;
    return {
      auth,
      raw,
      preferStoredOverRuntime: parsed?.[STORED_AUTH_RUNTIME_OVERRIDE_KEY] === true,
    };
  } catch (_error) {
    return null;
  }
};

const removeStoredMaintenanceAuthFrom = (storage) => {
  if (!storage) return true;
  try {
    storage.removeItem(DASHBOARD_AUTH_STORAGE_KEY);
    return true;
  } catch (_error) {
    return false;
  }
};

const readStoredMaintenanceAuth = () => {
  const sessionStorage = getBrowserStorage('sessionStorage');
  const localStorage = getBrowserStorage('localStorage');

  const sessionRecord = readStoredMaintenanceAuthFrom(sessionStorage);
  if (sessionRecord) {
    return sessionRecord;
  }

  const legacyRecord = readStoredMaintenanceAuthFrom(localStorage);
  if (!legacyRecord) {
    return null;
  }

  // Migrate older localStorage persistence to sessionStorage when available.
  if (sessionStorage) {
    try {
      sessionStorage.setItem(
        DASHBOARD_AUTH_STORAGE_KEY,
        JSON.stringify({
          maintenanceApiKey: legacyRecord.auth.key,
          maintenanceApiKeyMode: legacyRecord.auth.mode,
          [STORED_AUTH_RUNTIME_OVERRIDE_KEY]: legacyRecord.preferStoredOverRuntime === true,
        })
      );
      if (localStorage?.getItem(DASHBOARD_AUTH_STORAGE_KEY) === legacyRecord.raw) {
        removeStoredMaintenanceAuthFrom(localStorage);
      }
    } catch (_error) {
      // Keep the legacy auth readable for the current session when migration fails.
    }
  }

  return legacyRecord;
};

export const getMaintenanceAuthState = () => {
  const storedAuth = readStoredMaintenanceAuth();
  if (storedAuth?.preferStoredOverRuntime) {
    return { ...storedAuth.auth, source: 'stored' };
  }

  const runtimeAuth = readWindowRuntimeMaintenanceAuth();
  if (runtimeAuth) {
    return { ...runtimeAuth, source: 'runtime' };
  }

  if (storedAuth) {
    return { ...storedAuth.auth, source: 'stored' };
  }

  return null;
};

const notifyMaintenanceAuthChanged = () => {
  if (typeof window === 'undefined' || typeof window.dispatchEvent !== 'function') {
    return;
  }
  window.dispatchEvent(new Event(MAINTENANCE_AUTH_CHANGED_EVENT));
};

export const subscribeMaintenanceAuthChanges = (listener) => {
  if (typeof window === 'undefined' || typeof listener !== 'function') {
    return () => {};
  }

  const notify = () => {
    listener(getMaintenanceAuthState());
  };

  const handleStorage = (event) => {
    if (!event || event.key === null || event.key === DASHBOARD_AUTH_STORAGE_KEY) {
      notify();
    }
  };

  window.addEventListener(MAINTENANCE_AUTH_CHANGED_EVENT, notify);
  window.addEventListener('storage', handleStorage);

  return () => {
    window.removeEventListener(MAINTENANCE_AUTH_CHANGED_EVENT, notify);
    window.removeEventListener('storage', handleStorage);
  };
};

export const saveStoredMaintenanceAuth = (key, mode = 'header') => {
  const normalized = normalizeMaintenanceAuth({
    maintenanceApiKey: key,
    maintenanceApiKeyMode: mode,
  });
  if (!normalized) return null;
  const sessionStorage = getBrowserStorage('sessionStorage');
  if (!sessionStorage) return false;
  try {
    sessionStorage.setItem(
      DASHBOARD_AUTH_STORAGE_KEY,
      JSON.stringify({
        maintenanceApiKey: normalized.key,
        maintenanceApiKeyMode: normalized.mode,
        [STORED_AUTH_RUNTIME_OVERRIDE_KEY]: true,
      })
    );
    removeStoredMaintenanceAuthFrom(getBrowserStorage('localStorage'));
  } catch (_error) {
    return false;
  }
  notifyMaintenanceAuthChanged();
  return getMaintenanceAuthState();
};

export const clearStoredMaintenanceAuth = () => {
  const sessionStorage = getBrowserStorage('sessionStorage');
  const localStorage = getBrowserStorage('localStorage');
  const sessionCleared = removeStoredMaintenanceAuthFrom(sessionStorage);
  const legacyCleared = removeStoredMaintenanceAuthFrom(localStorage);
  if (sessionCleared || legacyCleared) {
    notifyMaintenanceAuthChanged();
  }
  return sessionCleared && legacyCleared;
};

const readRuntimeMaintenanceAuth = () => {
  const authState = getMaintenanceAuthState();
  if (!authState) return null;
  return { key: authState.key, mode: authState.mode };
};

const normalizeApiBasePath = (apiBasePath = '') => {
  if (typeof apiBasePath !== 'string') return '';
  const trimmed = apiBasePath.trim();
  if (!trimmed) return '';
  if (trimmed === '/') return '/';
  return trimmed.replace(/\/+$/, '');
};

const normalizeProtectedPath = (pathname, apiBasePath = '') => {
  if (!pathname || typeof pathname !== 'string') return '';
  const normalizedBasePath = normalizeApiBasePath(apiBasePath);
  if (normalizedBasePath && normalizedBasePath !== '/') {
    if (pathname === normalizedBasePath) return '/';
    if (pathname.startsWith(`${normalizedBasePath}/`)) {
      return pathname.slice(normalizedBasePath.length) || '/';
    }
  }
  if (pathname.startsWith('/api/')) return pathname.slice('/api'.length);
  return pathname;
};

const isProtectedPath = (pathname) => {
  const normalizedPath = normalizeProtectedPath(pathname);
  if (normalizedPath.startsWith('/maintenance/')) return true;
  if (normalizedPath.startsWith('/review/')) return true;
  if (normalizedPath.startsWith('/browse/')) return true;
  if (normalizedPath.startsWith('/setup/')) return true;
  if (normalizedPath.startsWith('/layering/')) return true;
  if (normalizedPath.startsWith('/forgetting/')) return true;
  if (normalizedPath === '/search/quality-metrics') return true;
  return false;
};

const ABSOLUTE_URL_PATTERN = /^([a-z][a-z\d+\-.]*:)?\/\//i;

const combineUrlsLikeAxios = (baseURL, relativeURL) => {
  const normalizedBase = String(baseURL || '').replace(/\/+$/, '');
  const normalizedRelative = String(relativeURL || '').replace(/^\/+/, '');
  if (!normalizedBase) {
    return normalizedRelative ? `/${normalizedRelative}` : '/';
  }
  if (!normalizedRelative) {
    return normalizedBase;
  }
  return `${normalizedBase}/${normalizedRelative}`;
};

const resolveApiBaseUrl = (config) => {
  if (typeof window === 'undefined') return null;
  const candidates = [config?.baseURL, api.defaults?.baseURL];
  for (const candidate of candidates) {
    if (typeof candidate !== 'string' || !candidate.trim()) continue;
    try {
      return new URL(candidate.trim(), window.location.origin);
    } catch (_error) {
      continue;
    }
  }
  return null;
};

const resolveRequestUrl = (config) => {
  const url = config?.url;
  if (!url || typeof url !== 'string') return null;
  if (typeof window === 'undefined') return null;
  try {
    if (ABSOLUTE_URL_PATTERN.test(url)) {
      return new URL(url, window.location.origin);
    }
    const apiBaseUrl = resolveApiBaseUrl(config);
    if (apiBaseUrl) {
      return new URL(combineUrlsLikeAxios(apiBaseUrl.href, url), window.location.origin);
    }
    return new URL(url, window.location.origin);
  } catch (_error) {
    return null;
  }
};

const deleteHeader = (headers, name) => {
  if (!headers || typeof name !== 'string') return;
  if (typeof headers.delete === 'function') {
    headers.delete(name);
    return;
  }
  const normalizedName = name.toLowerCase();
  Object.keys(headers).forEach((key) => {
    if (key.toLowerCase() === normalizedName) {
      delete headers[key];
    }
  });
};

const setHeader = (headers, name, value) => {
  if (!headers || typeof name !== 'string') return;
  if (typeof headers.set === 'function') {
    headers.set(name, value);
    return;
  }
  headers[name] = value;
};

const isProtectedApiRequest = (config) => {
  if (typeof window === 'undefined') return false;
  const requestUrl = resolveRequestUrl(config);
  if (!requestUrl) return false;

  const currentOrigin = window.location.origin;
  const apiBaseUrl = resolveApiBaseUrl(config);
  const matchesCurrentOrigin = requestUrl.origin === currentOrigin;
  const matchesConfiguredApiOrigin = apiBaseUrl
    ? requestUrl.origin === apiBaseUrl.origin
    : false;
  if (!matchesCurrentOrigin && !matchesConfiguredApiOrigin) {
    return false;
  }

  const normalizedPath = normalizeProtectedPath(
    requestUrl.pathname,
    apiBaseUrl?.pathname || ''
  );
  return isProtectedPath(normalizedPath);
};

api.interceptors.request.use((config) => {
  const runtimeAuth = readRuntimeMaintenanceAuth();
  if (!runtimeAuth || !isProtectedApiRequest(config)) {
    return config;
  }

  const supportsSet = typeof config.headers?.set === 'function';
  const headers = supportsSet ? config.headers : { ...(config.headers || {}) };
  deleteHeader(headers, 'Authorization');
  deleteHeader(headers, 'X-MCP-API-Key');
  if (runtimeAuth.mode === 'bearer') {
    setHeader(headers, 'Authorization', `Bearer ${runtimeAuth.key}`);
  } else {
    setHeader(headers, 'X-MCP-API-Key', runtimeAuth.key);
  }
  config.headers = /** @type {any} */ (headers);
  return config;
});

const normalizeMemoryNode = (node) => {
  if (!node || typeof node !== 'object') return null;
  return {
    ...node,
    gist_text: node.gist_text || null,
    gist_method: node.gist_method || null,
    gist_quality:
      node.gist_quality == null || Number.isNaN(Number(node.gist_quality))
        ? null
        : Number(node.gist_quality),
    source_hash: node.source_hash || null,
  };
};

const normalizeMemoryChild = (child) => {
  if (!child || typeof child !== 'object') return child;
  return {
    ...child,
    gist_text: child.gist_text || null,
    gist_method: child.gist_method || null,
    gist_quality:
      child.gist_quality == null || Number.isNaN(Number(child.gist_quality))
        ? null
        : Number(child.gist_quality),
    source_hash: child.source_hash || null,
  };
};

const normalizeMemoryNodePayload = (payload) => {
  const safe = payload && typeof payload === 'object' ? payload : {};
  return {
    ...safe,
    node: normalizeMemoryNode(safe.node),
    children: Array.isArray(safe.children)
      ? safe.children.map((child) => normalizeMemoryChild(child))
      : [],
    breadcrumbs: Array.isArray(safe.breadcrumbs) ? safe.breadcrumbs : [],
  };
};

const normalizeApiErrorCode = (value) => {
  if (typeof value !== 'string') return null;
  const normalized = value.trim().toLowerCase();
  if (!normalized) return null;
  if (!/^[a-z0-9][a-z0-9_.-]*$/.test(normalized)) return null;
  return normalized;
};

const translateApiErrorCode = (value) => {
  const code = normalizeApiErrorCode(value);
  if (!code) return null;
  const translated = i18n.t(`apiErrors.codes.${code}`);
  return translated && translated !== `apiErrors.codes.${code}` ? translated : null;
};

const translateApiErrorMessage = (value) => {
  if (typeof value !== 'string') return null;
  const normalized = value.trim();
  if (!normalized) return null;
  const codeTranslation = translateApiErrorCode(normalized);
  if (codeTranslation) return codeTranslation;
  const lowered = normalized.toLowerCase();
  if (lowered === 'network error') {
    return i18n.t('apiErrors.networkError');
  }
  if (lowered === 'failed to fetch') {
    return i18n.t('apiErrors.failedToFetch');
  }
  const statusCodeMatch = /^request failed with status code (\d{3})$/i.exec(normalized);
  if (statusCodeMatch) {
    return i18n.t('apiErrors.statusCode', { status: statusCodeMatch[1] });
  }
  const timeoutMatch = /^timeout of (\d+)ms exceeded$/i.exec(normalized);
  if (timeoutMatch) {
    return i18n.t('apiErrors.timeoutExceeded', { ms: timeoutMatch[1] });
  }
  const translated = i18n.t(`apiErrors.messages.${normalized.toLowerCase()}`);
  return translated && translated !== `apiErrors.messages.${normalized.toLowerCase()}`
    ? translated
    : null;
};

const formatValidationErrorLocation = (value) => {
  if (!Array.isArray(value)) return '';
  return value
    .map((segment) => {
      if (typeof segment === 'number') return String(segment);
      if (typeof segment === 'string') return segment.trim();
      return '';
    })
    .filter(Boolean)
    .join('.');
};

const extractValidationErrorMessages = (detail) => {
  if (!Array.isArray(detail)) return [];
  const messages = [];
  const pushMessage = (value) => {
    if (typeof value !== 'string') return;
    const normalized = value.trim();
    if (!normalized || messages.includes(normalized)) return;
    messages.push(normalized);
  };

  detail.forEach((item) => {
    if (typeof item === 'string') {
      pushMessage(translateApiErrorMessage(item) || item);
      return;
    }
    if (!item || typeof item !== 'object') return;

    const location = formatValidationErrorLocation(item.loc);
    const translatedMessage = translateApiErrorMessage(item.msg) || item.msg;
    if (typeof translatedMessage !== 'string' || !translatedMessage.trim()) {
      pushMessage(location);
      return;
    }
    pushMessage(location ? `${location}: ${translatedMessage.trim()}` : translatedMessage);
  });

  return messages;
};

export const extractApiErrorCode = (error) => {
  const detail = error?.response?.data?.detail;
  const codes = [];
  const pushCode = (value) => {
    const code = normalizeApiErrorCode(value);
    if (!code || codes.includes(code)) return;
    codes.push(code);
  };

  if (typeof detail === 'string') {
    pushCode(detail);
  } else if (detail && typeof detail === 'object') {
    pushCode(detail.code);
    pushCode(detail.error);
    pushCode(detail.reason);
  }
  return codes[0] || null;
};

export const extractApiError = (
  error,
  fallback = i18n.t('apiErrors.requestFailed')
) => {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) {
    return translateApiErrorMessage(detail) || detail;
  }
  const validationMessages = extractValidationErrorMessages(detail);
  if (validationMessages.length > 0) {
    return validationMessages.join(' | ');
  }
  if (detail && typeof detail === 'object') {
    const parts = [];
    const pushPart = (value) => {
      if (typeof value !== 'string') return;
      const normalized = value.trim();
      if (!normalized || parts.includes(normalized)) return;
      parts.push(normalized);
    };

    pushPart(translateApiErrorCode(detail.error) || detail.error);
    pushPart(translateApiErrorCode(detail.reason) || detail.reason);
    if (typeof detail.operation === 'string' && detail.operation.trim()) {
      pushPart(i18n.t('apiErrors.operation', { operation: detail.operation.trim() }));
    }
    pushPart(translateApiErrorMessage(detail.message) || detail.message);
    const errorCode = normalizeApiErrorCode(detail.error);
    const reasonCode = normalizeApiErrorCode(detail.reason);
    const isLoopbackWriteRestriction =
      reasonCode === 'local_loopback_required_for_write'
      || reasonCode === 'insecure_local_override_requires_loopback';
    const isAuthError =
      error?.response?.status === 401
      || errorCode === 'maintenance_auth_failed'
      || errorCode === 'setup_access_denied'
      || errorCode === 'mcp_sse_auth_failed'
      || reasonCode === 'invalid_or_missing_api_key'
      || reasonCode === 'api_key_not_configured'
      || reasonCode === 'local_loopback_or_api_key_required';
    if (isAuthError && !isLoopbackWriteRestriction) {
      pushPart(i18n.t('apiErrors.authHint'));
    }
    if (parts.length > 0) {
      return parts.join(' | ');
    }
    try {
      return JSON.stringify(detail);
    } catch (_error) {
      return fallback;
    }
  }
  const message = error?.message;
  if (typeof message === 'string' && message.trim()) {
    return translateApiErrorMessage(message) || message;
  }
  return fallback;
};

// ============ Review API (Session & Snapshot) ============

export const getSetupStatus = () =>
  api.get('/setup/status').then(res => res.data);

export const saveSetupConfig = (payload) =>
  api.post('/setup/config', payload).then(res => res.data);

export const getSessions = () => api.get('/review/sessions').then(res => res.data);

export const getSnapshots = (sessionId) => 
  api.get(`/review/sessions/${encodeId(sessionId)}/snapshots`).then(res => res.data);

export const getDiff = (sessionId, resourceId) => 
  api.get(`/review/sessions/${encodeId(sessionId)}/diff/${encodeId(resourceId)}`).then(res => res.data);

export const rollbackResource = (sessionId, resourceId) => 
  api.post(`/review/sessions/${encodeId(sessionId)}/rollback/${encodeId(resourceId)}`, {}).then(res => res.data);

export const approveSnapshot = (sessionId, resourceId) => 
  api.delete(`/review/sessions/${encodeId(sessionId)}/snapshots/${encodeId(resourceId)}`).then(res => res.data);

export const clearSession = (sessionId) => 
  api.delete(`/review/sessions/${encodeId(sessionId)}`).then(res => res.data);

// ============ Catalog API (SQLite/URI Model) ============

export const getMemoryNode = (params, requestConfig = {}) => {
  const mergedParams = {
    ...(requestConfig?.params || {}),
    ...(params || {}),
  };
  return api
    .get('/browse/node', { ...requestConfig, params: mergedParams })
    .then(res => normalizeMemoryNodePayload(res.data));
};

export const createMemoryNode = (payload) =>
  api.post('/browse/node', payload).then(res => res.data);

export const updateMemoryNode = (path, domain, payload) =>
  api.put('/browse/node', payload, { params: { path, domain } }).then(res => res.data);

export const deleteMemoryNode = (path, domain) =>
  api.delete('/browse/node', { params: { path, domain } }).then(res => res.data);

// ============ Observability API ============

export const getObservabilitySummary = () =>
  api.get('/maintenance/observability/summary').then(res => res.data);

export const runObservabilitySearch = (payload) =>
  api.post('/maintenance/observability/search', payload, {
    timeout: LONG_RUNNING_REQUEST_TIMEOUT_MS,
  }).then(res => res.data);

export const getIndexWorkerStatus = () =>
  api.get('/maintenance/index/worker').then(res => res.data);

export const getIndexJob = (jobId) =>
  api.get(`/maintenance/index/job/${encodeId(jobId)}`).then(res => res.data);

export const cancelIndexJob = (jobId, payload = {}) =>
  api.post(`/maintenance/index/job/${encodeId(jobId)}/cancel`, payload).then(res => res.data);

export const retryIndexJob = (jobId, payload = {}) =>
  api.post(`/maintenance/index/job/${encodeId(jobId)}/retry`, payload).then(res => res.data);

export const triggerIndexRebuild = (params = {}) =>
  api.post('/maintenance/index/rebuild', null, {
    params,
    timeout: LONG_RUNNING_REQUEST_TIMEOUT_MS,
  }).then(res => res.data);

export const triggerMemoryReindex = (memoryId, params = {}) =>
  api.post(`/maintenance/index/reindex/${encodeId(memoryId)}`, null, {
    params,
    timeout: LONG_RUNNING_REQUEST_TIMEOUT_MS,
  }).then(res => res.data);

export const triggerSleepConsolidation = (params = {}) =>
  api.post('/maintenance/index/sleep-consolidation', null, {
    params,
    timeout: LONG_RUNNING_REQUEST_TIMEOUT_MS,
  }).then(res => res.data);

// ============ Vitality Cleanup API ============

export const triggerVitalityDecay = (params = {}) =>
  api.post('/maintenance/vitality/decay', null, { params }).then(res => res.data);

export const queryVitalityCleanupCandidates = (payload) =>
  api.post('/maintenance/vitality/candidates/query', payload).then(res => res.data);

export const prepareVitalityCleanup = (payload) =>
  api.post('/maintenance/vitality/cleanup/prepare', payload).then(res => res.data);

export const confirmVitalityCleanup = (payload) =>
  api.post('/maintenance/vitality/cleanup/confirm', payload, {
    timeout: LONG_RUNNING_REQUEST_TIMEOUT_MS,
  }).then(res => res.data);

// ============ Orphan Maintenance API ============

export const listOrphanMemories = () =>
  api.get('/maintenance/orphans').then(res => res.data);

export const getOrphanMemoryDetail = (memoryId) =>
  api.get(`/maintenance/orphans/${encodeId(memoryId)}`).then(res => res.data);

export const deleteOrphanMemory = (memoryId) =>
  api.delete(`/maintenance/orphans/${encodeId(memoryId)}`).then(res => res.data);

// ============ Search Quality Observability ============

export const getSearchQualityMetrics = () =>
  api.get('/search/quality-metrics').then(res => res.data);

// ============ Forgetting / Vitality Decay Review ============

export const simulateForgettingDecay = (params = {}) =>
  api.get('/forgetting/simulate', { params }).then(res => res.data);

export const getForgettingCandidates = (params = {}) =>
  api.get('/forgetting/candidates', { params }).then(res => res.data);

export const prepareForgettingArchive = (payload) =>
  api.post('/forgetting/archive/prepare', payload).then(res => res.data);

export const confirmForgettingArchive = (payload) =>
  api.post('/forgetting/archive/confirm', payload, {
    timeout: LONG_RUNNING_REQUEST_TIMEOUT_MS,
  }).then(res => res.data);

export const archiveForgettingCandidates = (payload) =>
  api.post('/forgetting/archive', payload).then(res => res.data);

// ============ Layering Hierarchy ============

const normalizeLayerStat = (stat) => {
  if (!stat || typeof stat !== 'object') return stat;
  return {
    ...stat,
    storage_bytes: stat.storage_bytes ?? stat.storage_budget_bytes ?? 0,
  };
};

const normalizeLayerSummary = (summary) => {
  if (!summary || typeof summary !== 'object') return summary;
  const sourceIds = Array.isArray(summary.source_memory_ids)
    ? summary.source_memory_ids
    : Array.isArray(summary.source_ids)
      ? summary.source_ids
      : [];
  return {
    ...summary,
    id: summary.id ?? summary.summary_id,
    summary: summary.summary ?? summary.summary_text ?? null,
    storage_bytes: summary.storage_bytes ?? summary.storage_budget_bytes ?? null,
    source_memory_ids: sourceIds,
    l1_count: summary.l1_count ?? sourceIds.length,
    l0_count: summary.l0_count ?? summary.access_log_count ?? 0,
  };
};

const normalizeLayerSourceMemory = (source) => {
  if (!source || typeof source !== 'object') return source;
  const id = source.id ?? source.memory_id;
  return {
    ...source,
    id,
    title: source.title ?? source.uri ?? (id !== undefined ? `#${id}` : null),
    content: source.content ?? source.current_content ?? source.content_snippet ?? null,
  };
};

const normalizeLayeringSummaries = (data) => {
  if (!data || typeof data !== 'object') return data;
  return {
    ...data,
    layer_stats: Array.isArray(data.layer_stats)
      ? data.layer_stats.map(normalizeLayerStat)
      : data.layer_stats,
    summaries: Array.isArray(data.summaries)
      ? data.summaries.map(normalizeLayerSummary)
      : [],
  };
};

const normalizeLayeringDetail = (data) => {
  if (!data || typeof data !== 'object') return data;
  const sources = Array.isArray(data.source_memories)
    ? data.source_memories
    : Array.isArray(data.sources)
      ? data.sources
      : [];
  return {
    ...data,
    summary: normalizeLayerSummary(data.summary),
    source_memories: sources.map(normalizeLayerSourceMemory),
  };
};

export const getLayeringSummaries = () =>
  api.get('/layering/summaries').then(res => normalizeLayeringSummaries(res.data));

export const getLayeringSummaryDetail = (summaryId) =>
  api.get(`/layering/summaries/${encodeId(summaryId)}`).then(res => normalizeLayeringDetail(res.data));
