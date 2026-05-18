import React from 'react';
import { BrowserRouter, Routes, Route, NavLink, Navigate, useLocation } from 'react-router-dom';
import { ShieldCheck, Database, LibraryBig, Feather, Eye, Languages } from 'lucide-react';
import clsx from 'clsx';
import { motion } from 'framer-motion';
import { useTranslation } from 'react-i18next';

import FluidBackground from './components/FluidBackground';
import RootErrorBoundary from './RootErrorBoundary';
import SetupAssistantModal, {
  SETUP_ASSISTANT_DISMISSED_STORAGE_KEY,
} from './components/SetupAssistantModal';
import {
  clearStoredMaintenanceAuth,
  getSetupStatus,
  getMaintenanceAuthState,
} from './lib/api';
import {
  applyBrowserProfileAttribute,
  isEdgeBrowserProfile,
} from './lib/browserProfile';
import { CHINESE_LOCALE, DEFAULT_LOCALE } from './i18n';

const ReviewPage = React.lazy(() => import('./features/review/ReviewPage'));
const MemoryBrowser = React.lazy(() => import('./features/memory/MemoryBrowser'));
const MaintenancePage = React.lazy(() => import('./features/maintenance/MaintenancePage'));
const ObservabilityPage = React.lazy(() => import('./features/observability/ObservabilityPage'));

const ABSOLUTE_URL_PATTERN = /^([a-z][a-z\d+\-.]*:)?\/\//i;

const getBrowserStorage = (kind) => {
  if (typeof window === 'undefined') return null;
  try {
    if (kind === 'sessionStorage') return window.sessionStorage;
    if (kind === 'localStorage') return window.localStorage;
  } catch (_error) {
    return null;
  }
  return null;
};

const readSetupAssistantDismissedState = () => {
  const sessionStorage = getBrowserStorage('sessionStorage');
  const localStorage = getBrowserStorage('localStorage');

  const sessionValue = sessionStorage?.getItem(SETUP_ASSISTANT_DISMISSED_STORAGE_KEY);
  if (sessionValue != null) {
    return sessionValue;
  }

  const legacyValue = localStorage?.getItem(SETUP_ASSISTANT_DISMISSED_STORAGE_KEY);
  if (legacyValue == null) {
    return null;
  }

  if (sessionStorage) {
    try {
      sessionStorage.setItem(SETUP_ASSISTANT_DISMISSED_STORAGE_KEY, legacyValue);
      if (localStorage?.getItem(SETUP_ASSISTANT_DISMISSED_STORAGE_KEY) === legacyValue) {
        localStorage.removeItem(SETUP_ASSISTANT_DISMISSED_STORAGE_KEY);
      }
    } catch (_error) {
      // Keep the legacy dismissal readable for the current session when migration fails.
    }
  }

  return legacyValue;
};

const persistSetupAssistantDismissedState = (value) => {
  const sessionStorage = getBrowserStorage('sessionStorage');
  const localStorage = getBrowserStorage('localStorage');

  if (sessionStorage) {
    try {
      if (value) {
        sessionStorage.setItem(SETUP_ASSISTANT_DISMISSED_STORAGE_KEY, '1');
      } else {
        sessionStorage.removeItem(SETUP_ASSISTANT_DISMISSED_STORAGE_KEY);
      }
    } catch (_error) {
      // Storage can be unavailable in private / restricted browser contexts.
    }
  }

  if (localStorage) {
    try {
      localStorage.removeItem(SETUP_ASSISTANT_DISMISSED_STORAGE_KEY);
    } catch (_error) {
      // Storage can be unavailable in private / restricted browser contexts.
    }
  }
};

const normalizeBasePath = (value) => {
  if (typeof value !== 'string') return '/';
  const trimmed = value.trim();
  if (!trimmed || trimmed === '/') return '/';
  const normalized = trimmed.replace(/^\/+/, '/').replace(/\/+$/, '');
  return normalized || '/';
};

const resolveSameOriginPath = (value) => {
  if (typeof value !== 'string' || !value.trim()) return '/';
  const trimmed = value.trim();
  if (typeof window === 'undefined' || !ABSOLUTE_URL_PATTERN.test(trimmed)) {
    return normalizeBasePath(trimmed);
  }
  try {
    const url = new URL(trimmed, window.location.origin);
    if (url.origin !== window.location.origin) {
      return '/';
    }
    return normalizeBasePath(url.pathname);
  } catch (_error) {
    return normalizeBasePath(trimmed);
  }
};

export function resolveAppBasename() {
  const viteBase = normalizeBasePath(import.meta.env?.BASE_URL);
  if (viteBase !== '/') {
    return viteBase;
  }

  const apiBasePath = resolveSameOriginPath(import.meta.env?.VITE_API_BASE_URL);
  if (apiBasePath !== '/' && apiBasePath.endsWith('/api')) {
    return apiBasePath.slice(0, -'/api'.length) || '/';
  }

  return undefined;
}

function NavItem({ to, icon: Icon, label }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) => clsx(
        "relative flex h-10 items-center gap-2 rounded-full px-4 text-sm font-medium transition-all duration-300",
        isActive
          ? "text-[color:var(--palace-ink)]"
          : "text-[color:var(--palace-muted)] hover:text-[color:var(--palace-ink)]"
      )}
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <motion.div
              layoutId="nav-pill"
              className="absolute inset-0 rounded-full bg-white shadow-[0_2px_12px_rgba(212,175,55,0.15)] ring-1 ring-[color:var(--palace-accent)]/20"
              transition={{ type: "spring", bounce: 0.2, duration: 0.6 }}
            />
          )}
          <span className="relative z-10 flex items-center gap-2">
            <Icon size={16} className={clsx(isActive ? "text-[color:var(--palace-accent)]" : "text-current")} />
            {label}
          </span>
        </>
      )}
    </NavLink>
  );
}

function AuthControls({ authState, onOpenSetup, onClearApiKey }) {
  const { t } = useTranslation();

  if (authState?.source === 'runtime') {
    return (
      <div className="flex max-w-full flex-wrap items-center justify-end gap-2 sm:flex-nowrap">
        <div className="hidden shrink-0 whitespace-nowrap md:flex items-center rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-xs font-medium text-emerald-700 shadow-sm">
          {t('app.auth.runtimeBadge')}
        </div>
        <button
          type="button"
          onClick={onOpenSetup}
          data-testid="auth-open-setup"
          className="shrink-0 whitespace-nowrap rounded-full border border-white/40 bg-white/40 px-3 py-2 text-xs font-medium text-[color:var(--palace-ink)] backdrop-blur-md transition hover:bg-white/60"
        >
          {t('app.auth.openSetup')}
        </button>
      </div>
    );
  }

  return (
    <div className="flex max-w-full flex-wrap items-center justify-end gap-2 sm:flex-nowrap">
      <button
        type="button"
        onClick={onOpenSetup}
        data-testid="auth-set-api-key"
        className="shrink-0 whitespace-nowrap rounded-full border border-white/40 bg-white/40 px-3 py-2 text-xs font-medium text-[color:var(--palace-ink)] backdrop-blur-md transition hover:bg-white/60"
      >
        {authState ? t('app.auth.updateApiKey') : t('app.auth.setApiKey')}
      </button>
      {authState ? (
        <button
          type="button"
          onClick={onClearApiKey}
          data-testid="auth-clear-api-key"
          className="shrink-0 whitespace-nowrap rounded-full border border-white/30 bg-white/20 px-3 py-2 text-xs font-medium text-[color:var(--palace-muted)] backdrop-blur-md transition hover:bg-white/40 hover:text-[color:var(--palace-ink)]"
        >
          {t('app.auth.clearKey')}
        </button>
      ) : null}
    </div>
  );
}

function LanguageToggle() {
  const { t, i18n } = useTranslation();
  const currentLocale = i18n.resolvedLanguage || DEFAULT_LOCALE;
  const nextLocale = currentLocale === DEFAULT_LOCALE ? CHINESE_LOCALE : DEFAULT_LOCALE;
  const nextLabel = nextLocale === CHINESE_LOCALE
    ? t('common.language.chinese')
    : t('common.language.english');
  const ariaLabel = nextLocale === CHINESE_LOCALE
    ? t('common.language.switchToChinese')
    : t('common.language.switchToEnglish');

  const handleToggle = React.useCallback(() => {
    void i18n.changeLanguage(nextLocale);
  }, [i18n, nextLocale]);

  return (
    <button
      type="button"
      onClick={handleToggle}
      data-testid="language-toggle"
      aria-label={ariaLabel}
      title={ariaLabel}
      className="inline-flex shrink-0 whitespace-nowrap items-center gap-2 rounded-full border border-white/40 bg-white/40 px-3 py-2 text-xs font-medium text-[color:var(--palace-ink)] backdrop-blur-md transition hover:bg-white/60"
    >
      <Languages size={14} />
      <span>{nextLabel}</span>
    </button>
  );
}

export function buildRoutesKey(authState, authRevision) {
  return authState
    ? `${authState.source}:${authState.mode}:${authRevision}`
    : `no-auth:${authRevision}`;
}

function Layout({ authState, authRevision, onOpenSetup, onClearApiKey }) {
  const { t } = useTranslation();
  const location = useLocation();
  const routesKey = buildRoutesKey(authState, authRevision);
  const reducedVisualMode = isEdgeBrowserProfile();

  return (
    <div
      className="relative flex h-screen flex-col overflow-hidden text-[color:var(--palace-ink)]"
      data-browser-performance={reducedVisualMode ? 'lite' : 'default'}
    >
      <FluidBackground reducedEffects={reducedVisualMode} />

      {/* Floating Header */}
      <div className="relative z-20 shrink-0 px-6 pt-6 pb-2">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 md:flex-nowrap md:justify-between md:gap-4">
          <motion.div
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            className="order-1 flex shrink-0 items-center gap-3 rounded-2xl border border-white/40 bg-white/40 px-4 py-2 backdrop-blur-md shadow-sm"
          >
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[linear-gradient(135deg,var(--palace-accent),var(--palace-accent-2))] text-white shadow-md">
              <LibraryBig size={18} />
            </div>
            <span className="font-display text-lg font-semibold tracking-wide text-[color:var(--palace-ink)]">{t('common.appName')}</span>
          </motion.div>

          <motion.nav
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            className="order-3 flex w-full min-w-0 max-w-full items-center gap-1 overflow-x-auto rounded-full border border-white/30 bg-white/20 p-1.5 backdrop-blur-xl shadow-[0_8px_32px_rgba(179,133,79,0.05)] scrollbar-hide md:order-2 md:w-auto md:flex-1"
          >
            <NavItem to="/memory" icon={Database} label={t('app.nav.memory')} />
            <NavItem to="/review" icon={ShieldCheck} label={t('app.nav.review')} />
            <NavItem to="/maintenance" icon={Feather} label={t('app.nav.maintenance')} />
            <NavItem to="/observability" icon={Eye} label={t('app.nav.observability')} />
          </motion.nav>

          <div className="order-2 ml-auto flex max-w-full flex-wrap items-center justify-end gap-2 md:order-3 md:flex-nowrap">
            <LanguageToggle />
            <AuthControls
              authState={authState}
              onOpenSetup={onOpenSetup}
              onClearApiKey={onClearApiKey}
            />
          </div>
        </div>
      </div>

      {/* Main Area */}
      <div className="relative z-10 flex-1 min-h-0 overflow-hidden px-6 pb-6 pt-2">
        <div className="h-full w-full max-w-7xl mx-auto">
          <RootErrorBoundary resetKeys={[location.pathname, routesKey]}>
            <React.Suspense
              fallback={(
                <div
                  role="status"
                  className="flex h-full items-center justify-center rounded-[32px] border border-white/40 bg-white/35 text-sm font-medium text-[color:var(--palace-muted)] backdrop-blur-xl"
                >
                  {t('common.states.loading')}
                </div>
              )}
            >
              <Routes key={routesKey}>
                <Route path="/" element={<Navigate to="/memory" replace />} />
                <Route path="/review" element={<ReviewPage />} />
                <Route path="/memory" element={<MemoryBrowser />} />
                <Route path="/maintenance" element={<MaintenancePage />} />
                <Route path="/observability" element={<ObservabilityPage />} />
                <Route path="*" element={<Navigate to="/memory" replace />} />
              </Routes>
            </React.Suspense>
          </RootErrorBoundary>
        </div>
      </div>
    </div>
  );
}

function App() {
  const { t, i18n } = useTranslation();
  const [authState, setAuthState] = React.useState(() => getMaintenanceAuthState());
  const [authRevision, setAuthRevision] = React.useState(0);
  const [setupOpen, setSetupOpen] = React.useState(false);
  const [setupStatusProbe, setSetupStatusProbe] = React.useState(null);
  const [setupOpenMode, setSetupOpenMode] = React.useState('manual');
  const setupProbeRequestRef = React.useRef(0);
  const routerBasename = resolveAppBasename();

  const readDismissedState = React.useCallback(() => {
    return readSetupAssistantDismissedState();
  }, []);

  const clearDismissedState = React.useCallback(() => {
    persistSetupAssistantDismissedState(false);
  }, []);

  const persistDismissedState = React.useCallback((value) => {
    persistSetupAssistantDismissedState(value);
  }, []);

  React.useEffect(() => {
    document.title = t('app.documentTitle');
  }, [i18n.resolvedLanguage, t]);

  React.useEffect(() => {
    applyBrowserProfileAttribute();
  }, []);

  React.useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    if (authState?.source === 'runtime') return undefined;
    if (authState?.source === 'stored') return undefined;
    const dismissed = readDismissedState();
    if (dismissed === '1') return undefined;

    let cancelled = false;

    void getSetupStatus()
      .then((status) => {
        if (cancelled) return;
        setSetupStatusProbe({ kind: 'success', payload: status });
        if (status?.summary?.dashboard_auth_configured === true) {
          return;
        }
        if (readDismissedState() === '1') return;
        setSetupOpenMode('auto');
        setSetupOpen(true);
      })
      .catch((error) => {
        if (cancelled) return;
        setSetupStatusProbe({ kind: 'error', error });
        if (readDismissedState() === '1') return;
        setSetupOpenMode('auto');
        setSetupOpen(true);
      });

    return () => {
      cancelled = true;
    };
  }, [authState?.source, readDismissedState]);

  const handleOpenSetup = React.useCallback(() => {
    clearDismissedState();
    setSetupStatusProbe(null);
    setSetupOpenMode('manual');
    setSetupOpen(true);
    const requestId = setupProbeRequestRef.current + 1;
    setupProbeRequestRef.current = requestId;
    void getSetupStatus()
      .then((status) => {
        if (setupProbeRequestRef.current !== requestId) return;
        setSetupStatusProbe({ kind: 'success', payload: status });
      })
      .catch((error) => {
        if (setupProbeRequestRef.current !== requestId) return;
        setSetupStatusProbe({ kind: 'error', error });
      });
  }, [clearDismissedState]);

  const handleCloseSetup = React.useCallback(() => {
    setupProbeRequestRef.current += 1;
    persistDismissedState(true);
    setSetupOpen(false);
  }, [persistDismissedState]);

  const handleAuthUpdated = React.useCallback((nextAuth) => {
    setAuthState(nextAuth ?? getMaintenanceAuthState());
    setAuthRevision((value) => value + 1);
  }, []);

  const handleClearApiKey = React.useCallback(() => {
    clearStoredMaintenanceAuth();
    persistDismissedState(false);
    setAuthState(getMaintenanceAuthState());
    setAuthRevision((value) => value + 1);
  }, [persistDismissedState]);

  return (
    <BrowserRouter
      basename={routerBasename}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <Layout
        authState={authState}
        authRevision={authRevision}
        onOpenSetup={handleOpenSetup}
        onClearApiKey={handleClearApiKey}
      />
      <SetupAssistantModal
        open={setupOpen}
        authState={authState}
        initialStatusProbe={setupStatusProbe}
        preferBaselineProfile={setupOpenMode === 'auto'}
        onAuthUpdated={handleAuthUpdated}
        onClose={handleCloseSetup}
      />
    </BrowserRouter>
  );
}

export default App;
