import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../lib/api';
import { formatDateTime as formatDateTimeValue } from '../../lib/format';
import i18n, { LOCALE_STORAGE_KEY } from '../../i18n';
import ObservabilityPage from './ObservabilityPage';

vi.mock('../../lib/api', () => ({
  cancelIndexJob: vi.fn(),
  extractApiError: vi.fn((error, fallback = 'Request failed') => error?.message || fallback),
  getIndexJob: vi.fn(),
  getMaintenanceAuthState: vi.fn(() => null),
  getObservabilitySummary: vi.fn(),
  retryIndexJob: vi.fn(),
  runObservabilitySearch: vi.fn(),
  subscribeMaintenanceAuthChanges: vi.fn(() => () => {}),
  triggerIndexRebuild: vi.fn(),
  triggerMemoryReindex: vi.fn(),
  triggerSleepConsolidation: vi.fn(),
}));

const buildSummary = ({
  activeJobId = null,
  recentJobs = [],
  timestamp = '2026-01-01T00:00:00Z',
  queueDepth = recentJobs.length,
  lastError = null,
  searchStats = {},
  reflectionWorkflow = null,
  smLite = {
    storage: 'runtime_ephemeral',
    promotion_path: 'compact_context + auto_flush',
    session_cache: { session_count: 0, total_hits: 0 },
    flush_tracker: { session_count: 0, pending_events: 0 },
  },
} = {}) => ({
  status: 'ok',
  timestamp,
  search_stats: searchStats,
  health: {
    index: { degraded: false },
    runtime: {
      index_worker: {
        active_job_id: activeJobId,
        recent_jobs: recentJobs,
        queue_depth: queueDepth,
        cancelling_jobs: 0,
        sleep_pending: false,
        last_error: lastError,
      },
      sleep_consolidation: {},
      sm_lite: smLite,
    },
  },
  index_latency: {},
  cleanup_query_stats: {},
  ...(reflectionWorkflow ? { reflection_workflow: reflectionWorkflow } : {}),
});

const createDeferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
};

const createMockEventSource = () => {
  const listeners = new Map();
  return {
    addEventListener: vi.fn((eventName, listener) => {
      const entries = listeners.get(eventName) || [];
      entries.push(listener);
      listeners.set(eventName, entries);
    }),
    removeEventListener: vi.fn((eventName, listener) => {
      const entries = listeners.get(eventName) || [];
      listeners.set(
        eventName,
        entries.filter((entry) => entry !== listener),
      );
    }),
    close: vi.fn(),
    emit(eventName, event = {}) {
      const entries = listeners.get(eventName) || [];
      entries.forEach((listener) => listener(event));
    },
  };
};

describe('ObservabilityPage', () => {
  const getJobCardById = async (jobId) => {
    const jobLabel = await screen.findByText(jobId);
    const card = jobLabel.closest('article');
    expect(card).not.toBeNull();
    return card;
  };

  beforeEach(async () => {
    vi.clearAllMocks();
    window.localStorage?.removeItem?.(LOCALE_STORAGE_KEY);
    window.localStorage?.removeItem?.('memory-palace.dashboardAuth');
    window.sessionStorage?.removeItem?.('memory-palace.dashboardAuth');
    delete window.__MEMORY_PALACE_RUNTIME__;
    delete window.__MCP_RUNTIME_CONFIG__;
    await i18n.changeLanguage('en');
    api.getMaintenanceAuthState.mockReturnValue(null);
    api.getObservabilitySummary.mockResolvedValue(buildSummary());
    api.getIndexJob.mockResolvedValue({ job: null });
    api.retryIndexJob.mockResolvedValue({ job_id: 'retry-default' });
    api.runObservabilitySearch.mockResolvedValue({ results: [] });
    api.subscribeMaintenanceAuthChanges.mockImplementation(() => () => {});
    api.triggerIndexRebuild.mockResolvedValue({ job_id: 'rebuild-default' });
    api.triggerMemoryReindex.mockResolvedValue({ job_id: 'reindex-default' });
    api.triggerSleepConsolidation.mockResolvedValue({ job_id: 'sleep-default' });
    api.cancelIndexJob.mockResolvedValue({});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('shows translated validation errors in zh-CN for invalid integer inputs', async () => {
    const user = userEvent.setup();
    await i18n.changeLanguage('zh-CN');
    render(<ObservabilityPage />);

    const maxResultsInput = await screen.findByLabelText(i18n.t('observability.maxResults'));
    await user.clear(maxResultsInput);
    await user.type(maxResultsInput, '999');
    await user.click(screen.getByRole('button', { name: i18n.t('observability.runDiagnosticSearch') }));

    expect(
      await screen.findByText((content) => content.includes('最大结果数') && content.includes('[1, 50]'))
    ).toBeInTheDocument();
    expect(api.runObservabilitySearch).not.toHaveBeenCalled();
  });

  it('localizes dynamic runtime, job, and diagnostic tokens in zh-CN', async () => {
    const user = userEvent.setup();
    await i18n.changeLanguage('zh-CN');
    api.getObservabilitySummary.mockResolvedValue(
      buildSummary({
        searchStats: {
          latency_ms: { avg: 18.4, p95: 41.7 },
        },
        reflectionWorkflow: {
          prepared: 2,
          executed: 1,
          rolled_back: 1,
        },
        recentJobs: [
          {
            job_id: 'job-zh',
            status: 'failed',
            task_type: 'rebuild_index',
            reason: 'retry-later',
          },
        ],
        smLite: {
          storage: 'runtime_ephemeral',
          promotion_path: 'compact_context + auto_flush',
          session_cache: { session_count: 2, total_hits: 6 },
          flush_tracker: { session_count: 1, pending_events: 3 },
          degraded: true,
          reason: 'session queue pressure',
        },
      }),
    );
    api.runObservabilitySearch.mockResolvedValue({
      latency_ms: 12.3,
      mode_applied: 'semantic',
      intent_applied: 'temporal',
      strategy_template_applied: 'temporal_time_filtered',
      interaction_tier: 'deep',
      intent_llm_attempted: true,
      degraded: false,
      counts: { session: 1, global: 2, returned: 1 },
      results: [
        {
          uri: 'core://agent/zh-check',
          memory_id: 7,
          snippet: 'localized result',
          metadata: {
            source: 'session_queue',
            priority: 0,
            updated_at: '2026-01-01T00:00:00Z',
          },
          scores: { final: 0.88 },
        },
      ],
    });

    render(<ObservabilityPage />);

    expect(await screen.findByText('状态：正常')).toBeInTheDocument();
    expect(screen.getByText('索引降级：否')).toBeInTheDocument();
    expect(screen.getByText('sm-lite 降级：是')).toBeInTheDocument();
    expect(screen.getByText('反思工作流：已准备 2 / 已执行 1 / 已回滚 1')).toBeInTheDocument();
    expect(screen.getByText('P95：41.7 ms')).toBeInTheDocument();
    expect(screen.getByText('索引重建')).toBeInTheDocument();
    expect(screen.getByText('失败')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '执行诊断搜索' }));

    expect(await screen.findByText('模式 语义')).toBeInTheDocument();
    expect(screen.getByText('意图 时序型')).toBeInTheDocument();
    expect(screen.getByText('策略 时序过滤')).toBeInTheDocument();
    expect(screen.getByText('交互层级 深度')).toBeInTheDocument();
    expect(screen.getByText('意图 LLM 已尝试 是')).toBeInTheDocument();
    expect(screen.getByText('降级 否')).toBeInTheDocument();
    expect(screen.getByText('会话队列')).toBeInTheDocument();
  });

  it('formats result timestamps instead of rendering raw ISO strings', async () => {
    const user = userEvent.setup();
    api.runObservabilitySearch.mockResolvedValueOnce({
      results: [
        {
          uri: 'core://agent/date-check',
          memory_id: 8,
          snippet: 'timestamp result',
          metadata: {
            source: 'global',
            priority: 0,
            updated_at: '2026-01-01T00:00:00Z',
          },
          scores: { final: 0.5 },
        },
      ],
    });

    render(<ObservabilityPage />);

    await user.click(screen.getByRole('button', { name: /Run Diagnostic Search/i }));

    const expected = formatDateTimeValue('2026-01-01T00:00:00Z', 'en', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
    expect(await screen.findByText(expected)).toBeInTheDocument();
    expect(screen.queryByText('2026-01-01T00:00:00Z')).not.toBeInTheDocument();
  });

  it('uses unified retry endpoint when retry API is available', async () => {
    const failedJob = {
      job_id: 'job-unified',
      status: 'failed',
      task_type: 'reindex_memory',
      memory_id: 12,
      reason: 'failed-job',
    };
    api.getObservabilitySummary
      .mockResolvedValueOnce(buildSummary({ recentJobs: [failedJob], timestamp: '2026-01-01T00:00:00Z' }))
      .mockResolvedValueOnce(buildSummary({ recentJobs: [failedJob], timestamp: '2026-01-01T00:00:01Z' }));
    api.retryIndexJob.mockResolvedValueOnce({ job_id: 'job-unified-retry' });

    const user = userEvent.setup();
    render(<ObservabilityPage />);

    const jobCard = await getJobCardById('job-unified');
    await user.click(within(jobCard).getByRole('button', { name: 'Retry' }));

    await waitFor(() => {
      expect(api.retryIndexJob).toHaveBeenCalledWith('job-unified', { reason: 'retry:job-unified' });
    });
    expect(api.triggerMemoryReindex).not.toHaveBeenCalled();
    expect(api.triggerIndexRebuild).not.toHaveBeenCalled();
    expect(api.triggerSleepConsolidation).not.toHaveBeenCalled();
    expect(await screen.findByText(/Retry requested/i)).toBeInTheDocument();
  });

  it('localizes retry, rebuild, and sleep success targets in zh-CN', async () => {
    const failedJob = {
      job_id: 'job-zh-retry-source',
      status: 'failed',
      task_type: 'reindex_memory',
      memory_id: 12,
      reason: 'failed-job',
    };
    await i18n.changeLanguage('zh-CN');
    api.getObservabilitySummary
      .mockResolvedValueOnce(buildSummary({ recentJobs: [failedJob], timestamp: '2026-01-01T00:00:00Z' }))
      .mockResolvedValue(buildSummary({ recentJobs: [failedJob], timestamp: '2026-01-01T00:00:01Z' }));
    api.triggerIndexRebuild.mockResolvedValueOnce({ job_id: 'job-rebuild-zh' });
    api.triggerSleepConsolidation.mockResolvedValueOnce({});
    api.retryIndexJob.mockResolvedValueOnce({ job_id: 'job-retry-zh' });

    const user = userEvent.setup();
    render(<ObservabilityPage />);

    await user.click(await screen.findByRole('button', { name: '重建索引' }));
    expect(await screen.findByText('已请求重建（任务 job-rebuild-zh）')).toBeInTheDocument();
    expect(screen.queryByText('已请求重建（job job-rebuild-zh）')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '睡眠整合' }));
    expect(await screen.findByText('已请求睡眠整合（同步）')).toBeInTheDocument();
    expect(screen.queryByText('已请求睡眠整合（sync）')).not.toBeInTheDocument();

    const jobCard = await getJobCardById('job-zh-retry-source');
    await user.click(within(jobCard).getByRole('button', { name: '重试' }));
    expect(await screen.findByText('已请求重试（任务 job-retry-zh）')).toBeInTheDocument();
    expect(screen.queryByText('已请求重试（job job-retry-zh）')).not.toBeInTheDocument();
  });

  it('does not refetch summary when only the language changes', async () => {
    render(<ObservabilityPage />);

    await screen.findByText('Search Console');
    const initialCalls = api.getObservabilitySummary.mock.calls.length;
    expect(initialCalls).toBeGreaterThan(0);

    await act(async () => {
      await i18n.changeLanguage('zh-CN');
    });

    await screen.findByText('搜索控制台');
    expect(api.getObservabilitySummary.mock.calls.length).toBe(initialCalls);
  });

  it('relocalizes visible errors and untouched default query when only the language changes', async () => {
    api.getObservabilitySummary.mockRejectedValueOnce({ message: 'Network Error' });
    api.extractApiError.mockImplementation((error, fallback = 'Request failed') => {
      const locale = i18n.resolvedLanguage || i18n.language || 'en';
      return `${locale}:${error?.message || fallback}`;
    });

    render(<ObservabilityPage />);

    expect(await screen.findByText('en:Network Error')).toBeInTheDocument();
    expect(screen.getByLabelText('Query')).toHaveValue('memory flush queue');
    const initialCalls = api.getObservabilitySummary.mock.calls.length;

    await act(async () => {
      await i18n.changeLanguage('zh-CN');
    });

    expect(api.getObservabilitySummary.mock.calls.length).toBe(initialCalls);
    expect(await screen.findByText('zh-CN:Network Error')).toBeInTheDocument();
    expect(screen.getByLabelText('查询词')).toHaveValue(i18n.t('observability.defaultQuery'));
  });

  it('falls back to old backend endpoint when retry API is unsupported', async () => {
    const legacyJob = {
      job_id: 'job-legacy',
      status: 'failed',
      task_type: 'reindex_memory',
      memory_id: 77,
      reason: 'legacy-backend',
    };
    api.getObservabilitySummary
      .mockResolvedValueOnce(buildSummary({ recentJobs: [legacyJob], timestamp: '2026-01-01T00:00:00Z' }))
      .mockResolvedValueOnce(buildSummary({ recentJobs: [legacyJob], timestamp: '2026-01-01T00:00:01Z' }));
    api.retryIndexJob.mockRejectedValueOnce({
      response: { status: 404, data: { detail: 'Not Found' } },
    });
    api.triggerMemoryReindex.mockResolvedValueOnce({ job_id: 'job-legacy-retry' });

    const user = userEvent.setup();
    render(<ObservabilityPage />);

    const jobCard = await getJobCardById('job-legacy');
    await user.click(within(jobCard).getByRole('button', { name: 'Retry' }));

    await waitFor(() => {
      expect(api.retryIndexJob).toHaveBeenCalledWith('job-legacy', { reason: 'retry:job-legacy' });
      expect(api.triggerMemoryReindex).toHaveBeenCalledWith(77, { reason: 'retry:job-legacy', wait: false });
    });
    expect(api.triggerIndexRebuild).not.toHaveBeenCalled();
    expect(api.triggerSleepConsolidation).not.toHaveBeenCalled();
    expect(await screen.findByText(/Retry requested/i)).toBeInTheDocument();
  });

  it('falls back to legacy rebuild endpoint when retry endpoint returns 405', async () => {
    const legacyJob = {
      job_id: 'job-legacy-rebuild',
      status: 'failed',
      task_type: 'rebuild_index',
      reason: 'legacy-rebuild',
    };
    api.getObservabilitySummary
      .mockResolvedValueOnce(buildSummary({ recentJobs: [legacyJob], timestamp: '2026-01-01T00:00:00Z' }))
      .mockResolvedValueOnce(buildSummary({ recentJobs: [legacyJob], timestamp: '2026-01-01T00:00:01Z' }));
    api.retryIndexJob.mockRejectedValueOnce({
      response: { status: 405, data: { detail: 'Method Not Allowed' } },
    });
    api.triggerIndexRebuild.mockResolvedValueOnce({ job_id: 'job-legacy-rebuild-retry' });

    const user = userEvent.setup();
    render(<ObservabilityPage />);

    const jobCard = await getJobCardById('job-legacy-rebuild');
    await user.click(within(jobCard).getByRole('button', { name: 'Retry' }));

    await waitFor(() => {
      expect(api.retryIndexJob).toHaveBeenCalledWith('job-legacy-rebuild', { reason: 'retry:job-legacy-rebuild' });
      expect(api.triggerIndexRebuild).toHaveBeenCalledWith({ reason: 'retry:job-legacy-rebuild', wait: false });
    });
    expect(api.triggerMemoryReindex).not.toHaveBeenCalled();
    expect(api.triggerSleepConsolidation).not.toHaveBeenCalled();
    expect(await screen.findByText(/Retry requested/i)).toBeInTheDocument();
  });

  it('does not fallback to legacy endpoints when retry returns job_not_found', async () => {
    const failedJob = {
      job_id: 'job-not-found',
      status: 'failed',
      task_type: 'reindex_memory',
      memory_id: 88,
      reason: 'not-found-case',
    };
    api.getObservabilitySummary.mockResolvedValue(buildSummary({ recentJobs: [failedJob] }));
    api.retryIndexJob.mockRejectedValueOnce({
      message: 'job not found',
      response: {
        status: 404,
        data: {
          detail: { error: 'job_not_found', message: 'job not found' },
        },
      },
    });

    const user = userEvent.setup();
    render(<ObservabilityPage />);

    const jobCard = await getJobCardById('job-not-found');
    await user.click(within(jobCard).getByRole('button', { name: 'Retry' }));

    await waitFor(() => {
      expect(api.retryIndexJob).toHaveBeenCalledWith('job-not-found', { reason: 'retry:job-not-found' });
    });
    expect(api.triggerMemoryReindex).not.toHaveBeenCalled();
    expect(api.triggerIndexRebuild).not.toHaveBeenCalled();
    expect(api.triggerSleepConsolidation).not.toHaveBeenCalled();
    expect(await screen.findByText(/Retry failed \(job-not-found\): job not found/i)).toBeInTheDocument();
  });

  it('does not fallback when 404 detail message reports job not found', async () => {
    const failedJob = {
      job_id: 'job-not-found-message',
      status: 'failed',
      task_type: 'rebuild_index',
      reason: 'not-found-message-case',
    };
    api.getObservabilitySummary.mockResolvedValue(buildSummary({ recentJobs: [failedJob] }));
    api.retryIndexJob.mockRejectedValueOnce({
      message: 'job missing',
      response: {
        status: 404,
        data: {
          detail: {
            error: 'request_failed',
            reason: 'backend_error',
            message: 'job not found',
          },
        },
      },
    });

    const user = userEvent.setup();
    render(<ObservabilityPage />);

    const jobCard = await getJobCardById('job-not-found-message');
    await user.click(within(jobCard).getByRole('button', { name: 'Retry' }));

    await waitFor(() => {
      expect(api.retryIndexJob).toHaveBeenCalledWith('job-not-found-message', { reason: 'retry:job-not-found-message' });
    });
    expect(api.triggerMemoryReindex).not.toHaveBeenCalled();
    expect(api.triggerIndexRebuild).not.toHaveBeenCalled();
    expect(api.triggerSleepConsolidation).not.toHaveBeenCalled();
    expect(await screen.findByText(/Retry failed \(job-not-found-message\): job missing/i)).toBeInTheDocument();
  });

  it('falls back to legacy sleep consolidation endpoint when retry endpoint returns 405', async () => {
    const legacyJob = {
      job_id: 'job-legacy-sleep',
      status: 'failed',
      task_type: 'sleep_consolidation',
      reason: 'legacy-sleep',
    };
    api.getObservabilitySummary
      .mockResolvedValueOnce(buildSummary({ recentJobs: [legacyJob], timestamp: '2026-01-01T00:00:00Z' }))
      .mockResolvedValueOnce(buildSummary({ recentJobs: [legacyJob], timestamp: '2026-01-01T00:00:01Z' }));
    api.retryIndexJob.mockRejectedValueOnce({
      response: { status: 405, data: { detail: 'Method Not Allowed' } },
    });
    api.triggerSleepConsolidation.mockResolvedValueOnce({ job_id: 'job-legacy-sleep-retry' });

    const user = userEvent.setup();
    render(<ObservabilityPage />);

    const jobCard = await getJobCardById('job-legacy-sleep');
    await user.click(within(jobCard).getByRole('button', { name: 'Retry' }));

    await waitFor(() => {
      expect(api.retryIndexJob).toHaveBeenCalledWith('job-legacy-sleep', { reason: 'retry:job-legacy-sleep' });
      expect(api.triggerSleepConsolidation).toHaveBeenCalledWith({ reason: 'retry:job-legacy-sleep', wait: false });
    });
    expect(api.triggerMemoryReindex).not.toHaveBeenCalled();
    expect(api.triggerIndexRebuild).not.toHaveBeenCalled();
    expect(await screen.findByText(/Retry requested/i)).toBeInTheDocument();
  });

  it('shows explicit error when fallback task type is unsupported', async () => {
    const unknownTaskJob = {
      job_id: 'job-unknown-task',
      status: 'failed',
      task_type: 'unknown_task_type',
      reason: 'unknown-task',
    };
    api.getObservabilitySummary.mockResolvedValue(buildSummary({ recentJobs: [unknownTaskJob] }));
    api.retryIndexJob.mockRejectedValueOnce({
      response: { status: 405, data: { detail: 'Method Not Allowed' } },
    });

    const user = userEvent.setup();
    render(<ObservabilityPage />);

    const jobCard = await getJobCardById('job-unknown-task');
    await user.click(within(jobCard).getByRole('button', { name: 'Retry' }));

    expect(api.triggerMemoryReindex).not.toHaveBeenCalled();
    expect(api.triggerIndexRebuild).not.toHaveBeenCalled();
    expect(api.triggerSleepConsolidation).not.toHaveBeenCalled();
    expect(
      await screen.findByText(
        /Retry failed \(job-unknown-task\): retry for task type 'unknown_task_type' is not supported/i,
      ),
    ).toBeInTheDocument();
  });

  it('renders runtime queue depth and last worker error', async () => {
    api.getObservabilitySummary.mockResolvedValue(
      buildSummary({
        queueDepth: 9,
        lastError: 'queue_full',
      }),
    );

    render(<ObservabilityPage />);

    expect(await screen.findByText(/queue depth:\s*9/i)).toBeInTheDocument();
    expect(screen.getByText(/last worker error:\s*queue_full/i)).toBeInTheDocument();
  });

  it('keeps latest summary state when refresh requests race', async () => {
    const user = userEvent.setup();
    const first = createDeferred();
    const second = createDeferred();
    api.getObservabilitySummary
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);

    render(<ObservabilityPage />);

    await user.click(screen.getByRole('button', { name: 'Rebuild Index' }));
    await waitFor(() => {
      expect(api.getObservabilitySummary).toHaveBeenCalledTimes(2);
    });

    second.resolve(buildSummary({ queueDepth: 2, timestamp: '2026-01-01T00:00:02Z' }));
    await screen.findByText(/queue depth:\s*2/i);

    first.resolve(buildSummary({ queueDepth: 9, timestamp: '2026-01-01T00:00:01Z' }));
    await waitFor(() => {
      expect(screen.getByText(/queue depth:\s*2/i)).toBeInTheDocument();
      expect(screen.queryByText(/queue depth:\s*9/i)).not.toBeInTheDocument();
    });
  });

  it('refreshes summary from live SSE events and closes the stream on unmount', async () => {
    const liveSource = createMockEventSource();
    vi.stubGlobal('EventSource', vi.fn(() => liveSource));
    api.getObservabilitySummary
      .mockResolvedValueOnce(buildSummary({ queueDepth: 1, timestamp: '2026-01-01T00:00:00Z' }))
      .mockResolvedValueOnce(buildSummary({ queueDepth: 4, timestamp: '2026-01-01T00:00:04Z' }));

    const { unmount } = render(<ObservabilityPage />);

    expect(await screen.findByText(/queue depth:\s*1/i)).toBeInTheDocument();

    await act(async () => {
      liveSource.emit('endpoint', { data: '/messages?session_id=live-observability' });
    });

    await waitFor(() => {
      expect(api.getObservabilitySummary).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText(/queue depth:\s*4/i)).toBeInTheDocument();

    unmount();

    expect(liveSource.close).toHaveBeenCalledTimes(1);
  });

  it('shows and clears the SSE connection lost banner from stream lifecycle events', async () => {
    const liveSource = createMockEventSource();
    vi.stubGlobal('EventSource', vi.fn(() => liveSource));

    render(<ObservabilityPage />);

    expect(await screen.findByText(/queue depth:\s*0/i)).toBeInTheDocument();

    await act(async () => {
      liveSource.emit('error', { error: new Error('transient disconnect') });
    });

    expect(screen.getByText(i18n.t('common.states.connectionLost'))).toBeInTheDocument();

    await act(async () => {
      liveSource.emit('open');
    });

    await waitFor(() => {
      expect(screen.queryByText(i18n.t('common.states.connectionLost'))).not.toBeInTheDocument();
    });
  });

  it('shows the SSE connection lost banner when stream creation fails', async () => {
    vi.stubGlobal('EventSource', undefined);
    vi.stubGlobal('fetch', undefined);

    render(<ObservabilityPage />);

    expect(await screen.findByText(/queue depth:\s*0/i)).toBeInTheDocument();
    expect(screen.getByText(i18n.t('common.states.connectionLost'))).toBeInTheDocument();
  });

  it('uses authenticated fetch-based SSE when maintenance auth is present', async () => {
    const encoder = new TextEncoder();
    api.getMaintenanceAuthState.mockReturnValue({
      key: 'week6-sse-secret',
      mode: 'header',
      source: 'runtime',
    });
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        body: new ReadableStream({
          start(controller) {
            controller.enqueue(
              encoder.encode('event: endpoint\ndata: /messages?session_id=auth-live\n\n')
            );
            controller.close();
          },
        }),
      }))
    );
    api.getObservabilitySummary
      .mockResolvedValueOnce(buildSummary({ queueDepth: 1, timestamp: '2026-01-01T00:00:00Z' }))
      .mockResolvedValueOnce(buildSummary({ queueDepth: 6, timestamp: '2026-01-01T00:00:06Z' }));

    render(<ObservabilityPage />);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/sse/'),
        expect.objectContaining({
          method: 'GET',
          headers: { 'X-MCP-API-Key': 'week6-sse-secret' },
        })
      );
    });

    await waitFor(() => {
      expect(api.getObservabilitySummary).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText(/queue depth:\s*6/i)).toBeInTheDocument();
  });

  it('re-establishes authenticated SSE after a terminal 401 when maintenance auth changes', async () => {
    const encoder = new TextEncoder();
    let authChangeListener = null;
    let maintenanceAuth = {
      key: 'expired-maintenance-key',
      mode: 'header',
      source: 'runtime',
    };
    api.getMaintenanceAuthState.mockImplementation(() => maintenanceAuth);
    api.subscribeMaintenanceAuthChanges.mockImplementation((listener) => {
      authChangeListener = listener;
      return () => {
        if (authChangeListener === listener) {
          authChangeListener = null;
        }
      };
    });
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce({
          ok: false,
          status: 401,
          body: new ReadableStream({
            start(controller) {
              controller.close();
            },
          }),
        })
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          body: new ReadableStream({
            start(controller) {
              controller.enqueue(
                encoder.encode('event: endpoint\ndata: /messages?session_id=auth-recovered\n\n')
              );
              controller.close();
            },
          }),
        })
    );
    api.getObservabilitySummary
      .mockResolvedValueOnce(buildSummary({ queueDepth: 1, timestamp: '2026-01-01T00:00:00Z' }))
      .mockResolvedValueOnce(buildSummary({ queueDepth: 8, timestamp: '2026-01-01T00:00:08Z' }));

    render(<ObservabilityPage />);

    expect(await screen.findByText(/queue depth:\s*1/i)).toBeInTheDocument();
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/sse/'),
        expect.objectContaining({
          headers: { 'X-MCP-API-Key': 'expired-maintenance-key' },
        })
      );
    });

    maintenanceAuth = {
      key: 'refreshed-maintenance-key',
      mode: 'header',
      source: 'runtime',
    };
    await act(async () => {
      authChangeListener?.(maintenanceAuth);
    });

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledTimes(2);
      expect(globalThis.fetch).toHaveBeenLastCalledWith(
        expect.stringContaining('/sse/'),
        expect.objectContaining({
          headers: { 'X-MCP-API-Key': 'refreshed-maintenance-key' },
        })
      );
    });
    await waitFor(() => {
      expect(api.getObservabilitySummary).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText(/queue depth:\s*8/i)).toBeInTheDocument();
  });

  it('re-establishes authenticated SSE after a terminal 401 when the page regains focus', async () => {
    const encoder = new TextEncoder();
    const maintenanceAuth = {
      key: 'focused-maintenance-key',
      mode: 'header',
      source: 'runtime',
    };
    api.getMaintenanceAuthState.mockReturnValue(maintenanceAuth);
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce({
          ok: false,
          status: 401,
          body: new ReadableStream({
            start(controller) {
              controller.close();
            },
          }),
        })
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          body: new ReadableStream({
            start(controller) {
              controller.enqueue(
                encoder.encode('event: endpoint\ndata: /messages?session_id=focus-recovered\n\n')
              );
              controller.close();
            },
          }),
        })
    );
    api.getObservabilitySummary
      .mockResolvedValueOnce(buildSummary({ queueDepth: 2, timestamp: '2026-01-01T00:00:00Z' }))
      .mockResolvedValueOnce(buildSummary({ queueDepth: 9, timestamp: '2026-01-01T00:00:09Z' }));

    render(<ObservabilityPage />);

    expect(await screen.findByText(/queue depth:\s*2/i)).toBeInTheDocument();
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    });

    await act(async () => {
      window.dispatchEvent(new Event('focus'));
    });

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledTimes(2);
      expect(globalThis.fetch).toHaveBeenLastCalledWith(
        expect.stringContaining('/sse/'),
        expect.objectContaining({
          headers: { 'X-MCP-API-Key': 'focused-maintenance-key' },
        })
      );
    });
    await waitFor(() => {
      expect(api.getObservabilitySummary).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText(/queue depth:\s*9/i)).toBeInTheDocument();
  });

  it('does not rebuild a healthy authenticated SSE stream when the page regains focus', async () => {
    const encoder = new TextEncoder();
    const maintenanceAuth = {
      key: 'healthy-maintenance-key',
      mode: 'header',
      source: 'runtime',
    };
    api.getMaintenanceAuthState.mockReturnValue(maintenanceAuth);
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce({
        ok: true,
        status: 200,
        body: new ReadableStream({
          start(controller) {
            controller.enqueue(
              encoder.encode('event: endpoint\ndata: /messages?session_id=focus-stable\n\n')
            );
          },
        }),
      })
    );
    api.getObservabilitySummary
      .mockResolvedValueOnce(buildSummary({ queueDepth: 3, timestamp: '2026-01-01T00:00:00Z' }))
      .mockResolvedValueOnce(buildSummary({ queueDepth: 4, timestamp: '2026-01-01T00:00:04Z' }));

    render(<ObservabilityPage />);

    expect(await screen.findByText(/queue depth:\s*3/i)).toBeInTheDocument();
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    });
    expect(await screen.findByText(/queue depth:\s*4/i)).toBeInTheDocument();

    await act(async () => {
      window.dispatchEvent(new Event('focus'));
    });

    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });

  it('blocks diagnostic search when max priority is not an integer', async () => {
    const user = userEvent.setup();
    render(<ObservabilityPage />);

    const input = await screen.findByLabelText('Max priority filter');
    await user.type(input, '1.9');
    await user.click(screen.getByRole('button', { name: /Run Diagnostic Search/i }));

    expect(api.runObservabilitySearch).not.toHaveBeenCalled();
    expect(await screen.findByText(/max priority filter must be a non-negative integer/i)).toBeInTheDocument();
  });

  it('sends max priority as an integer filter', async () => {
    const user = userEvent.setup();
    render(<ObservabilityPage />);

    const input = await screen.findByLabelText('Max priority filter');
    await user.type(input, '3');
    await user.click(screen.getByRole('button', { name: /Run Diagnostic Search/i }));

    await waitFor(() => {
      expect(api.runObservabilitySearch).toHaveBeenCalledWith(
        expect.objectContaining({
          filters: expect.objectContaining({ max_priority: 3 }),
        }),
      );
    });
  });

  it('sends scope_hint when provided', async () => {
    const user = userEvent.setup();
    render(<ObservabilityPage />);

    const input = await screen.findByLabelText('Scope hint');
    await user.type(input, 'core://agent');
    await user.click(screen.getByRole('button', { name: /Run Diagnostic Search/i }));

    await waitFor(() => {
      expect(api.runObservabilitySearch).toHaveBeenCalledWith(
        expect.objectContaining({
          scope_hint: 'core://agent',
        }),
      );
    });
  });

  it('renders sm-lite runtime metrics', async () => {
    api.getObservabilitySummary.mockResolvedValue(
      buildSummary({
        smLite: {
          storage: 'runtime_ephemeral',
          promotion_path: 'compact_context + auto_flush',
          session_cache: { session_count: 2, total_hits: 6 },
          flush_tracker: { session_count: 1, pending_events: 3 },
          degraded: false,
        },
      }),
    );

    render(<ObservabilityPage />);

    expect(await screen.findByText(/sm-lite sessions:\s*2/i)).toBeInTheDocument();
    expect(screen.getByText(/sm-lite pending events:\s*3/i)).toBeInTheDocument();
  });

  it('shows explicit message when cancel returns 404', async () => {
    const runningJob = {
      job_id: 'job-cancel-missing',
      status: 'running',
      task_type: 'reindex_memory',
      memory_id: 91,
      reason: 'cancel-missing',
    };
    api.getObservabilitySummary
      .mockResolvedValueOnce(buildSummary({ recentJobs: [runningJob], timestamp: '2026-01-01T00:00:00Z' }))
      .mockResolvedValueOnce(buildSummary({ recentJobs: [runningJob], timestamp: '2026-01-01T00:00:01Z' }));
    api.cancelIndexJob.mockRejectedValueOnce({
      message: "job 'job-cancel-missing' not found.",
      response: {
        status: 404,
        data: {
          detail: "job 'job-cancel-missing' not found.",
        },
      },
    });

    const user = userEvent.setup();
    render(<ObservabilityPage />);

    const jobCard = await getJobCardById('job-cancel-missing');
    await user.click(within(jobCard).getByRole('button', { name: 'Cancel' }));

    await waitFor(() => {
      expect(api.cancelIndexJob).toHaveBeenCalledWith('job-cancel-missing', {
        reason: 'observability_console_cancel',
      });
    });
    expect(api.getObservabilitySummary).toHaveBeenCalledTimes(2);
    expect(await screen.findByText(/Cancel skipped \(job-cancel-missing\): job not found/i)).toBeInTheDocument();
  });

  it('shows explicit message when cancel returns 409', async () => {
    const runningJob = {
      job_id: 'job-cancel-finalized',
      status: 'running',
      task_type: 'reindex_memory',
      memory_id: 92,
      reason: 'cancel-finalized',
    };
    api.getObservabilitySummary
      .mockResolvedValueOnce(buildSummary({ recentJobs: [runningJob], timestamp: '2026-01-01T00:00:00Z' }))
      .mockResolvedValueOnce(buildSummary({ recentJobs: [runningJob], timestamp: '2026-01-01T00:00:01Z' }));
    api.cancelIndexJob.mockRejectedValueOnce({
      message: 'job_already_finalized',
      response: {
        status: 409,
        data: {
          detail: 'job_already_finalized',
        },
      },
    });

    const user = userEvent.setup();
    render(<ObservabilityPage />);

    const jobCard = await getJobCardById('job-cancel-finalized');
    await user.click(within(jobCard).getByRole('button', { name: 'Cancel' }));

    await waitFor(() => {
      expect(api.cancelIndexJob).toHaveBeenCalledWith('job-cancel-finalized', {
        reason: 'observability_console_cancel',
      });
    });
    expect(api.getObservabilitySummary).toHaveBeenCalledTimes(2);
    expect(await screen.findByText(/Cancel skipped \(job-cancel-finalized\): already finalized/i)).toBeInTheDocument();
  });

  it('localizes cancel-skipped detail text in zh-CN', async () => {
    const runningJob = {
      job_id: 'job-cancel-zh',
      status: 'running',
      task_type: 'reindex_memory',
      memory_id: 94,
      reason: 'cancel-zh',
    };
    await i18n.changeLanguage('zh-CN');
    api.getObservabilitySummary
      .mockResolvedValueOnce(buildSummary({ recentJobs: [runningJob], timestamp: '2026-01-01T00:00:00Z' }))
      .mockResolvedValueOnce(buildSummary({ recentJobs: [runningJob], timestamp: '2026-01-01T00:00:01Z' }));
    api.cancelIndexJob.mockRejectedValueOnce({
      message: "job 'job-cancel-zh' not found.",
      response: {
        status: 404,
        data: {
          detail: "job 'job-cancel-zh' not found.",
        },
      },
    });

    const user = userEvent.setup();
    render(<ObservabilityPage />);

    const jobCard = await getJobCardById('job-cancel-zh');
    await user.click(within(jobCard).getByRole('button', { name: '取消' }));

    expect(await screen.findByText('取消已跳过（job-cancel-zh）：任务不存在')).toBeInTheDocument();
  });

  it('treats unknown 409 conflicts as cancel failure', async () => {
    const runningJob = {
      job_id: 'job-cancel-conflict',
      status: 'running',
      task_type: 'reindex_memory',
      memory_id: 93,
      reason: 'cancel-conflict',
    };
    api.getObservabilitySummary.mockResolvedValue(buildSummary({ recentJobs: [runningJob] }));
    api.cancelIndexJob.mockRejectedValueOnce({
      message: 'running_job_handle_unavailable',
      response: {
        status: 409,
        data: {
          detail: 'running_job_handle_unavailable',
        },
      },
    });

    const user = userEvent.setup();
    render(<ObservabilityPage />);

    const jobCard = await getJobCardById('job-cancel-conflict');
    await user.click(within(jobCard).getByRole('button', { name: 'Cancel' }));

    await waitFor(() => {
      expect(api.cancelIndexJob).toHaveBeenCalledWith('job-cancel-conflict', {
        reason: 'observability_console_cancel',
      });
    });
    expect(api.getObservabilitySummary).toHaveBeenCalledTimes(1);
    expect(
      await screen.findByText(/Cancel failed \(job-cancel-conflict\): running_job_handle_unavailable/i),
    ).toBeInTheDocument();
  });

  it('switches inspect detail between selected job and active job', async () => {
    const activeJobId = 'job-active';
    const inspectedJobId = 'job-inspect';
    const summary = buildSummary({
      activeJobId,
      recentJobs: [
        {
          job_id: inspectedJobId,
          status: 'failed',
          task_type: 'reindex_memory',
          memory_id: 42,
          reason: 'inspect-target',
        },
      ],
    });
    const jobDetails = {
      [activeJobId]: {
        job_id: activeJobId,
        status: 'running',
        task_type: 'rebuild_index',
        reason: 'active-reason',
      },
      [inspectedJobId]: {
        job_id: inspectedJobId,
        status: 'failed',
        task_type: 'reindex_memory',
        memory_id: 42,
        reason: 'inspect-reason',
      },
    };
    api.getObservabilitySummary.mockResolvedValue(summary);
    api.getIndexJob.mockImplementation(async (jobId) => ({ job: jobDetails[jobId] }));

    const user = userEvent.setup();
    render(<ObservabilityPage />);

    await screen.findByText(/reason:\s*active-reason/i);
    const inspectCard = await getJobCardById(inspectedJobId);
    await user.click(within(inspectCard).getByRole('button', { name: 'Inspect' }));
    await screen.findByText(/reason:\s*inspect-reason/i);

    expect(api.getIndexJob).toHaveBeenCalledWith(inspectedJobId);

    await user.click(screen.getByRole('button', { name: 'Back to Active' }));
    await screen.findByText(/reason:\s*active-reason/i);
    expect(api.getIndexJob).toHaveBeenLastCalledWith(activeJobId);
  });
});
