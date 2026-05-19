import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { readFileSync } from 'node:fs';

vi.mock('./lib/api', () => ({
  getSetupStatus: vi.fn().mockResolvedValue({
    ok: true,
    apply_supported: true,
    apply_reason: 'local_env_file',
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
  }),
  saveSetupConfig: vi.fn(),
  saveStoredMaintenanceAuth: vi.fn(),
  clearStoredMaintenanceAuth: vi.fn(),
  getMaintenanceAuthState: vi.fn().mockReturnValue(null),
  extractApiError: vi.fn(() => 'Request failed'),
}));

vi.mock('./features/memory/MemoryBrowser', () => ({
  default: () => <div>memory-page</div>,
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

const runLangDetectScript = ({
  storedLocale = null,
  languages = ['en-US'],
  language = 'en-US',
} = {}) => {
  const script = readFileSync('public/lang-detect.js', 'utf8');
  const documentLike = { documentElement: { lang: '' } };
  const localStorageLike = {
    getItem: vi.fn((key) => (key === 'memory-palace.locale' ? storedLocale : null)),
  };
  const navigatorLike = { languages, language };

  Function('localStorage', 'navigator', 'document', script)(
    localStorageLike,
    navigatorLike,
    documentLike,
  );

  return documentLike.documentElement.lang;
};

describe('i18n bootstrap', () => {
  beforeEach(() => {
    window.localStorage?.removeItem?.('memory-palace.dashboardAuth');
    window.localStorage?.removeItem?.('memory-palace.locale');
    delete window.__MEMORY_PALACE_RUNTIME__;
    vi.spyOn(window, 'prompt').mockReturnValue(null);
    vi.spyOn(window, 'alert').mockImplementation(() => {});
    window.history.pushState({}, '', '/memory');
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.resetModules();
    window.history.pushState({}, '', '/');
  });

  it('restores stored locale on fresh init instead of overwriting it back to english', async () => {
    window.localStorage.setItem('memory-palace.locale', 'zh-CN');

    vi.resetModules();
    const [{ default: FreshApp }, { default: freshI18n, LOCALE_STORAGE_KEY }] = await Promise.all([
      import('./App'),
      import('./i18n'),
    ]);

    render(<FreshApp />);

    expect(await screen.findByRole('button', { name: '设置 API 密钥' })).toBeInTheDocument();
    await waitFor(() => expect(freshI18n.resolvedLanguage).toBe('zh-CN'));
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('zh-CN');
    expect(document.documentElement.lang).toBe('zh-CN');
    expect(document.title).toBe('Memory Palace 控制台');
  });

  it('primes document language and title from the stored locale before render', async () => {
    window.localStorage.setItem('memory-palace.locale', 'zh-CN');
    document.documentElement.lang = 'en';
    document.title = 'Memory Palace Dashboard';

    vi.resetModules();
    const [{ primeDocumentLanguageFromBootstrap }] = await Promise.all([
      import('./i18n'),
    ]);

    const primedLocale = primeDocumentLanguageFromBootstrap();

    expect(primedLocale).toBe('zh-CN');
    expect(document.documentElement.lang).toBe('zh-CN');
    expect(document.title).toBe('Memory Palace 控制台');
  });

  it('normalizes stored Chinese locale aliases in the synchronous lang detect script', () => {
    expect(runLangDetectScript({ storedLocale: 'zh' })).toBe('zh-CN');
    expect(runLangDetectScript({ storedLocale: 'zh-TW' })).toBe('zh-CN');
    expect(runLangDetectScript({ storedLocale: 'zh-HK' })).toBe('zh-CN');
  });

  it('treats null translations as missing values instead of returning null', async () => {
    vi.resetModules();
    const [{ default: freshI18n }] = await Promise.all([
      import('./i18n'),
    ]);

    freshI18n.addResourceBundle('en', 'translation', {
      tests: {
        nullValue: null,
      },
    }, true, true);
    await freshI18n.changeLanguage('en');

    expect(freshI18n.options.returnNull).toBe(false);
    expect(freshI18n.t('tests.nullValue')).toBe('tests.nullValue');
  });

  it('maps zh-TW navigator locale to zh-CN on fresh init when no stored locale exists', async () => {
    const originalLanguage = window.navigator.language;
    const originalLanguages = window.navigator.languages;

    Object.defineProperty(window.navigator, 'language', {
      configurable: true,
      value: 'zh-TW',
    });
    Object.defineProperty(window.navigator, 'languages', {
      configurable: true,
      value: ['zh-TW', 'zh'],
    });

    try {
      vi.resetModules();
      const [{ default: freshI18n, LOCALE_STORAGE_KEY }] = await Promise.all([
        import('./i18n'),
      ]);

      await waitFor(() => expect(freshI18n.resolvedLanguage).toBe('zh-CN'));
      expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('zh-CN');
      expect(document.documentElement.lang).toBe('zh-CN');
    } finally {
      Object.defineProperty(window.navigator, 'language', {
        configurable: true,
        value: originalLanguage,
      });
      Object.defineProperty(window.navigator, 'languages', {
        configurable: true,
        value: originalLanguages,
      });
    }
  });

  it('falls back to english for non-Chinese navigator locales on fresh init', async () => {
    const originalLanguage = window.navigator.language;
    const originalLanguages = window.navigator.languages;

    Object.defineProperty(window.navigator, 'language', {
      configurable: true,
      value: 'fr-FR',
    });
    Object.defineProperty(window.navigator, 'languages', {
      configurable: true,
      value: ['fr-FR', 'fr'],
    });

    try {
      vi.resetModules();
      const [{ default: freshI18n, LOCALE_STORAGE_KEY }] = await Promise.all([
        import('./i18n'),
      ]);

      await waitFor(() => expect(freshI18n.resolvedLanguage).toBe('en'));
      expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('en');
      expect(document.documentElement.lang).toBe('en');
    } finally {
      Object.defineProperty(window.navigator, 'language', {
        configurable: true,
        value: originalLanguage,
      });
      Object.defineProperty(window.navigator, 'languages', {
        configurable: true,
        value: originalLanguages,
      });
    }
  });

  it('renders interpolated html-like values without double-escaping in React', async () => {
    vi.resetModules();
    const [{ default: freshI18n }] = await Promise.all([
      import('./i18n'),
    ]);

    const Probe = () => (
      <div>
        {freshI18n.t('setup.messages.serverSaved', {
          target: '<script>alert(1)</script> & notes',
        })}
      </div>
    );

    render(<Probe />);

    expect(
      screen.getByText('Saved local setup to <script>alert(1)</script> & notes.')
    ).toBeInTheDocument();
  });
});
