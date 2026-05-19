import React from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  KeyRound,
  Languages,
  Route,
  Save,
  Sparkles,
  Wand2,
  X,
} from 'lucide-react';

import GlassCard from './GlassCard';
import {
  clearStoredMaintenanceAuth,
  extractApiError,
  getSetupStatus,
  saveSetupConfig,
  saveStoredMaintenanceAuth,
} from '../lib/api';

/**
 * @typedef {'header' | 'bearer'} AuthMode
 * @typedef {'none' | 'hash' | 'api' | 'openai' | 'router'} EmbeddingBackend
 *
 * @typedef {{
 *   source?: string,
 *   key?: string,
 *   mode?: string,
 * }} SetupAuthState
 *
 * @typedef {{
 *   dashboard_api_key: string,
 *   allow_insecure_local: boolean,
 *   embedding_backend: EmbeddingBackend,
 *   embedding_api_base: string,
 *   embedding_api_key: string,
 *   embedding_model: string,
 *   embedding_dim: string,
 *   reranker_enabled: boolean,
 *   reranker_api_base: string,
 *   reranker_api_key: string,
 *   reranker_model: string,
 *   write_guard_llm_enabled: boolean,
 *   write_guard_llm_api_base: string,
 *   write_guard_llm_api_key: string,
 *   write_guard_llm_model: string,
 *   intent_llm_enabled: boolean,
 *   intent_llm_api_base: string,
 *   intent_llm_api_key: string,
 *   intent_llm_model: string,
 *   router_api_base: string,
 *   router_api_key: string,
 *   router_chat_model: string,
 *   router_embedding_model: string,
 *   router_reranker_model: string,
 * }} SetupFormState
 *
 * @typedef {{
 *   allow_insecure_local?: boolean,
 *   dashboard_auth_configured?: boolean,
   *   embedding_backend?: EmbeddingBackend,
 *   embedding_configured?: boolean,
 *   embedding_dim?: number | null,
 *   reranker_enabled?: boolean,
 *   reranker_configured?: boolean,
 *   write_guard_enabled?: boolean,
 *   write_guard_configured?: boolean,
 *   intent_llm_enabled?: boolean,
 *   intent_llm_configured?: boolean,
 * }} SetupSummary
 *
 * @typedef {{
 *   summary?: SetupSummary,
 *   apply_supported?: boolean,
 *   write_supported?: boolean,
 *   apply_reason?: string,
 *   write_reason?: string,
 *   restart_targets?: string[],
 *   target_label?: string,
 * }} SetupStatus
 *
 * @typedef {{
 *   kind: 'success',
 *   payload: SetupStatus,
 * } | {
 *   kind: 'error',
 *   error: unknown,
 * }} InitialStatusProbe
 *
 * @typedef {{
 *   error: unknown,
 *   fallbackKey: string,
 * }} SetupErrorState
 *
 * @typedef {{
 *   kind: 'browser' | 'server',
 *   targetLabel?: string,
 *   restart_targets?: string[],
 * }} SetupSaveSuccess
 *
 * @typedef {{
 *   missingFields: string[],
 *   placeholderFields: string[],
 *   isValid: boolean,
 * }} PersistValidationResult
 *
 * @typedef {{
 *   label: string,
 *   hint?: string,
 *   value: string | number,
 *   onChange: (event: import('react').ChangeEvent<HTMLInputElement>) => void,
 *   placeholder?: string,
 *   type?: string,
 *   min?: number | string,
 *   step?: number | string,
 *   inputProps?: Record<string, unknown>,
 * }} SetupInputProps
 *
 * @typedef {{
 *   label: string,
 *   hint?: string,
 *   value: string,
 *   onChange: (event: import('react').ChangeEvent<HTMLSelectElement>) => void,
 *   options: Array<{ value: string, label: string }>,
 * }} SetupSelectProps
 *
 * @typedef {{
 *   label: string,
 *   hint?: string,
 *   checked: boolean,
 *   onChange: (event: import('react').ChangeEvent<HTMLInputElement>) => void,
 * }} SetupToggleProps
 *
 * @typedef {{
 *   label: string,
 *   value: unknown,
 *   configuredText: string,
 *   missingText: string,
 * }} SummaryItemProps
 *
 * @typedef {{
 *   open: boolean,
 *   authState?: SetupAuthState | null,
 *   initialStatusProbe?: InitialStatusProbe | null,
 *   preferBaselineProfile?: boolean | undefined,
 *   onClose?: (() => void) | undefined,
 *   onAuthUpdated?: ((auth: unknown) => void) | undefined,
 * }} SetupAssistantModalProps
 *
 * @typedef {keyof SetupFormState} SetupFormField
 */

export const SETUP_ASSISTANT_DISMISSED_STORAGE_KEY = 'memory-palace.setupAssistantDismissed';

const REMOTE_EMBEDDING_BACKENDS = new Set(['api', 'router', 'openai']);

const ROUTER_PRESET_DEFAULTS = {
  c: {
    router_api_base: 'http://127.0.0.1:8001/v1',
    router_embedding_model: '',
    router_reranker_model: '',
  },
  d: {
    router_api_base: 'https://router.example.com/v1',
    router_embedding_model: '',
    router_reranker_model: '',
  },
};

/** @type {Record<'a' | 'b', Pick<SetupFormState, 'embedding_backend' | 'reranker_enabled' | 'write_guard_llm_enabled' | 'intent_llm_enabled'>>} */
const PROFILE_PRESET_DEFAULTS = {
  a: {
    embedding_backend: 'none',
    reranker_enabled: false,
    write_guard_llm_enabled: false,
    intent_llm_enabled: false,
  },
  b: {
    embedding_backend: 'hash',
    reranker_enabled: false,
    write_guard_llm_enabled: false,
    intent_llm_enabled: false,
  },
};

const PLACEHOLDER_VALUES = {
  router_api_base: new Set(['https://router.example.com/v1']),
  embedding_model: new Set(['text-embedding-model']),
  router_embedding_model: new Set(['router-embedding-model']),
  router_reranker_model: new Set(['router-reranker-model']),
  reranker_model: new Set(['reranker-model']),
  write_guard_llm_model: new Set(['chat-model']),
  intent_llm_model: new Set(['intent-model']),
  router_chat_model: new Set(['router-chat-model']),
};

const FOCUSABLE_DIALOG_SELECTOR = [
  'button:not([disabled])',
  '[href]',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

/** @param {unknown} value */
const normalizeFieldValue = (value) => String(value ?? '').trim();
/** @param {unknown} value */
const isPositiveIntegerValue = (value) => /^[1-9]\d*$/.test(normalizeFieldValue(value));
/** @param {unknown} value */
const normalizeRemoteEmbeddingDimDraft = (value) => {
  const normalized = normalizeFieldValue(value);
  if (!normalized || normalized === '64') {
    return '';
  }
  return normalized;
};

/** @param {SetupSummary} summary */
const shouldHydrateRetrievalShape = (summary) => (
  ['none', 'hash', 'api', 'openai', 'router'].includes(summary.embedding_backend ?? '')
  || Boolean(summary.reranker_enabled)
);

/**
 * @param {string} field
 * @param {unknown} value
 */
const isPlaceholderValue = (field, value) => {
  const normalized = normalizeFieldValue(value);
  if (!normalized) return false;
  return /** @type {Record<string, Set<string>>} */ (PLACEHOLDER_VALUES)[field]?.has(normalized) ?? false;
};

/**
 * @param {SetupAuthState | null | undefined} authState
 * @returns {SetupFormState}
 */
const defaultFormState = (authState) => ({
  dashboard_api_key: authState?.key ?? '',
  allow_insecure_local: false,
  embedding_backend: 'none',
  embedding_api_base: '',
  embedding_api_key: '',
  embedding_model: '',
  embedding_dim: '',
  reranker_enabled: false,
  reranker_api_base: '',
  reranker_api_key: '',
  reranker_model: '',
  write_guard_llm_enabled: false,
  write_guard_llm_api_base: '',
  write_guard_llm_api_key: '',
  write_guard_llm_model: '',
  intent_llm_enabled: false,
  intent_llm_api_base: '',
  intent_llm_api_key: '',
  intent_llm_model: '',
  router_api_base: '',
  router_api_key: '',
  router_chat_model: '',
  router_embedding_model: '',
  router_reranker_model: '',
});

/**
 * @param {SetupFormState} nextForm
 * @returns {SetupFormState}
 */
const clearHiddenRetrievalFields = (nextForm) => {
  const cleaned = { ...nextForm };

  if (!REMOTE_EMBEDDING_BACKENDS.has(cleaned.embedding_backend)) {
    cleaned.embedding_dim = '';
  }

  if (!['api', 'openai'].includes(cleaned.embedding_backend)) {
    cleaned.embedding_api_base = '';
    cleaned.embedding_api_key = '';
    cleaned.embedding_model = '';
  }

  if (cleaned.embedding_backend !== 'router') {
    cleaned.router_api_base = '';
    cleaned.router_api_key = '';
    cleaned.router_chat_model = '';
    cleaned.router_embedding_model = '';
    cleaned.router_reranker_model = '';
  }

  if (!(cleaned.reranker_enabled && cleaned.embedding_backend !== 'router')) {
    cleaned.reranker_api_base = '';
    cleaned.reranker_api_key = '';
    cleaned.reranker_model = '';
  }

  if (!(cleaned.reranker_enabled && cleaned.embedding_backend === 'router')) {
    cleaned.router_reranker_model = '';
  }

  if (!cleaned.write_guard_llm_enabled) {
    cleaned.write_guard_llm_api_base = '';
    cleaned.write_guard_llm_api_key = '';
    cleaned.write_guard_llm_model = '';
  }

  if (!cleaned.intent_llm_enabled) {
    cleaned.intent_llm_api_base = '';
    cleaned.intent_llm_api_key = '';
    cleaned.intent_llm_model = '';
  }

  if (!(cleaned.intent_llm_enabled && cleaned.embedding_backend === 'router')) {
    cleaned.router_chat_model = '';
  }

  return cleaned;
};

/**
 * @param {SetupFormState} form
 * @returns {PersistValidationResult}
 */
const validatePersistableForm = (form) => {
  const missingFields = /** @type {string[]} */ ([]);
  const placeholderFields = /** @type {string[]} */ ([]);
  /**
   * @param {string[]} bucket
   * @param {string} field
   */
  const pushField = (bucket, field) => {
    if (!bucket.includes(field)) {
      bucket.push(field);
    }
  };
  /** @param {SetupFormField} field */
  const requireTextField = (field) => {
    const value = normalizeFieldValue(form[field]);
    if (!value) {
      pushField(missingFields, field);
      return;
    }
    if (isPlaceholderValue(field, value)) {
      pushField(placeholderFields, field);
    }
  };

  if (['api', 'openai'].includes(form.embedding_backend)) {
    requireTextField('embedding_api_base');
    requireTextField('embedding_model');
  } else if (form.embedding_backend === 'router') {
    requireTextField('router_api_base');
    requireTextField('router_embedding_model');
    if (form.reranker_enabled) {
      requireTextField('router_reranker_model');
    }
  }

  if (REMOTE_EMBEDDING_BACKENDS.has(form.embedding_backend)) {
    if (!isPositiveIntegerValue(form.embedding_dim)) {
      pushField(missingFields, 'embedding_dim');
    }
  }

  if (form.reranker_enabled && form.embedding_backend !== 'router') {
    requireTextField('reranker_api_base');
    requireTextField('reranker_model');
  }

  if (form.write_guard_llm_enabled) {
    requireTextField('write_guard_llm_api_base');
    requireTextField('write_guard_llm_model');
  }

  if (form.intent_llm_enabled) {
    requireTextField('intent_llm_api_base');
    requireTextField('intent_llm_model');
  }

  return {
    missingFields,
    placeholderFields,
    isValid: missingFields.length === 0 && placeholderFields.length === 0,
  };
};

/** @param {SetupInputProps} props */
function SetupInput({
  label,
  hint = '',
  value,
  onChange,
  placeholder = '',
  type = 'text',
  min,
  step,
  inputProps = {},
}) {
  return (
    <label className="block space-y-2">
      <div>
        <div className="text-sm font-medium text-[color:var(--palace-ink)]">{label}</div>
        {hint ? (
          <div className="mt-1 text-xs leading-relaxed text-[color:var(--palace-muted)]">
            {hint}
          </div>
        ) : null}
      </div>
      <input
        type={type}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        aria-label={label}
        min={min}
        step={step}
        className="palace-input"
        {...inputProps}
      />
    </label>
  );
}

/** @param {SetupSelectProps} props */
function SetupSelect({ label, hint = '', value, onChange, options }) {
  return (
    <label className="block space-y-2">
      <div>
        <div className="text-sm font-medium text-[color:var(--palace-ink)]">{label}</div>
        {hint ? (
          <div className="mt-1 text-xs leading-relaxed text-[color:var(--palace-muted)]">
            {hint}
          </div>
        ) : null}
      </div>
      <select value={value} onChange={onChange} aria-label={label} className="palace-input">
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

/** @param {SetupToggleProps} props */
function SetupToggle({ label, hint = '', checked, onChange }) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-4 rounded-2xl border border-[color:var(--palace-line)] bg-white/55 px-4 py-3">
      <div className="min-w-0">
        <div className="text-sm font-medium text-[color:var(--palace-ink)]">{label}</div>
        {hint ? (
          <div className="mt-1 text-xs leading-relaxed text-[color:var(--palace-muted)]">
            {hint}
          </div>
        ) : null}
      </div>
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        aria-label={label}
        className="mt-1 h-4 w-4 accent-[color:var(--palace-accent)]"
      />
    </label>
  );
}

/** @param {SummaryItemProps} props */
function SummaryItem({ label, value, configuredText, missingText }) {
  const active = Boolean(value);
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-[color:var(--palace-line)] bg-white/45 px-3 py-2">
      <span className="text-sm text-[color:var(--palace-ink)]">{label}</span>
      <span
        className={
          active
            ? 'rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 text-xs font-semibold text-emerald-700'
            : 'rounded-full border border-amber-500/25 bg-amber-500/10 px-2 py-0.5 text-xs font-semibold text-amber-700'
        }
      >
        {active ? configuredText : missingText}
      </span>
    </div>
  );
}

/** @param {SetupAssistantModalProps} props */
export default function SetupAssistantModal({
  open,
  authState = null,
  initialStatusProbe = null,
  preferBaselineProfile = false,
  onClose,
  onAuthUpdated,
}) {
  const { t, i18n } = useTranslation();
  const dialogRef = React.useRef(/** @type {HTMLDivElement | null} */ (null));
  const [form, setForm] = React.useState(() => defaultFormState(authState));
  const [statusLoading, setStatusLoading] = React.useState(false);
  const [setupStatus, setSetupStatus] = React.useState(/** @type {SetupStatus | null} */ (null));
  const [statusErrorState, setStatusErrorState] = React.useState(
    /** @type {SetupErrorState | null} */ (null)
  );
  const [saveErrorState, setSaveErrorState] = React.useState(
    /** @type {SetupErrorState | null} */ (null)
  );
  const [saveSuccess, setSaveSuccess] = React.useState(
    /** @type {SetupSaveSuccess | null} */ (null)
  );
  const [savingMode, setSavingMode] = React.useState(/** @type {'server' | null} */ (null));
  const initializedOpenRef = React.useRef(false);
  const touchedFieldsRef = React.useRef(new Set(/** @type {string[]} */ ([])));

  const markFieldsTouched = React.useCallback((/** @type {string[]} */ keys) => {
    keys.forEach((/** @type {string} */ key) => touchedFieldsRef.current.add(key));
  }, []);

  const applySetupStatus = React.useCallback((/** @type {SetupStatus} */ payload) => {
    setSetupStatus(payload);
    setForm((current) => {
      const next = { ...current };
      const summary = payload?.summary ?? {};
      const hydrateRetrievalShape = shouldHydrateRetrievalShape(summary);

      if (!touchedFieldsRef.current.has('allow_insecure_local')) {
        next.allow_insecure_local = summary.allow_insecure_local ?? current.allow_insecure_local;
      }
      if (!touchedFieldsRef.current.has('embedding_backend') && hydrateRetrievalShape) {
        next.embedding_backend = summary.embedding_backend ?? current.embedding_backend;
      }
      if (
        !touchedFieldsRef.current.has('embedding_dim')
        && hydrateRetrievalShape
        && summary.embedding_dim != null
      ) {
        next.embedding_dim = String(summary.embedding_dim);
      }
      if (!touchedFieldsRef.current.has('reranker_enabled') && hydrateRetrievalShape) {
        next.reranker_enabled = summary.reranker_enabled ?? current.reranker_enabled;
      }
      if (!touchedFieldsRef.current.has('write_guard_llm_enabled')) {
        next.write_guard_llm_enabled =
          summary.write_guard_enabled ?? current.write_guard_llm_enabled;
      }
      if (!touchedFieldsRef.current.has('intent_llm_enabled')) {
        next.intent_llm_enabled = summary.intent_llm_enabled ?? current.intent_llm_enabled;
      }

      const shouldKeepDocumentedBaseline =
        preferBaselineProfile
        && summary.dashboard_auth_configured !== true
        && summary.embedding_backend === 'hash'
        && summary.reranker_enabled !== true
        && summary.write_guard_enabled !== true
        && summary.intent_llm_enabled !== true;

      if (shouldKeepDocumentedBaseline) {
        if (!touchedFieldsRef.current.has('embedding_backend')) {
          next.embedding_backend = 'none';
        }
        if (!touchedFieldsRef.current.has('embedding_dim')) {
          next.embedding_dim = '';
        }
        if (!touchedFieldsRef.current.has('reranker_enabled')) {
          next.reranker_enabled = false;
        }
        if (!touchedFieldsRef.current.has('write_guard_llm_enabled')) {
          next.write_guard_llm_enabled = false;
        }
        if (!touchedFieldsRef.current.has('intent_llm_enabled')) {
          next.intent_llm_enabled = false;
        }
      }

      return clearHiddenRetrievalFields(next);
    });
  }, [preferBaselineProfile]);

  React.useEffect(() => {
    if (!open) {
      initializedOpenRef.current = false;
      touchedFieldsRef.current = new Set();
      return undefined;
    }
    if (initializedOpenRef.current) return undefined;
    initializedOpenRef.current = true;

    let cancelled = false;
    touchedFieldsRef.current = new Set();
    setForm(defaultFormState(authState));
    setSetupStatus(null);
    setStatusErrorState(null);
    setSaveErrorState(null);
    setSaveSuccess(null);

    if (initialStatusProbe?.kind === 'success' && initialStatusProbe.payload) {
      applySetupStatus(initialStatusProbe.payload);
      setStatusLoading(false);
      return () => {
        cancelled = true;
      };
    }

    if (initialStatusProbe?.kind === 'error') {
      setStatusLoading(false);
      setStatusErrorState({
        error: initialStatusProbe.error,
        fallbackKey: 'setup.messages.statusUnavailable',
      });
      return () => {
        cancelled = true;
      };
    }

    setStatusLoading(true);

    getSetupStatus()
      .then((payload) => {
        if (cancelled) return;
        applySetupStatus(payload);
      })
      .catch((error) => {
        if (cancelled) return;
        setStatusErrorState({
          error,
          fallbackKey: 'setup.messages.statusUnavailable',
        });
      })
      .finally(() => {
        if (cancelled) return;
        setStatusLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [applySetupStatus, authState, initialStatusProbe, open]);

  React.useEffect(() => {
    if (!open || !initializedOpenRef.current || !initialStatusProbe) {
      return undefined;
    }

    if (initialStatusProbe.kind === 'success' && initialStatusProbe.payload) {
      setStatusErrorState(null);
      setStatusLoading(false);
      applySetupStatus(initialStatusProbe.payload);
      return undefined;
    }

    if (initialStatusProbe.kind === 'error') {
      setStatusLoading(false);
      setStatusErrorState({
        error: initialStatusProbe.error,
        fallbackKey: 'setup.messages.statusUnavailable',
      });
    }

    return undefined;
  }, [applySetupStatus, initialStatusProbe, open]);

  React.useEffect(() => {
    if (!open) return undefined;

    const dialog = dialogRef.current;
    if (!dialog) return undefined;

    const preferredFocus =
      dialog.querySelector('[data-autofocus="true"]')
      || dialog.querySelector(FOCUSABLE_DIALOG_SELECTOR);
    if (preferredFocus instanceof HTMLElement) {
      preferredFocus.focus();
    } else {
      dialog.focus();
    }

    return undefined;
  }, [open]);

  const handleDialogKeyDown = React.useCallback((event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      onClose?.();
      return;
    }

    if (event.key !== 'Tab') return;

    const dialog = dialogRef.current;
    if (!dialog) return;

    const focusableElements = Array.from(
      dialog.querySelectorAll(FOCUSABLE_DIALOG_SELECTOR)
    ).filter((element) => element instanceof HTMLElement);

    if (focusableElements.length === 0) {
      event.preventDefault();
      dialog.focus();
      return;
    }

    const firstElement = focusableElements[0];
    const lastElement = focusableElements[focusableElements.length - 1];
    const activeElement = document.activeElement;

    if (event.shiftKey) {
      if (activeElement === firstElement || activeElement === dialog) {
        event.preventDefault();
        lastElement.focus();
      }
      return;
    }

    if (activeElement === lastElement) {
      event.preventDefault();
      firstElement.focus();
    }
  }, [onClose]);

  const updateField = React.useCallback((
    /** @type {SetupFormField} */ key,
    /** @type {SetupFormState[SetupFormField]} */ value
  ) => {
    markFieldsTouched([key]);
    setForm((current) => {
      const next = { ...current, [key]: value };
      if (
        key === 'embedding_backend'
        && typeof value === 'string'
        && REMOTE_EMBEDDING_BACKENDS.has(value)
      ) {
        next.embedding_dim = normalizeRemoteEmbeddingDimDraft(next.embedding_dim);
      }
      return clearHiddenRetrievalFields(next);
    });
  }, [markFieldsTouched]);

  const statusError = React.useMemo(() => {
    if (!statusErrorState) return null;
    return extractApiError(statusErrorState.error, t(statusErrorState.fallbackKey));
  }, [statusErrorState, t]);

  const saveError = React.useMemo(() => {
    if (!saveErrorState) return null;
    if (saveErrorState.error) {
      return extractApiError(saveErrorState.error, t(saveErrorState.fallbackKey));
    }
    return t(saveErrorState.fallbackKey);
  }, [saveErrorState, t]);

  const saveSuccessMessage = React.useMemo(() => {
    if (!saveSuccess) return null;
    if (saveSuccess.kind === 'browser') {
      return t('setup.messages.browserOnlySaved');
    }
    return t('setup.messages.serverSaved', {
      target: saveSuccess.targetLabel || '.env',
    });
  }, [saveSuccess, t]);

  const applyPreset = React.useCallback((/** @type {'a' | 'b' | 'c' | 'd'} */ preset) => {
    if (preset === 'a' || preset === 'b') {
      markFieldsTouched([
        'embedding_backend',
        'reranker_enabled',
        'write_guard_llm_enabled',
        'intent_llm_enabled',
      ]);
    } else {
      markFieldsTouched([
        'embedding_backend',
        'reranker_enabled',
        'router_api_base',
        'router_embedding_model',
        'router_reranker_model',
        'embedding_dim',
      ]);
    }
    setForm((current) => {
      if (preset === 'a') {
        return clearHiddenRetrievalFields({
          ...current,
          ...PROFILE_PRESET_DEFAULTS.a,
        });
      }
      if (preset === 'b') {
        return clearHiddenRetrievalFields({
          ...current,
          ...PROFILE_PRESET_DEFAULTS.b,
        });
      }
      if (preset === 'c') {
        return clearHiddenRetrievalFields({
          ...current,
          embedding_backend: 'router',
          reranker_enabled: true,
          embedding_dim: normalizeRemoteEmbeddingDimDraft(current.embedding_dim),
          ...ROUTER_PRESET_DEFAULTS.c,
        });
      }
      return clearHiddenRetrievalFields({
        ...current,
        embedding_backend: 'router',
        reranker_enabled: true,
        embedding_dim: normalizeRemoteEmbeddingDimDraft(current.embedding_dim),
        ...ROUTER_PRESET_DEFAULTS.d,
      });
    });
  }, [markFieldsTouched]);

  const saveBrowserOnlyDisabled = !String(form.dashboard_api_key || '').trim();
  const persistValidation = React.useMemo(() => validatePersistableForm(form), [form]);
  const showEmbeddingApiFields = ['api', 'openai'].includes(form.embedding_backend);
  const showRouterFields = form.embedding_backend === 'router';
  const showEmbeddingDimField = REMOTE_EMBEDDING_BACKENDS.has(form.embedding_backend);
  const showRerankerApiFields = form.reranker_enabled && form.embedding_backend !== 'router';
  const canPersistServer =
    setupStatus?.apply_supported === true && setupStatus?.write_supported === true;
  const saveEnvDisabled =
    !canPersistServer || savingMode === 'server' || !persistValidation.isValid;
  const restartTargets = setupStatus?.restart_targets || saveSuccess?.restart_targets || [];
  const summary = setupStatus?.summary || {};
  const rerankerStatus =
    typeof summary.reranker_enabled === 'boolean'
      ? (!summary.reranker_enabled || summary.reranker_configured)
      : false;
  const writeGuardStatus =
    typeof summary.write_guard_enabled === 'boolean'
      ? (!summary.write_guard_enabled || summary.write_guard_configured)
      : false;
  const intentStatus =
    typeof summary.intent_llm_enabled === 'boolean'
      ? (!summary.intent_llm_enabled || summary.intent_llm_configured)
      : false;

  const handleSaveBrowserOnly = React.useCallback(() => {
    setSaveErrorState(null);
    setSaveSuccess(null);
    const saved = saveStoredMaintenanceAuth(form.dashboard_api_key, authState?.mode ?? 'header');
    if (saved === false) {
      setSaveErrorState({
        error: null,
        fallbackKey: 'setup.messages.saveFailed',
      });
      return;
    }
    if (!saved) {
      setSaveErrorState({
        error: null,
        fallbackKey: 'setup.messages.browserOnlyRequiresKey',
      });
      return;
    }
    onAuthUpdated?.(saved);
    setSaveErrorState(null);
    setSaveSuccess({
      kind: 'browser',
    });
  }, [authState?.mode, form.dashboard_api_key, onAuthUpdated]);

  const handlePersistConfig = React.useCallback(async () => {
    setSavingMode('server');
    setSaveErrorState(null);
    setSaveSuccess(null);
    try {
      if (!persistValidation.isValid) {
        setSaveErrorState({
          error: null,
          fallbackKey: 'setup.messages.remoteProfileIncomplete',
        });
        return;
      }
      const normalizedDashboardApiKey = normalizeFieldValue(form.dashboard_api_key);
      const payload = {
        ...form,
        dashboard_api_key: normalizedDashboardApiKey,
        embedding_dim: normalizeFieldValue(form.embedding_dim)
          ? Number.parseInt(normalizeFieldValue(form.embedding_dim), 10)
          : null,
      };
      const response = await saveSetupConfig(payload);
      let authSaveFailed = false;
      if (normalizedDashboardApiKey) {
        const saved = saveStoredMaintenanceAuth(normalizedDashboardApiKey, authState?.mode ?? 'header');
        if (saved) {
          onAuthUpdated?.(saved);
        } else {
          authSaveFailed = true;
        }
      } else {
        const cleared = clearStoredMaintenanceAuth();
        if (cleared) {
          onAuthUpdated?.(null);
        } else {
          authSaveFailed = true;
        }
      }
      setSetupStatus((current) => ({
        ...(current || {}),
        ...response,
        apply_supported: current?.apply_supported ?? true,
        apply_reason: current?.apply_reason ?? response.apply_reason,
        write_supported: current?.write_supported ?? true,
        write_reason: current?.write_reason ?? response.write_reason,
      }));
      if (authSaveFailed) {
        setSaveErrorState({
          error: null,
          fallbackKey: 'setup.messages.saveFailed',
        });
        return;
      }
      setSaveSuccess({
        kind: 'server',
        targetLabel: response.target_label || '.env',
        restart_targets: response.restart_targets || [],
      });
    } catch (error) {
      setSaveErrorState({
        error,
        fallbackKey: 'setup.messages.saveFailed',
      });
    } finally {
      setSavingMode(null);
    }
  }, [authState?.mode, form, onAuthUpdated, persistValidation.isValid]);

  const validationMessage = React.useMemo(() => {
    if (persistValidation.isValid) return null;
    if (persistValidation.missingFields.length > 0) {
      return t('setup.messages.remoteProfileIncomplete');
    }
    return t('setup.messages.remoteProfileUsesExamples');
  }, [persistValidation, t]);

  const currentLocale = i18n.resolvedLanguage || 'en';
  const nextLocale = currentLocale === 'en' ? 'zh-CN' : 'en';
  const nextLocaleLabel =
    nextLocale === 'zh-CN'
      ? t('common.language.chinese')
      : t('common.language.english');
  const nextLocaleAriaLabel =
    nextLocale === 'zh-CN'
      ? t('common.language.switchToChinese')
      : t('common.language.switchToEnglish');

  const handleToggleLanguage = React.useCallback(() => {
    void i18n.changeLanguage(nextLocale);
  }, [i18n, nextLocale]);

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-40 flex items-center justify-center bg-[rgba(47,42,36,0.18)] px-4 py-6 backdrop-blur-sm"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-labelledby="setup-assistant-title"
            ref={dialogRef}
            tabIndex={-1}
            onKeyDown={handleDialogKeyDown}
            initial={{ opacity: 0, y: 18, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 18, scale: 0.98 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            className="glass-card flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden border-white/60 bg-white/70"
          >
            <div className="flex items-start justify-between gap-4 border-b border-[color:var(--palace-line)] bg-white/55 px-6 py-5">
              <div className="min-w-0">
                <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-[color:var(--palace-line)] bg-white/60 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-[color:var(--palace-muted)]">
                  <Wand2 size={13} />
                  {t('setup.kicker')}
                </div>
                <h2
                  id="setup-assistant-title"
                  className="font-display text-2xl font-semibold text-[color:var(--palace-ink)]"
                >
                  {t('setup.title')}
                </h2>
                <p className="mt-2 max-w-3xl text-sm leading-relaxed text-[color:var(--palace-muted)]">
                  {t('setup.subtitle')}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleToggleLanguage}
                  data-testid="setup-language-toggle"
                  aria-label={nextLocaleAriaLabel}
                  title={nextLocaleAriaLabel}
                  className="inline-flex items-center gap-2 rounded-full border border-white/50 bg-white/50 px-3 py-2 text-xs font-medium text-[color:var(--palace-ink)] transition hover:bg-white/80"
                >
                  <Languages size={14} />
                  <span>{nextLocaleLabel}</span>
                </button>
                <button
                  type="button"
                  onClick={onClose}
                  className="rounded-full border border-white/50 bg-white/50 p-2 text-[color:var(--palace-muted)] transition hover:bg-white/80 hover:text-[color:var(--palace-ink)]"
                  aria-label={t('setup.actions.close')}
                >
                  <X size={16} />
                </button>
              </div>
            </div>

            <div className="grid min-h-0 flex-1 gap-5 overflow-hidden px-5 py-5 lg:grid-cols-[minmax(0,1.55fr)_360px]">
              <div className="space-y-5 overflow-y-auto pr-1">
                <GlassCard className="space-y-4 p-5">
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 inline-flex h-10 w-10 items-center justify-center rounded-2xl bg-[linear-gradient(135deg,var(--palace-accent),var(--palace-accent-2))] text-white shadow-sm">
                      <KeyRound size={18} />
                    </div>
                    <div>
                      <div className="text-lg font-semibold text-[color:var(--palace-ink)]">
                        {t('setup.dashboard.title')}
                      </div>
                      <div className="mt-1 text-sm leading-relaxed text-[color:var(--palace-muted)]">
                        {t('setup.dashboard.description')}
                      </div>
                    </div>
                  </div>

                  <div className="grid gap-4 md:grid-cols-2">
                    <SetupInput
                      label={t('setup.dashboard.apiKeyLabel')}
                      hint={t('setup.dashboard.apiKeyHint')}
                      value={form.dashboard_api_key}
                      onChange={(event) => updateField('dashboard_api_key', event.target.value)}
                      placeholder={t('setup.dashboard.apiKeyPlaceholder')}
                      type="password"
                      inputProps={{ 'data-autofocus': 'true', autoComplete: 'off' }}
                    />
                    <SetupToggle
                      label={t('setup.dashboard.insecureLocalLabel')}
                      hint={t('setup.dashboard.insecureLocalHint')}
                      checked={form.allow_insecure_local}
                      onChange={(event) => updateField('allow_insecure_local', event.target.checked)}
                    />
                  </div>

                  <div className="rounded-2xl border border-[color:var(--palace-line)] bg-white/45 p-4 text-sm leading-relaxed text-[color:var(--palace-muted)]">
                    {t('setup.dashboard.browserScope')}
                  </div>
                </GlassCard>

                <GlassCard className="space-y-4 p-5">
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 inline-flex h-10 w-10 items-center justify-center rounded-2xl bg-[rgba(212,175,55,0.12)] text-[color:var(--palace-accent-2)]">
                      <Route size={18} />
                    </div>
                    <div>
                      <div className="text-lg font-semibold text-[color:var(--palace-ink)]">
                        {t('setup.retrieval.title')}
                      </div>
                      <div className="mt-1 text-sm leading-relaxed text-[color:var(--palace-muted)]">
                        {t('setup.retrieval.description')}
                      </div>
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    {/** @type {Array<'a' | 'b' | 'c' | 'd'>} */ (['a', 'b', 'c', 'd']).map((preset) => (
                      <button
                        key={preset}
                        type="button"
                        onClick={() => applyPreset(preset)}
                        className="rounded-full border border-white/40 bg-white/55 px-3 py-1.5 text-xs font-medium text-[color:var(--palace-ink)] transition hover:bg-white/80"
                      >
                        {t(`setup.retrieval.presets.${preset}`)}
                      </button>
                    ))}
                  </div>

                  <SetupSelect
                    label={t('setup.retrieval.embeddingBackendLabel')}
                    hint={t('setup.retrieval.embeddingBackendHint')}
                    value={form.embedding_backend}
                    onChange={(event) => updateField('embedding_backend', event.target.value)}
                    options={[
                      { value: 'none', label: t('setup.retrieval.backends.none') },
                      { value: 'hash', label: t('setup.retrieval.backends.hash') },
                      { value: 'api', label: t('setup.retrieval.backends.api') },
                      { value: 'openai', label: t('setup.retrieval.backends.openai') },
                      { value: 'router', label: t('setup.retrieval.backends.router') },
                    ]}
                  />

                  {showEmbeddingApiFields ? (
                    <div className="grid gap-4 md:grid-cols-2">
                      <SetupInput
                        label={t('setup.retrieval.embeddingApiBaseLabel')}
                        value={form.embedding_api_base}
                        onChange={(event) => updateField('embedding_api_base', event.target.value)}
                        placeholder={t('setup.retrieval.embeddingApiBasePlaceholder')}
                      />
                      <SetupInput
                        label={t('setup.retrieval.embeddingModelLabel')}
                        value={form.embedding_model}
                        onChange={(event) => updateField('embedding_model', event.target.value)}
                        placeholder={t('setup.retrieval.embeddingModelPlaceholder')}
                      />
                      <SetupInput
                        label={t('setup.retrieval.embeddingApiKeyLabel')}
                        hint={t('setup.retrieval.optionalApiKeyHint')}
                        value={form.embedding_api_key}
                        onChange={(event) => updateField('embedding_api_key', event.target.value)}
                        placeholder={t('setup.retrieval.embeddingApiKeyPlaceholder')}
                        type="password"
                        inputProps={{ autoComplete: 'off' }}
                      />
                    </div>
                  ) : null}

                  {showEmbeddingDimField ? (
                    <div className="grid gap-4 md:grid-cols-2">
                      <SetupInput
                        label={t('setup.retrieval.embeddingDimLabel')}
                        hint={t('setup.retrieval.embeddingDimHint')}
                        value={form.embedding_dim}
                        onChange={(event) => updateField('embedding_dim', event.target.value)}
                        placeholder={t('setup.retrieval.embeddingDimPlaceholder')}
                        type="number"
                        min="1"
                        step="1"
                      />
                    </div>
                  ) : null}

                  {showRouterFields ? (
                    <div className="grid gap-4 md:grid-cols-2">
                      <SetupInput
                        label={t('setup.retrieval.routerApiBaseLabel')}
                        value={form.router_api_base}
                        onChange={(event) => updateField('router_api_base', event.target.value)}
                        placeholder={t('setup.retrieval.routerApiBasePlaceholder')}
                      />
                      <SetupInput
                        label={t('setup.retrieval.routerApiKeyLabel')}
                        hint={t('setup.retrieval.optionalApiKeyHint')}
                        value={form.router_api_key}
                        onChange={(event) => updateField('router_api_key', event.target.value)}
                        placeholder={t('setup.retrieval.routerApiKeyPlaceholder')}
                        type="password"
                        inputProps={{ autoComplete: 'off' }}
                      />
                      <SetupInput
                        label={t('setup.retrieval.routerEmbeddingModelLabel')}
                        value={form.router_embedding_model}
                        onChange={(event) => updateField('router_embedding_model', event.target.value)}
                        placeholder={t('setup.retrieval.routerEmbeddingModelPlaceholder')}
                      />
                      <SetupInput
                        label={t('setup.retrieval.routerRerankerModelLabel')}
                        value={form.router_reranker_model}
                        onChange={(event) => updateField('router_reranker_model', event.target.value)}
                        placeholder={t('setup.retrieval.routerRerankerModelPlaceholder')}
                      />
                    </div>
                  ) : null}

                  <SetupToggle
                    label={t('setup.retrieval.rerankerEnabledLabel')}
                    hint={t('setup.retrieval.rerankerEnabledHint')}
                    checked={form.reranker_enabled}
                    onChange={(event) => updateField('reranker_enabled', event.target.checked)}
                  />

                  {showRerankerApiFields ? (
                    <div className="grid gap-4 md:grid-cols-2">
                      <SetupInput
                        label={t('setup.retrieval.rerankerApiBaseLabel')}
                        value={form.reranker_api_base}
                        onChange={(event) => updateField('reranker_api_base', event.target.value)}
                        placeholder={t('setup.retrieval.rerankerApiBasePlaceholder')}
                      />
                      <SetupInput
                        label={t('setup.retrieval.rerankerModelLabel')}
                        value={form.reranker_model}
                        onChange={(event) => updateField('reranker_model', event.target.value)}
                        placeholder={t('setup.retrieval.rerankerModelPlaceholder')}
                      />
                      <SetupInput
                        label={t('setup.retrieval.rerankerApiKeyLabel')}
                        hint={t('setup.retrieval.optionalApiKeyHint')}
                        value={form.reranker_api_key}
                        onChange={(event) => updateField('reranker_api_key', event.target.value)}
                        placeholder={t('setup.retrieval.rerankerApiKeyPlaceholder')}
                        type="password"
                        inputProps={{ autoComplete: 'off' }}
                      />
                    </div>
                  ) : null}
                </GlassCard>

                <GlassCard className="space-y-4 p-5">
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 inline-flex h-10 w-10 items-center justify-center rounded-2xl bg-[rgba(184,150,46,0.12)] text-[color:var(--palace-accent-2)]">
                      <Bot size={18} />
                    </div>
                    <div>
                      <div className="text-lg font-semibold text-[color:var(--palace-ink)]">
                        {t('setup.llm.title')}
                      </div>
                      <div className="mt-1 text-sm leading-relaxed text-[color:var(--palace-muted)]">
                        {t('setup.llm.description')}
                      </div>
                    </div>
                  </div>

                  <SetupToggle
                    label={t('setup.llm.writeGuardEnabledLabel')}
                    hint={t('setup.llm.writeGuardEnabledHint')}
                    checked={form.write_guard_llm_enabled}
                    onChange={(event) => updateField('write_guard_llm_enabled', event.target.checked)}
                  />

                  {form.write_guard_llm_enabled ? (
                    <div className="grid gap-4 md:grid-cols-2">
                      <SetupInput
                        label={t('setup.llm.writeGuardApiBaseLabel')}
                        value={form.write_guard_llm_api_base}
                        onChange={(event) => updateField('write_guard_llm_api_base', event.target.value)}
                        placeholder={t('setup.llm.writeGuardApiBasePlaceholder')}
                      />
                      <SetupInput
                        label={t('setup.llm.writeGuardModelLabel')}
                        value={form.write_guard_llm_model}
                        onChange={(event) => updateField('write_guard_llm_model', event.target.value)}
                        placeholder={t('setup.llm.writeGuardModelPlaceholder')}
                      />
                      <SetupInput
                        label={t('setup.llm.writeGuardApiKeyLabel')}
                        hint={t('setup.retrieval.optionalApiKeyHint')}
                        value={form.write_guard_llm_api_key}
                        onChange={(event) => updateField('write_guard_llm_api_key', event.target.value)}
                        placeholder={t('setup.llm.writeGuardApiKeyPlaceholder')}
                        type="password"
                        inputProps={{ autoComplete: 'off' }}
                      />
                    </div>
                  ) : null}

                  <SetupToggle
                    label={t('setup.llm.intentEnabledLabel')}
                    hint={t('setup.llm.intentEnabledHint')}
                    checked={form.intent_llm_enabled}
                    onChange={(event) => updateField('intent_llm_enabled', event.target.checked)}
                  />

                  {form.intent_llm_enabled ? (
                    <div className="grid gap-4 md:grid-cols-2">
                      <SetupInput
                        label={t('setup.llm.intentApiBaseLabel')}
                        value={form.intent_llm_api_base}
                        onChange={(event) => updateField('intent_llm_api_base', event.target.value)}
                        placeholder={t('setup.llm.intentApiBasePlaceholder')}
                      />
                      <SetupInput
                        label={t('setup.llm.intentModelLabel')}
                        value={form.intent_llm_model}
                        onChange={(event) => updateField('intent_llm_model', event.target.value)}
                        placeholder={t('setup.llm.intentModelPlaceholder')}
                      />
                      <SetupInput
                        label={t('setup.llm.intentApiKeyLabel')}
                        hint={t('setup.retrieval.optionalApiKeyHint')}
                        value={form.intent_llm_api_key}
                        onChange={(event) => updateField('intent_llm_api_key', event.target.value)}
                        placeholder={t('setup.llm.intentApiKeyPlaceholder')}
                        type="password"
                        inputProps={{ autoComplete: 'off' }}
                      />
                      {showRouterFields ? (
                        <SetupInput
                          label={t('setup.llm.routerChatModelLabel')}
                          value={form.router_chat_model}
                          onChange={(event) => updateField('router_chat_model', event.target.value)}
                          placeholder={t('setup.llm.routerChatModelPlaceholder')}
                        />
                      ) : null}
                    </div>
                  ) : null}

                  <div className="rounded-2xl border border-[color:var(--palace-line)] bg-white/45 p-4 text-sm leading-relaxed text-[color:var(--palace-muted)]">
                    {t('setup.llm.gistFallbackHint')}
                  </div>
                </GlassCard>
              </div>

              <div className="space-y-4 overflow-y-auto pr-1">
                <GlassCard className="space-y-4 p-5">
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 inline-flex h-10 w-10 items-center justify-center rounded-2xl bg-[rgba(212,175,55,0.12)] text-[color:var(--palace-accent-2)]">
                      <Sparkles size={18} />
                    </div>
                    <div>
                      <div className="text-lg font-semibold text-[color:var(--palace-ink)]">
                        {t('setup.summary.title')}
                      </div>
                      <div className="mt-1 text-sm leading-relaxed text-[color:var(--palace-muted)]">
                        {statusLoading
                          ? t('setup.summary.loading')
                          : statusError || t('setup.summary.subtitle')}
                      </div>
                    </div>
                  </div>

                  <div className="rounded-2xl border border-[color:var(--palace-line)] bg-white/45 p-4">
                    <div className="text-sm font-medium text-[color:var(--palace-ink)]">
                      {t('setup.summary.targetLabel', {
                        target: setupStatus?.target_label || '.env',
                      })}
                    </div>
                    <div className="mt-2 text-sm leading-relaxed text-[color:var(--palace-muted)]">
                      {canPersistServer
                        ? t('setup.summary.applySupported')
                        : t(
                            `setup.reasons.${setupStatus?.write_reason || setupStatus?.apply_reason || 'status_unavailable'}`
                          )}
                    </div>
                  </div>

                  <div className="space-y-2">
                    <SummaryItem
                      label={t('setup.summary.dashboardAuth')}
                      value={summary.dashboard_auth_configured}
                      configuredText={t('setup.summary.configured')}
                      missingText={t('setup.summary.missing')}
                    />
                    <SummaryItem
                      label={t('setup.summary.embedding')}
                      value={summary.embedding_configured}
                      configuredText={t('setup.summary.configured')}
                      missingText={t('setup.summary.missing')}
                    />
                    <SummaryItem
                      label={t('setup.summary.reranker')}
                      value={rerankerStatus}
                      configuredText={summary.reranker_enabled
                        ? t('setup.summary.configured')
                        : t('setup.summary.notEnabled')}
                      missingText={t('setup.summary.missing')}
                    />
                    <SummaryItem
                      label={t('setup.summary.writeGuard')}
                      value={writeGuardStatus}
                      configuredText={summary.write_guard_enabled
                        ? t('setup.summary.configured')
                        : t('setup.summary.notEnabled')}
                      missingText={t('setup.summary.missing')}
                    />
                    <SummaryItem
                      label={t('setup.summary.intent')}
                      value={intentStatus}
                      configuredText={summary.intent_llm_enabled
                        ? t('setup.summary.configured')
                        : t('setup.summary.notEnabled')}
                      missingText={t('setup.summary.missing')}
                    />
                  </div>
                </GlassCard>

                <GlassCard className="space-y-4 p-5">
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 inline-flex h-10 w-10 items-center justify-center rounded-2xl bg-[rgba(47,42,36,0.08)] text-[color:var(--palace-ink)]">
                      <Save size={18} />
                    </div>
                    <div>
                      <div className="text-lg font-semibold text-[color:var(--palace-ink)]">
                        {t('setup.actions.nextTitle')}
                      </div>
                      <div className="mt-1 text-sm leading-relaxed text-[color:var(--palace-muted)]">
                        {t('setup.actions.nextHint')}
                      </div>
                    </div>
                  </div>

                  <div className="rounded-2xl border border-[color:var(--palace-line)] bg-white/45 p-4 text-sm leading-relaxed text-[color:var(--palace-muted)]">
                    {restartTargets.length > 0
                      ? t('setup.summary.restartHint', {
                          targets: restartTargets.join(' / '),
                        })
                      : t('setup.summary.browserOnlyHint')}
                  </div>

                  {validationMessage ? (
                    <div className="rounded-2xl border border-[color:var(--palace-line)] bg-white/45 p-4 text-sm leading-relaxed text-[color:var(--palace-muted)]">
                      {validationMessage}
                    </div>
                  ) : null}

                  {saveSuccess ? (
                    <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/10 p-4 text-sm text-emerald-800">
                      <div className="mb-1 flex items-center gap-2 font-medium">
                        <CheckCircle2 size={16} />
                        {saveSuccessMessage}
                      </div>
                      {saveSuccess.kind === 'server' && restartTargets.length > 0 ? (
                        <div>{t('setup.summary.restartHint', { targets: restartTargets.join(' / ') })}</div>
                      ) : null}
                    </div>
                  ) : null}

                  {saveError ? (
                    <div className="rounded-2xl border border-amber-500/25 bg-amber-500/10 p-4 text-sm text-amber-800">
                      <div className="mb-1 flex items-center gap-2 font-medium">
                        <AlertTriangle size={16} />
                        {t('setup.messages.saveFailed')}
                      </div>
                      <div>{saveError}</div>
                    </div>
                  ) : null}

                  <div className="space-y-3">
                    <button
                      type="button"
                      onClick={handlePersistConfig}
                      disabled={saveEnvDisabled}
                      className="palace-btn-primary w-full justify-center disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {savingMode === 'server'
                        ? t('setup.actions.savingEnv')
                        : t('setup.actions.saveEnv')}
                    </button>
                    <button
                      type="button"
                      onClick={handleSaveBrowserOnly}
                      disabled={saveBrowserOnlyDisabled || savingMode === 'server'}
                      className="palace-btn-ghost w-full justify-center border border-[color:var(--palace-line)] bg-white/45 text-[color:var(--palace-ink)] disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {t('setup.actions.saveBrowserOnly')}
                    </button>
                    <button
                      type="button"
                      onClick={onClose}
                      className="palace-btn-ghost w-full justify-center"
                    >
                      {t('setup.actions.close')}
                    </button>
                  </div>
                </GlassCard>
              </div>
            </div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
