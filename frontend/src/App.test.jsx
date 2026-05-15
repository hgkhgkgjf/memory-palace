import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import userEvent from '@testing-library/user-event';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

import App, { buildRoutesKey, resolveAppBasename } from './App';
import i18n, { LOCALE_STORAGE_KEY } from './i18n';

const { memoryMountCounter, setupApi } = vi.hoisted(() => ({
  memoryMountCounter: { current: 0 },
  setupApi: {
    getSetupStatus: vi.fn(),
    saveSetupConfig: vi.fn(),
  },
}));

vi.mock('./lib/api', async () => {
  const actual = await vi.importActual('./lib/api');
  return {
    ...actual,
    getSetupStatus: setupApi.getSetupStatus,
    saveSetupConfig: setupApi.saveSetupConfig,
  };
});

vi.mock('./features/memory/MemoryBrowser', () => ({
  default: () => {
    React.useEffect(() => {
      memoryMountCounter.current += 1;
    }, []);
    return <div>memory-page</div>;
  },
}));

vi.mock('./features/review/ReviewPage', () => ({
  default: () => <div>review-page</div>,
}));

vi.mock('./features/maintenance/MaintenancePage', () => ({
  default: () => <div>maintenance-page</div>,
}));

vi.mock('./features/observability/ObservabilityPage', () => ({
  default: () => <div>observability-page</div>,
}));

const createDeferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
};

const SETUP_ASSISTANT_DISMISSED_STORAGE_KEY = 'memory-palace.setupAssistantDismissed';

const clearSetupAssistantDismissedState = () => {
  window.localStorage?.removeItem?.(SETUP_ASSISTANT_DISMISSED_STORAGE_KEY);
  window.sessionStorage?.removeItem?.(SETUP_ASSISTANT_DISMISSED_STORAGE_KEY);
};

describe('App routing', () => {
  beforeEach(async () => {
    memoryMountCounter.current = 0;
    window.localStorage?.removeItem?.('memory-palace.dashboardAuth');
    window.sessionStorage?.removeItem?.('memory-palace.dashboardAuth');
    window.localStorage?.removeItem?.(LOCALE_STORAGE_KEY);
    clearSetupAssistantDismissedState();
    window.sessionStorage?.setItem?.(SETUP_ASSISTANT_DISMISSED_STORAGE_KEY, '1');
    delete document.documentElement.dataset.browserProfile;
    delete window.__MEMORY_PALACE_RUNTIME__;
    await i18n.changeLanguage('en');
    window.localStorage?.removeItem?.(LOCALE_STORAGE_KEY);
    setupApi.getSetupStatus.mockReset();
    setupApi.saveSetupConfig.mockReset();
    setupApi.getSetupStatus.mockResolvedValue({
      ok: true,
      apply_supported: true,
      apply_reason: 'local_env_file',
      write_supported: true,
      write_reason: 'local_env_file',
      target_label: '.env',
      restart_required: true,
      restart_targets: ['backend', 'sse'],
      summary: {
        dashboard_auth_configured: false,
        allow_insecure_local: false,
        embedding_backend: 'hash',
        embedding_configured: true,
        reranker_enabled: false,
        reranker_configured: false,
        write_guard_enabled: false,
        write_guard_configured: false,
        intent_llm_enabled: false,
        intent_llm_configured: false,
      },
    });
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    window.history.pushState({}, '', '/');
  });

  it('redirects root path to memory', async () => {
    window.history.pushState({}, '', '/');

    render(<App />);

    expect(await screen.findByText('memory-page')).toBeInTheDocument();
    await waitFor(() => expect(window.location.pathname).toBe('/memory'));
  });

  it('redirects unknown paths to memory', async () => {
    window.history.pushState({}, '', '/unknown-route');

    render(<App />);

    expect(await screen.findByText('memory-page')).toBeInTheDocument();
    await waitFor(() => expect(window.location.pathname).toBe('/memory'));
  });

  it('derives a router basename from a same-origin prefixed API base', () => {
    vi.stubEnv('BASE_URL', '/');
    vi.stubEnv('VITE_API_BASE_URL', '/memory-palace/api/');

    expect(resolveAppBasename()).toBe('/memory-palace');
  });

  it('keeps redirects inside the resolved app basename', async () => {
    vi.stubEnv('BASE_URL', '/');
    vi.stubEnv('VITE_API_BASE_URL', '/memory-palace/api/');
    window.history.pushState({}, '', '/memory-palace/');

    render(<App />);

    expect(await screen.findByText('memory-page')).toBeInTheDocument();
    await waitFor(() => expect(window.location.pathname).toBe('/memory-palace/memory'));
  });

  it('stores API key through header action when runtime config is absent', async () => {
    const user = userEvent.setup();
    window.history.pushState({}, '', '/memory');

    render(<App />);

    await user.click(screen.getByRole('button', { name: i18n.t('app.auth.setApiKey') }));
    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });
    await user.type(
      within(dialog).getByPlaceholderText(i18n.t('setup.dashboard.apiKeyPlaceholder')),
      'stored-key'
    );
    await user.click(screen.getByRole('button', { name: i18n.t('setup.actions.saveBrowserOnly') }));

    expect(window.sessionStorage.getItem('memory-palace.dashboardAuth')).toContain('stored-key');
    expect(await screen.findByRole('button', { name: i18n.t('app.auth.updateApiKey') })).toBeInTheDocument();
  });

  it('keeps the setup assistant open and shows browser-only save success feedback', async () => {
    const user = userEvent.setup();
    window.history.pushState({}, '', '/memory');

    render(<App />);

    await user.click(screen.getByRole('button', { name: i18n.t('app.auth.setApiKey') }));
    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });
    await user.type(
      within(dialog).getByPlaceholderText(i18n.t('setup.dashboard.apiKeyPlaceholder')),
      'stored-key'
    );
    await user.click(within(dialog).getByRole('button', { name: i18n.t('setup.actions.saveBrowserOnly') }));

    expect(
      await within(dialog).findByText(i18n.t('setup.messages.browserOnlySaved'))
    ).toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: i18n.t('setup.title') })).toBeInTheDocument();
  });

  it('keeps browser-only dashboard auth across remounts until it is cleared', async () => {
    const user = userEvent.setup();
    window.history.pushState({}, '', '/memory');

    const firstRender = render(<App />);

    await user.click(screen.getByRole('button', { name: i18n.t('app.auth.setApiKey') }));
    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });
    await user.type(
      within(dialog).getByPlaceholderText(i18n.t('setup.dashboard.apiKeyPlaceholder')),
      'stored-key'
    );
    await user.click(screen.getByRole('button', { name: i18n.t('setup.actions.saveBrowserOnly') }));

    expect(await screen.findByRole('button', { name: i18n.t('app.auth.updateApiKey') })).toBeInTheDocument();

    firstRender.unmount();
    render(<App />);

    expect(await screen.findByRole('button', { name: i18n.t('app.auth.updateApiKey') })).toBeInTheDocument();
  });

  it('shows a browser-storage risk warning inside the setup assistant', async () => {
    const user = userEvent.setup();
    window.history.pushState({}, '', '/memory');

    render(<App />);

    await user.click(screen.getByRole('button', { name: i18n.t('app.auth.setApiKey') }));
    expect(
      await screen.findByText(/Avoid saving this key in shared browsers or profiles you do not control\./i)
    ).toBeInTheDocument();
  });

  it('shows an error instead of crashing when browser storage rejects the API key write', async () => {
    const user = userEvent.setup();
    const originalStorage = window.sessionStorage;
    window.history.pushState({}, '', '/memory');

    render(<App />);

    await user.click(screen.getByRole('button', { name: i18n.t('app.auth.setApiKey') }));
    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });
    await user.type(
      within(dialog).getByPlaceholderText(i18n.t('setup.dashboard.apiKeyPlaceholder')),
      'stored-key'
    );
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

    await user.click(screen.getByRole('button', { name: i18n.t('setup.actions.saveBrowserOnly') }));
    Object.defineProperty(window, 'sessionStorage', {
      configurable: true,
      writable: true,
      value: originalStorage,
    });

    expect((await screen.findAllByText(i18n.t('setup.messages.saveFailed'))).length).toBeGreaterThan(0);
    expect(screen.getByRole('dialog', { name: i18n.t('setup.title') })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: i18n.t('app.auth.setApiKey') })).toBeInTheDocument();
  });

  it('shows an error instead of a false success when server save succeeds but browser auth persistence fails', async () => {
    const user = userEvent.setup();
    const originalStorage = window.sessionStorage;
    window.history.pushState({}, '', '/memory');
    setupApi.saveSetupConfig.mockResolvedValueOnce({
      ok: true,
      target_label: '.env',
      restart_targets: ['backend', 'sse'],
    });

    render(<App />);

    await user.click(screen.getByRole('button', { name: i18n.t('app.auth.setApiKey') }));
    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });
    await user.type(
      within(dialog).getByPlaceholderText(i18n.t('setup.dashboard.apiKeyPlaceholder')),
      'stored-key'
    );

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

    try {
      await user.click(screen.getByRole('button', { name: i18n.t('setup.actions.saveEnv') }));

      expect((await screen.findAllByText(i18n.t('setup.messages.saveFailed'))).length).toBeGreaterThan(0);
      expect(screen.queryByText(i18n.t('setup.messages.serverSaved', { target: '.env' }))).not.toBeInTheDocument();
      expect(screen.getByRole('dialog', { name: i18n.t('setup.title') })).toBeInTheDocument();
      expect(window.sessionStorage.getItem('memory-palace.dashboardAuth')).toBeNull();
      expect(setupApi.saveSetupConfig).toHaveBeenCalledTimes(1);
    } finally {
      Object.defineProperty(window, 'sessionStorage', {
        configurable: true,
        writable: true,
        value: originalStorage,
      });
    }
  });

  it('shows server save success and persists browser auth when both succeed', async () => {
    const user = userEvent.setup();
    window.history.pushState({}, '', '/memory');
    setupApi.saveSetupConfig.mockResolvedValueOnce({
      ok: true,
      target_label: '.env',
      restart_targets: ['backend', 'sse'],
    });

    render(<App />);

    await user.click(screen.getByRole('button', { name: i18n.t('app.auth.setApiKey') }));
    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });
    await user.type(
      within(dialog).getByPlaceholderText(i18n.t('setup.dashboard.apiKeyPlaceholder')),
      'stored-key'
    );

    await user.click(screen.getByRole('button', { name: i18n.t('setup.actions.saveEnv') }));

    expect(
      (
        await within(dialog).findAllByText((_, node) =>
          node?.textContent?.includes(i18n.t('setup.messages.serverSaved', { target: '.env' }))
        )
      ).length
    ).toBeGreaterThan(0);
    expect(window.sessionStorage.getItem('memory-palace.dashboardAuth')).toContain('stored-key');
    expect(setupApi.saveSetupConfig).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: i18n.t('app.auth.updateApiKey') })).toBeInTheDocument();
  });

  it('persists the current runtime dashboard key when saving local env settings', async () => {
    const user = userEvent.setup();
    window.history.pushState({}, '', '/memory');
    window.__MEMORY_PALACE_RUNTIME__ = {
      maintenanceApiKey: 'runtime-key',
      maintenanceApiKeyMode: 'bearer',
    };
    setupApi.saveSetupConfig.mockResolvedValueOnce({
      ok: true,
      target_label: '.env',
      restart_targets: ['backend', 'sse'],
    });

    render(<App />);

    await user.click(screen.getByRole('button', { name: i18n.t('app.auth.openSetup') }));
    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });

    expect(
      within(dialog).getByPlaceholderText(i18n.t('setup.dashboard.apiKeyPlaceholder'))
    ).toHaveValue('runtime-key');

    await user.click(within(dialog).getByRole('button', { name: i18n.t('setup.actions.saveEnv') }));

    expect(setupApi.saveSetupConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        dashboard_api_key: 'runtime-key',
      })
    );
    expect(window.sessionStorage.getItem('memory-palace.dashboardAuth')).toContain('runtime-key');
  });

  it('clears stored browser auth when the dashboard key is emptied before local env save', async () => {
    const user = userEvent.setup();
    window.history.pushState({}, '', '/memory');
    window.sessionStorage.setItem(
      'memory-palace.dashboardAuth',
      JSON.stringify({
        maintenanceApiKey: 'stored-key',
        maintenanceApiKeyMode: 'header',
        preferStoredOverRuntime: true,
      })
    );
    setupApi.saveSetupConfig.mockResolvedValueOnce({
      ok: true,
      target_label: '.env',
      restart_targets: ['backend', 'sse'],
    });

    render(<App />);

    await user.click(screen.getByRole('button', { name: i18n.t('app.auth.updateApiKey') }));
    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });
    const apiKeyInput = within(dialog).getByPlaceholderText(i18n.t('setup.dashboard.apiKeyPlaceholder'));

    await user.clear(apiKeyInput);
    await user.click(within(dialog).getByRole('button', { name: i18n.t('setup.actions.saveEnv') }));

    expect(setupApi.saveSetupConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        dashboard_api_key: '',
      })
    );
    expect(window.sessionStorage.getItem('memory-palace.dashboardAuth')).toBeNull();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: i18n.t('app.auth.setApiKey') })).toBeInTheDocument();
    });
  });

  it('disables local .env save when setup status is authenticated-but-not-loopback', async () => {
    const user = userEvent.setup();
    window.history.pushState({}, '', '/memory');
    setupApi.getSetupStatus.mockResolvedValue({
      ok: true,
      apply_supported: true,
      apply_reason: 'local_env_file',
      write_supported: false,
      write_reason: 'local_loopback_required_for_write',
      target_label: '.env',
      restart_required: true,
      restart_targets: ['backend', 'sse'],
      summary: {
        dashboard_auth_configured: true,
        allow_insecure_local: false,
        embedding_backend: 'hash',
        embedding_configured: true,
        reranker_enabled: false,
        reranker_configured: false,
        write_guard_enabled: false,
        write_guard_configured: false,
        intent_llm_enabled: false,
        intent_llm_configured: false,
      },
    });

    render(<App />);

    await user.click(screen.getByRole('button', { name: i18n.t('app.auth.setApiKey') }));
    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });
    const saveButton = within(dialog).getByRole('button', { name: i18n.t('setup.actions.saveEnv') });

    await waitFor(() => expect(saveButton).toBeDisabled());
    expect(
      await within(dialog).findByText(i18n.t('setup.reasons.local_loopback_required_for_write'))
    ).toBeInTheDocument();
  });

  it('disables local .env save when setup status requires api key for loopback write', async () => {
    const user = userEvent.setup();
    window.history.pushState({}, '', '/memory');
    setupApi.getSetupStatus.mockResolvedValue({
      ok: true,
      apply_supported: true,
      apply_reason: 'local_env_file',
      write_supported: false,
      write_reason: 'local_api_key_required_for_write',
      target_label: '.env',
      restart_required: true,
      restart_targets: ['backend', 'sse'],
      summary: {
        dashboard_auth_configured: true,
        allow_insecure_local: false,
        embedding_backend: 'hash',
        embedding_configured: true,
        reranker_enabled: false,
        reranker_configured: false,
        write_guard_enabled: false,
        write_guard_configured: false,
        intent_llm_enabled: false,
        intent_llm_configured: false,
      },
    });

    render(<App />);

    await user.click(screen.getByRole('button', { name: i18n.t('app.auth.setApiKey') }));
    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });
    const saveButton = within(dialog).getByRole('button', { name: i18n.t('setup.actions.saveEnv') });

    await waitFor(() => expect(saveButton).toBeDisabled());
    expect(
      await within(dialog).findByText(i18n.t('setup.reasons.local_api_key_required_for_write'))
    ).toBeInTheDocument();
  });

  it('remounts routes after stored auth changes without depending on raw key text', async () => {
    const user = userEvent.setup();
    window.history.pushState({}, '', '/memory');

    render(<App />);
    expect(await screen.findByText('memory-page')).toBeInTheDocument();
    await waitFor(() => expect(memoryMountCounter.current).toBe(1));

    await user.click(screen.getByRole('button', { name: i18n.t('app.auth.setApiKey') }));
    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });
    await user.type(
      within(dialog).getByPlaceholderText(i18n.t('setup.dashboard.apiKeyPlaceholder')),
      'stored-key'
    );
    await user.click(screen.getByRole('button', { name: i18n.t('setup.actions.saveBrowserOnly') }));

    await waitFor(() => expect(memoryMountCounter.current).toBe(2));
  });

  it('defaults to english when no stored locale exists', async () => {
    window.history.pushState({}, '', '/memory');

    render(<App />);

    expect(await screen.findByRole('button', { name: 'Set API key' })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe('en');
  });

  it('shows runtime status badge when runtime config is present', async () => {
    window.history.pushState({}, '', '/memory');
    window.__MEMORY_PALACE_RUNTIME__ = {
      maintenanceApiKey: 'runtime-key',
      maintenanceApiKeyMode: 'header',
    };

    render(<App />);

    expect(await screen.findByText(i18n.t('app.auth.runtimeBadge'))).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: i18n.t('app.auth.setApiKey') })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: i18n.t('app.auth.openSetup') })).toBeInTheDocument();
  });

  it('switches dashboard visuals into lite mode for Edge', async () => {
    const originalUserAgent = window.navigator.userAgent;
    window.history.pushState({}, '', '/memory');

    Object.defineProperty(window.navigator, 'userAgent', {
      configurable: true,
      value:
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0',
    });

    try {
      const { container } = render(<App />);

      expect(await screen.findByTestId('fluid-background-static')).toBeInTheDocument();
      expect(container.firstChild).toHaveAttribute('data-browser-performance', 'lite');
      await waitFor(() => {
        expect(document.documentElement.dataset.browserProfile).toBe('edge');
      });
    } finally {
      Object.defineProperty(window.navigator, 'userAgent', {
        configurable: true,
        value: originalUserAgent,
      });
    }
  });

  it('toggles language and persists the selection across remounts', async () => {
    const user = userEvent.setup();
    window.history.pushState({}, '', '/memory');

    const firstRender = render(<App />);

    expect(await screen.findByRole('button', { name: 'Set API key' })).toBeInTheDocument();
    await user.click(screen.getByTestId('language-toggle'));

    expect(await screen.findByRole('button', { name: '设置 API 密钥' })).toBeInTheDocument();
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('zh-CN');

    firstRender.unmount();

    render(<App />);

    expect(await screen.findByRole('button', { name: '设置 API 密钥' })).toBeInTheDocument();
  });

  it('keeps header language and auth buttons from collapsing their labels on narrow screens', async () => {
    window.history.pushState({}, '', '/memory');

    render(<App />);

    const languageToggle = await screen.findByTestId('language-toggle');
    const authButton = screen.getByTestId('auth-set-api-key');

    expect(languageToggle.className).toContain('shrink-0');
    expect(languageToggle.className).toContain('whitespace-nowrap');
    expect(authButton.className).toContain('shrink-0');
    expect(authButton.className).toContain('whitespace-nowrap');
  });

  it('auto-opens setup assistant on first load when no auth is configured', async () => {
    clearSetupAssistantDismissedState();
    window.history.pushState({}, '', '/memory');

    render(<App />);

    expect(await screen.findByRole('dialog', { name: i18n.t('setup.title') })).toBeInTheDocument();
  });

  it('migrates legacy setup assistant dismissal into sessionStorage', async () => {
    window.localStorage.setItem(SETUP_ASSISTANT_DISMISSED_STORAGE_KEY, '1');
    window.sessionStorage.removeItem(SETUP_ASSISTANT_DISMISSED_STORAGE_KEY);
    window.history.pushState({}, '', '/memory');

    render(<App />);

    expect(await screen.findByText('memory-page')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: i18n.t('setup.title') })).not.toBeInTheDocument();
    });
    expect(window.sessionStorage.getItem(SETUP_ASSISTANT_DISMISSED_STORAGE_KEY)).toBe('1');
    expect(window.localStorage.getItem(SETUP_ASSISTANT_DISMISSED_STORAGE_KEY)).toBeNull();
  });

  it('does not auto-open setup assistant when runtime auth is already present', async () => {
    clearSetupAssistantDismissedState();
    window.history.pushState({}, '', '/memory');
    window.__MEMORY_PALACE_RUNTIME__ = {
      maintenanceApiKey: 'runtime-key',
      maintenanceApiKeyMode: 'header',
    };

    render(<App />);

    expect(await screen.findByText(i18n.t('app.auth.runtimeBadge'))).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: i18n.t('setup.title') })).not.toBeInTheDocument();
    });
  });

  it('does not auto-open setup assistant when proxy-held auth is already effective', async () => {
    clearSetupAssistantDismissedState();
    window.history.pushState({}, '', '/memory');
    setupApi.getSetupStatus.mockResolvedValue({
      ok: true,
      apply_supported: true,
      apply_reason: 'local_env_file',
      write_supported: false,
      write_reason: 'local_loopback_required_for_write',
      target_label: '.env',
      restart_required: true,
      restart_targets: ['backend', 'sse'],
      summary: {
        dashboard_auth_configured: true,
        allow_insecure_local: false,
        embedding_backend: 'hash',
        embedding_configured: true,
        reranker_enabled: false,
        reranker_configured: false,
        write_guard_enabled: false,
        write_guard_configured: false,
        intent_llm_enabled: false,
        intent_llm_configured: false,
      },
    });

    render(<App />);

    expect(await screen.findByText('memory-page')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: i18n.t('setup.title') })).not.toBeInTheDocument();
    });
  });

  it('allows switching language from inside the setup assistant on first load', async () => {
    const user = userEvent.setup();
    clearSetupAssistantDismissedState();
    window.history.pushState({}, '', '/memory');

    render(<App />);

    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });
    expect(within(dialog).getByText('Configure Memory Palace')).toBeInTheDocument();

    await user.click(within(dialog).getByTestId('setup-language-toggle'));

    expect(await screen.findByRole('dialog', { name: '配置 Memory Palace' })).toBeInTheDocument();
    const translatedDialog = screen.getByRole('dialog', { name: '配置 Memory Palace' });
    expect(within(translatedDialog).getByText('首启配置')).toBeInTheDocument();
    expect(
      within(translatedDialog).getByRole('button', { name: '档位 A · 纯关键词' })
    ).toBeInTheDocument();
    expect(
      within(translatedDialog).getByRole('button', { name: '档位 B · 混合检索 + hash' })
    ).toBeInTheDocument();
    expect(
      within(translatedDialog).queryByRole('button', { name: /^(Profile B|Profile C|Profile D)\b/ })
    ).not.toBeInTheDocument();
  });

  it('keeps typed setup values when switching language inside the setup assistant', async () => {
    const user = userEvent.setup();
    clearSetupAssistantDismissedState();
    window.history.pushState({}, '', '/memory');

    render(<App />);

    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });
    const apiKeyInput = within(dialog).getByPlaceholderText(i18n.t('setup.dashboard.apiKeyPlaceholder'));

    await user.type(apiKeyInput, 'typed-key-123');
    await user.click(within(dialog).getByTestId('setup-language-toggle'));

    const translatedDialog = await screen.findByRole('dialog', { name: '配置 Memory Palace' });
    expect(within(translatedDialog).getByDisplayValue('typed-key-123')).toBeInTheDocument();
  });

  it('hydrates the real hash retrieval state when setup is opened manually', async () => {
    const user = userEvent.setup();
    window.history.pushState({}, '', '/memory');
    setupApi.getSetupStatus.mockResolvedValue({
      ok: true,
      apply_supported: true,
      apply_reason: 'local_env_file',
      write_supported: true,
      write_reason: 'local_env_file',
      target_label: '.env',
      restart_required: true,
      restart_targets: ['backend', 'sse'],
      summary: {
        dashboard_auth_configured: true,
        allow_insecure_local: false,
        embedding_backend: 'hash',
        embedding_configured: true,
        reranker_enabled: false,
        reranker_configured: false,
        write_guard_enabled: false,
        write_guard_configured: false,
        intent_llm_enabled: false,
        intent_llm_configured: false,
      },
    });

    render(<App />);

    await user.click(screen.getByRole('button', { name: i18n.t('app.auth.setApiKey') }));
    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });

    await waitFor(() => {
      expect(within(dialog).getByRole('combobox')).toHaveValue('hash');
    });
  });

  it('starts the setup assistant on the documented Profile A baseline instead of an unnamed hash state', async () => {
    clearSetupAssistantDismissedState();
    window.history.pushState({}, '', '/memory');

    render(<App />);

    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });

    expect(
      within(dialog).getByRole('button', { name: i18n.t('setup.retrieval.presets.a') })
    ).toBeInTheDocument();
    expect(within(dialog).getByRole('combobox')).toHaveValue('none');
    expect(
      within(dialog).getByRole('checkbox', {
        name: new RegExp(`^${i18n.t('setup.retrieval.rerankerEnabledLabel')}`),
      })
    ).not.toBeChecked();
  });

  it('relocalizes setup assistant status errors when switching language', async () => {
    const user = userEvent.setup();
    clearSetupAssistantDismissedState();
    window.history.pushState({}, '', '/memory');
    setupApi.getSetupStatus.mockRejectedValueOnce({
      message: 'Request failed with status code 500',
    });

    render(<App />);

    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });
    expect(await within(dialog).findByText('Request failed with status code 500')).toBeInTheDocument();

    await user.click(within(dialog).getByTestId('setup-language-toggle'));

    const translatedDialog = await screen.findByRole('dialog', { name: '配置 Memory Palace' });
    expect(await within(translatedDialog).findByText('请求失败（状态码 500）')).toBeInTheDocument();
  });

  it('focuses the dashboard API key input when the setup assistant opens', async () => {
    clearSetupAssistantDismissedState();
    window.history.pushState({}, '', '/memory');

    render(<App />);

    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });
    const apiKeyInput = within(dialog).getByPlaceholderText(i18n.t('setup.dashboard.apiKeyPlaceholder'));

    await waitFor(() => {
      expect(apiKeyInput).toHaveFocus();
    });
  });

  it('closes the setup assistant when Escape is pressed inside the dialog', async () => {
    clearSetupAssistantDismissedState();
    window.history.pushState({}, '', '/memory');

    render(<App />);

    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });
    const apiKeyInput = within(dialog).getByPlaceholderText(i18n.t('setup.dashboard.apiKeyPlaceholder'));

    fireEvent.keyDown(apiKeyInput, { key: 'Escape' });

    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: i18n.t('setup.title') })).not.toBeInTheDocument();
    });
  });

  it('traps keyboard tab navigation inside the setup assistant', async () => {
    clearSetupAssistantDismissedState();
    window.history.pushState({}, '', '/memory');

    render(<App />);

    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });
    const firstFocusable = within(dialog).getByTestId('setup-language-toggle');
    const closeButtons = within(dialog).getAllByRole('button', { name: i18n.t('setup.actions.close') });
    const lastFocusable = closeButtons[closeButtons.length - 1];

    firstFocusable.focus();
    fireEvent.keyDown(firstFocusable, { key: 'Tab', shiftKey: true });
    expect(lastFocusable).toHaveFocus();

    fireEvent.keyDown(lastFocusable, { key: 'Tab' });
    expect(firstFocusable).toHaveFocus();
  });

  it('maps setup profile presets to the documented B/C/D retrieval shapes', async () => {
    const user = userEvent.setup();
    clearSetupAssistantDismissedState();
    window.history.pushState({}, '', '/memory');

    render(<App />);

    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });
    const embeddingBackend = within(dialog).getByRole('combobox');
    const rerankerToggle = within(dialog).getByRole('checkbox', {
      name: new RegExp(`^${i18n.t('setup.retrieval.rerankerEnabledLabel')}`),
    });

    await user.click(within(dialog).getByRole('button', { name: i18n.t('setup.retrieval.presets.b') }));
    expect(embeddingBackend).toHaveValue('hash');
    expect(rerankerToggle).not.toBeChecked();
    expect(within(dialog).queryByPlaceholderText(i18n.t('setup.retrieval.routerApiBasePlaceholder'))).not.toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: i18n.t('setup.retrieval.presets.c') }));
    expect(embeddingBackend).toHaveValue('router');
    expect(rerankerToggle).toBeChecked();
    expect(
      within(dialog).getByDisplayValue('http://127.0.0.1:8001/v1')
    ).toBeInTheDocument();
    expect(within(dialog).queryByPlaceholderText(i18n.t('setup.retrieval.embeddingApiBasePlaceholder'))).not.toBeInTheDocument();
    expect(within(dialog).queryByPlaceholderText(i18n.t('setup.retrieval.rerankerApiBasePlaceholder'))).not.toBeInTheDocument();
    expect(
      within(dialog).getByLabelText(i18n.t('setup.retrieval.embeddingDimLabel'))
    ).toHaveValue(null);

    await user.click(within(dialog).getByRole('button', { name: i18n.t('setup.retrieval.presets.d') }));
    expect(embeddingBackend).toHaveValue('router');
    expect(rerankerToggle).toBeChecked();
    expect(
      within(dialog).getByDisplayValue('https://router.example.com/v1')
    ).toBeInTheDocument();
  });

  it('does not auto-fill embedding dimensions when switching from hash to remote backends', async () => {
    const user = userEvent.setup();
    clearSetupAssistantDismissedState();
    window.history.pushState({}, '', '/memory');

    render(<App />);

    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });

    await user.click(within(dialog).getByRole('button', { name: i18n.t('setup.retrieval.presets.b') }));
    await user.selectOptions(within(dialog).getByRole('combobox'), 'api');
    let embeddingDimInput = within(dialog).getByLabelText(i18n.t('setup.retrieval.embeddingDimLabel'));
    expect(embeddingDimInput).toHaveValue(null);

    await user.click(within(dialog).getByRole('button', { name: i18n.t('setup.retrieval.presets.c') }));
    embeddingDimInput = within(dialog).getByLabelText(i18n.t('setup.retrieval.embeddingDimLabel'));
    expect(embeddingDimInput).toHaveValue(null);
  });

  it('blocks saving preset C until required remote retrieval fields are real values', async () => {
    const user = userEvent.setup();
    clearSetupAssistantDismissedState();
    window.history.pushState({}, '', '/memory');

    render(<App />);

    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });
    const saveButton = within(dialog).getByRole('button', { name: i18n.t('setup.actions.saveEnv') });

    await user.click(within(dialog).getByRole('button', { name: i18n.t('setup.retrieval.presets.c') }));
    expect(saveButton).toBeDisabled();

    await user.type(
      within(dialog).getByLabelText(i18n.t('setup.retrieval.routerEmbeddingModelLabel')),
      'router-embed-model'
    );
    await user.type(
      within(dialog).getByLabelText(i18n.t('setup.retrieval.routerRerankerModelLabel')),
      'router-reranker-live'
    );

    await waitFor(() => expect(saveButton).toBeDisabled());
    await user.type(
      within(dialog).getByLabelText(i18n.t('setup.retrieval.embeddingDimLabel')),
      '1024'
    );

    await waitFor(() => expect(saveButton).not.toBeDisabled());
  });

  it('requires an embedding dimension before api backend config can be saved', async () => {
    const user = userEvent.setup();
    clearSetupAssistantDismissedState();
    window.history.pushState({}, '', '/memory');

    render(<App />);

    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });
    const saveButton = within(dialog).getByRole('button', { name: i18n.t('setup.actions.saveEnv') });

    await user.selectOptions(within(dialog).getByRole('combobox'), 'api');
    await user.type(
      within(dialog).getByLabelText(i18n.t('setup.retrieval.embeddingApiBaseLabel')),
      'https://emb.example/v1'
    );
    await user.type(
      within(dialog).getByLabelText(i18n.t('setup.retrieval.embeddingModelLabel')),
      'text-embedding-live'
    );
    await user.clear(within(dialog).getByLabelText(i18n.t('setup.retrieval.embeddingDimLabel')));

    await waitFor(() => expect(saveButton).toBeDisabled());
    expect(setupApi.saveSetupConfig).not.toHaveBeenCalled();
  });

  it.each([
    ['api', '0'],
    ['api', 'NaN'],
    ['router', '-1'],
    ['openai', '1.5'],
  ])('rejects invalid embedding dimensions for %s backends: %s', async (backend, invalidDim) => {
    const user = userEvent.setup();
    clearSetupAssistantDismissedState();
    window.history.pushState({}, '', '/memory');

    render(<App />);

    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });
    const saveButton = within(dialog).getByRole('button', { name: i18n.t('setup.actions.saveEnv') });

    if (backend === 'router') {
      await user.click(within(dialog).getByRole('button', { name: i18n.t('setup.retrieval.presets.c') }));
      await user.type(
        within(dialog).getByLabelText(i18n.t('setup.retrieval.routerEmbeddingModelLabel')),
        'router-embed-live'
      );
      await user.type(
        within(dialog).getByLabelText(i18n.t('setup.retrieval.routerRerankerModelLabel')),
        'router-rerank-live'
      );
    } else {
      await user.selectOptions(within(dialog).getByRole('combobox'), backend);
      await user.type(
        within(dialog).getByLabelText(i18n.t('setup.retrieval.embeddingApiBaseLabel')),
        backend === 'openai' ? 'https://api.openai.com/v1' : 'https://emb.example/v1'
      );
      await user.type(
        within(dialog).getByLabelText(i18n.t('setup.retrieval.embeddingModelLabel')),
        backend === 'openai' ? 'text-embedding-3-large' : 'text-embedding-live'
      );
    }

    fireEvent.change(within(dialog).getByLabelText(i18n.t('setup.retrieval.embeddingDimLabel')), {
      target: { value: invalidDim },
    });

    await waitFor(() => expect(saveButton).toBeDisabled());
    expect(setupApi.saveSetupConfig).not.toHaveBeenCalled();
  });

  it('supports the openai embedding backend and sends a provider-specific embedding dimension', async () => {
    const user = userEvent.setup();
    clearSetupAssistantDismissedState();
    window.history.pushState({}, '', '/memory');
    setupApi.saveSetupConfig.mockResolvedValueOnce({
      ok: true,
      target_label: '.env',
      restart_targets: ['backend', 'sse'],
    });

    render(<App />);

    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });
    await user.selectOptions(
      within(dialog).getByRole('combobox'),
      'openai'
    );

    await user.type(
      within(dialog).getByLabelText(i18n.t('setup.retrieval.embeddingApiBaseLabel')),
      'https://api.openai.com/v1'
    );
    await user.type(
      within(dialog).getByLabelText(i18n.t('setup.retrieval.embeddingModelLabel')),
      'text-embedding-3-large'
    );
    await user.clear(within(dialog).getByLabelText(i18n.t('setup.retrieval.embeddingDimLabel')));
    await user.type(
      within(dialog).getByLabelText(i18n.t('setup.retrieval.embeddingDimLabel')),
      '3072'
    );

    await user.click(within(dialog).getByRole('button', { name: i18n.t('setup.actions.saveEnv') }));

    expect(setupApi.saveSetupConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        embedding_backend: 'openai',
        embedding_api_base: 'https://api.openai.com/v1',
        embedding_model: 'text-embedding-3-large',
        embedding_dim: 3072,
      })
    );
  });

  it('hydrates untouched retrieval status fields even if the user types a dashboard key before setup status resolves', async () => {
    const user = userEvent.setup();
    const setupStatusDeferred = createDeferred();
    window.history.pushState({}, '', '/memory');
    setupApi.getSetupStatus.mockReset();
    setupApi.getSetupStatus.mockReturnValue(setupStatusDeferred.promise);
    setupApi.saveSetupConfig.mockResolvedValueOnce({
      ok: true,
      target_label: '.env',
      restart_targets: ['backend', 'sse'],
    });

    render(<App />);

    await user.click(screen.getByRole('button', { name: i18n.t('app.auth.setApiKey') }));
    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });
    await user.type(
      within(dialog).getByPlaceholderText(i18n.t('setup.dashboard.apiKeyPlaceholder')),
      'typed-before-status'
    );

    setupStatusDeferred.resolve({
      ok: true,
      apply_supported: true,
      apply_reason: 'local_env_file',
      write_supported: true,
      write_reason: 'local_env_file',
      target_label: '.env',
      restart_required: true,
      restart_targets: ['backend', 'sse'],
      summary: {
        dashboard_auth_configured: false,
        allow_insecure_local: false,
        embedding_backend: 'router',
        embedding_dim: 1024,
        embedding_configured: true,
        reranker_enabled: true,
        reranker_configured: true,
        write_guard_enabled: false,
        write_guard_configured: false,
        intent_llm_enabled: false,
        intent_llm_configured: false,
      },
    });

    await waitFor(() => {
      expect(within(dialog).getByRole('combobox')).toHaveValue('router');
    });
    expect(
      within(dialog).getByRole('checkbox', {
        name: new RegExp(`^${i18n.t('setup.retrieval.rerankerEnabledLabel')}`),
      })
    ).toBeChecked();
    expect(within(dialog).getByDisplayValue('typed-before-status')).toBeInTheDocument();

    await user.type(
      within(dialog).getByLabelText(i18n.t('setup.retrieval.routerApiBaseLabel')),
      'http://127.0.0.1:8001/v1'
    );
    await user.type(
      within(dialog).getByLabelText(i18n.t('setup.retrieval.routerEmbeddingModelLabel')),
      'local-router-embed'
    );
    await user.type(
      within(dialog).getByLabelText(i18n.t('setup.retrieval.routerRerankerModelLabel')),
      'local-router-rerank'
    );

    await user.click(within(dialog).getByRole('button', { name: i18n.t('setup.actions.saveEnv') }));

    expect(setupApi.saveSetupConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        dashboard_api_key: 'typed-before-status',
        embedding_backend: 'router',
        embedding_dim: 1024,
        reranker_enabled: true,
        router_api_base: 'http://127.0.0.1:8001/v1',
        router_embedding_model: 'local-router-embed',
        router_reranker_model: 'local-router-rerank',
      })
    );
  });

  it('allows the real local router endpoint but still blocks example router model ids', async () => {
    const user = userEvent.setup();
    clearSetupAssistantDismissedState();
    window.history.pushState({}, '', '/memory');

    render(<App />);

    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });
    const saveButton = within(dialog).getByRole('button', { name: i18n.t('setup.actions.saveEnv') });

    await user.click(within(dialog).getByRole('button', { name: i18n.t('setup.retrieval.presets.c') }));
    expect(saveButton).toBeDisabled();

    await user.type(
      within(dialog).getByLabelText(i18n.t('setup.retrieval.routerEmbeddingModelLabel')),
      'router-embedding-model'
    );
    await user.type(
      within(dialog).getByLabelText(i18n.t('setup.retrieval.routerRerankerModelLabel')),
      'router-reranker-model'
    );

    await waitFor(() => expect(saveButton).toBeDisabled());

    await user.clear(within(dialog).getByLabelText(i18n.t('setup.retrieval.routerEmbeddingModelLabel')));
    await user.type(
      within(dialog).getByLabelText(i18n.t('setup.retrieval.routerEmbeddingModelLabel')),
      'local-router-embed'
    );
    await user.clear(within(dialog).getByLabelText(i18n.t('setup.retrieval.routerRerankerModelLabel')));
    await user.type(
      within(dialog).getByLabelText(i18n.t('setup.retrieval.routerRerankerModelLabel')),
      'local-router-rerank'
    );
    await user.type(
      within(dialog).getByLabelText(i18n.t('setup.retrieval.embeddingDimLabel')),
      '1024'
    );

    await waitFor(() => expect(saveButton).not.toBeDisabled());
  });

  it('clears hidden router fallback fields when switching back to preset B before saving', async () => {
    const user = userEvent.setup();
    clearSetupAssistantDismissedState();
    window.history.pushState({}, '', '/memory');
    setupApi.saveSetupConfig.mockResolvedValueOnce({
      ok: true,
      target_label: '.env',
      restart_targets: ['backend', 'sse'],
    });

    render(<App />);

    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });

    await user.click(within(dialog).getByRole('button', { name: i18n.t('setup.retrieval.presets.c') }));

    await user.type(
      within(dialog).getByPlaceholderText(i18n.t('setup.retrieval.routerApiBasePlaceholder')),
      'https://router.example/v1'
    );
    await user.type(
      within(dialog).getByPlaceholderText(i18n.t('setup.retrieval.routerApiKeyPlaceholder')),
      'router-secret'
    );
    await user.type(
      within(dialog).getByPlaceholderText(i18n.t('setup.retrieval.routerEmbeddingModelPlaceholder')),
      'router-embed-model'
    );
    await user.type(
      within(dialog).getByPlaceholderText(i18n.t('setup.retrieval.routerRerankerModelPlaceholder')),
      'router-reranker-model'
    );
    await user.click(
      within(dialog).getByRole('checkbox', {
        name: new RegExp(`^${i18n.t('setup.llm.writeGuardEnabledLabel')}`),
      })
    );
    await user.type(
      within(dialog).getByPlaceholderText(i18n.t('setup.llm.writeGuardApiBasePlaceholder')),
      'https://llm.example/write-guard'
    );
    await user.type(
      within(dialog).getByPlaceholderText(i18n.t('setup.llm.writeGuardModelPlaceholder')),
      'write-guard-model'
    );
    await user.type(
      within(dialog).getByPlaceholderText(i18n.t('setup.llm.writeGuardApiKeyPlaceholder')),
      'write-guard-key'
    );
    await user.click(
      within(dialog).getByRole('checkbox', {
        name: new RegExp(`^${i18n.t('setup.llm.intentEnabledLabel')}`),
      })
    );
    await user.type(
      within(dialog).getByPlaceholderText(i18n.t('setup.llm.intentApiBasePlaceholder')),
      'https://llm.example/intent'
    );
    await user.type(
      within(dialog).getByPlaceholderText(i18n.t('setup.llm.intentModelPlaceholder')),
      'intent-model'
    );
    await user.type(
      within(dialog).getByPlaceholderText(i18n.t('setup.llm.intentApiKeyPlaceholder')),
      'intent-key'
    );
    await user.type(
      within(dialog).getByPlaceholderText(i18n.t('setup.llm.routerChatModelPlaceholder')),
      'router-chat-model'
    );

    expect(within(dialog).getByDisplayValue('router-chat-model')).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: i18n.t('setup.retrieval.presets.b') }));

    expect(
      within(dialog).queryByPlaceholderText(i18n.t('setup.retrieval.routerApiBasePlaceholder'))
    ).not.toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: i18n.t('setup.actions.saveEnv') }));

    expect(setupApi.saveSetupConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        embedding_backend: 'hash',
        reranker_enabled: false,
        router_api_base: '',
        router_api_key: '',
        router_embedding_model: '',
        router_reranker_model: '',
        write_guard_llm_enabled: false,
        write_guard_llm_api_base: '',
        write_guard_llm_api_key: '',
        write_guard_llm_model: '',
        intent_llm_enabled: false,
        intent_llm_api_base: '',
        intent_llm_api_key: '',
        intent_llm_model: '',
        router_chat_model: '',
      })
    );
  });

  it('saves preset B from the documented baseline without remote residue', async () => {
    const user = userEvent.setup();
    clearSetupAssistantDismissedState();
    window.history.pushState({}, '', '/memory');
    setupApi.saveSetupConfig.mockResolvedValueOnce({
      ok: true,
      target_label: '.env',
      restart_targets: ['backend', 'sse'],
      summary: {
        dashboard_auth_configured: true,
        allow_insecure_local: false,
        embedding_backend: 'hash',
        embedding_configured: true,
        reranker_enabled: false,
        reranker_configured: false,
        write_guard_enabled: false,
        write_guard_configured: false,
        intent_llm_enabled: false,
        intent_llm_configured: false,
      },
    });

    render(<App />);

    const dialog = await screen.findByRole('dialog', { name: i18n.t('setup.title') });
    await user.type(
      within(dialog).getByPlaceholderText(i18n.t('setup.dashboard.apiKeyPlaceholder')),
      'local-secret'
    );

    await user.click(within(dialog).getByRole('button', { name: i18n.t('setup.retrieval.presets.b') }));
    await user.click(within(dialog).getByRole('button', { name: i18n.t('setup.actions.saveEnv') }));

    expect(setupApi.saveSetupConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        dashboard_api_key: 'local-secret',
        embedding_backend: 'hash',
        embedding_dim: null,
        reranker_enabled: false,
        write_guard_llm_enabled: false,
        intent_llm_enabled: false,
        embedding_api_base: '',
        embedding_api_key: '',
        embedding_model: '',
        router_api_base: '',
        router_api_key: '',
        router_chat_model: '',
        router_embedding_model: '',
        router_reranker_model: '',
      })
    );
  });

  it('does not embed the raw api key in the routes key', () => {
    const routesKey = buildRoutesKey(
      {
        source: 'stored',
        mode: 'header',
        key: 'super-secret-key',
      },
      3
    );

    expect(routesKey).toBe('stored:header:3');
    expect(routesKey).not.toContain('super-secret-key');
    expect(buildRoutesKey(null, 4)).toBe('no-auth:4');
  });
});
