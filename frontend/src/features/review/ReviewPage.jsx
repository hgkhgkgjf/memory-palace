import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  approveSnapshot,
  clearSession,
  extractApiError,
  getDiff,
  getSessions,
  getSnapshots,
  rollbackResource,
} from '../../lib/api';
import SnapshotList from '../../components/SnapshotList';
import { SimpleDiff } from '../../components/DiffViewer'; // Uses the Memory Palace styled diff
import {
  Activity, 
  Check, 
  ChevronRight, 
  Clock, 
  Database, 
  FileText,
  Layout, 
  Link2,
  RefreshCw, 
  RotateCcw, 
  Settings2,
  ShieldCheck, 
  Trash2
} from 'lucide-react';
import clsx from 'clsx';
import { formatTime } from '../../lib/format';
import { alertWithFallback, confirmWithFallback } from '../../lib/dialogs';

const normalizeSessionList = (value) => {
  if (!Array.isArray(value)) return [];
  return value.map((session, index) => {
    const normalizedSession = session && typeof session === 'object' ? session : {};
    const rawSessionId = normalizedSession.session_id;
    const sessionId =
      (typeof rawSessionId === 'string' || typeof rawSessionId === 'number')
        ? String(rawSessionId).trim()
        : '';
    return {
      ...normalizedSession,
      session_id: sessionId || `session-${index + 1}`,
    };
  });
};

const formatSnapshotTime = (value, lng, fallback) => {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return fallback;
  return formatTime(parsed, lng, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }) || fallback;
};

function ReviewPage() {
  const { t, i18n } = useTranslation();
  const [sessions, setSessions] = useState([]);
  const [currentSessionId, setCurrentSessionId] = useState(null);
  const [snapshots, setSnapshots] = useState([]);
  const [selectedSnapshot, setSelectedSnapshot] = useState(null);
  const [diffData, setDiffData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [diffErrorState, setDiffErrorState] = useState(null);
  const [mutationInFlight, setMutationInFlight] = useState(false);
  const [actionMessage, setActionMessage] = useState(null);
  
  const sessionsRequestRef = useRef(0);
  const currentSessionIdRef = useRef(null);
  const diffRequestRef = useRef(0);
  const snapshotsRequestRef = useRef(0);
  const mutationInFlightRef = useRef(false);
  const mountedRef = useRef(false);
  const diffError = useMemo(() => {
    if (!diffErrorState) return null;
    return extractApiError(diffErrorState.error, t(diffErrorState.fallbackKey));
  }, [diffErrorState, t]);

  const beginMutation = () => {
    if (!mountedRef.current) return false;
    if (mutationInFlightRef.current) return false;
    mutationInFlightRef.current = true;
    setMutationInFlight(true);
    return true;
  };

  const endMutation = () => {
    mutationInFlightRef.current = false;
    if (mountedRef.current) {
      setMutationInFlight(false);
    }
  };

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      sessionsRequestRef.current += 1;
      snapshotsRequestRef.current += 1;
      diffRequestRef.current += 1;
    };
  }, []);

  useEffect(() => {
    currentSessionIdRef.current = currentSessionId;
  }, [currentSessionId]);

  const isActiveSession = useCallback((sessionId) => (
    mountedRef.current && currentSessionIdRef.current === sessionId
  ), []);

  const loadSessions = useCallback(async () => {
    if (!mountedRef.current) return;
    const requestId = ++sessionsRequestRef.current;
    try {
      const rawList = await getSessions();
      const list = normalizeSessionList(rawList);
      if (!mountedRef.current || requestId !== sessionsRequestRef.current) return;
      setDiffErrorState(null);
      setSessions(list);
      // Logic to auto-select or maintain selection
      const activeSessionId = currentSessionIdRef.current;
      const hasActiveSession = Boolean(
        activeSessionId && list.find((session) => session.session_id === activeSessionId)
      );
      if (hasActiveSession) return;
      if (list.length === 0) {
        setSnapshots([]);
        setDiffData(null);
        setSelectedSnapshot(null);
        setCurrentSessionId(null);
        return;
      }
      setSelectedSnapshot(null);
      setCurrentSessionId(list[0].session_id);
    } catch (err) {
      if (!mountedRef.current || requestId !== sessionsRequestRef.current) return;
      setDiffErrorState({ error: err, fallbackKey: 'review.errors.loadSessions' });
    }
  }, []);

  const loadSnapshots = useCallback(async (sessionId) => {
    if (!mountedRef.current) return;
    const requestId = ++snapshotsRequestRef.current;
    setLoading(true);
    setDiffErrorState(null);
    try {
      const list = await getSnapshots(sessionId);
      if (
        !mountedRef.current
        || requestId !== snapshotsRequestRef.current
        || currentSessionIdRef.current !== sessionId
      ) return;
      setSnapshots(list);
      if (list.length > 0) setSelectedSnapshot(list[0]);
      else {
        setSelectedSnapshot(null);
        setDiffData(null);
      }
    } catch (err) {
      if (
        !mountedRef.current
        || requestId !== snapshotsRequestRef.current
        || currentSessionIdRef.current !== sessionId
      ) return;
      if (err.response?.status === 404) {
        setSnapshots([]);
        setSelectedSnapshot(null);
        setDiffData(null);
        setDiffErrorState(null);
        return;
      }
      setSnapshots([]);
      setSelectedSnapshot(null);
      setDiffData(null);
      setDiffErrorState({ error: err, fallbackKey: 'review.errors.loadSnapshots' });
    } finally {
      if (!mountedRef.current || requestId !== snapshotsRequestRef.current) return;
      setLoading(false);
    }
  }, []);

  const loadDiff = useCallback(async (sessionId, resourceId) => {
    if (!mountedRef.current) return;
    const requestId = ++diffRequestRef.current;
    setDiffErrorState(null);
    setDiffData(null);
    try {
      const data = await getDiff(sessionId, resourceId);
      if (
        mountedRef.current
        && requestId === diffRequestRef.current
        && currentSessionIdRef.current === sessionId
      ) setDiffData(data);
    } catch (err) {
      if (
        mountedRef.current
        && requestId === diffRequestRef.current
        && currentSessionIdRef.current === sessionId
      ) {
        setDiffErrorState({ error: err, fallbackKey: 'review.errors.retrieveFragment' });
        setDiffData(null);
      }
    }
  }, []);

  // --- Data Loading Logic (Keep existing logic, refine UI) ---
  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      if (cancelled) return;
      await loadSessions();
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [loadSessions]);

  useEffect(() => {
    if (!currentSessionId) {
      snapshotsRequestRef.current += 1;
      setLoading(false);
      return undefined;
    }
    let cancelled = false;
    setSelectedSnapshot(null);
    const run = async () => {
      if (cancelled) return;
      await loadSnapshots(currentSessionId);
    };
    void run();
    return () => {
      cancelled = true;
      snapshotsRequestRef.current += 1;
    };
  }, [currentSessionId, loadSnapshots]);

  useEffect(() => {
    if (!(currentSessionId && selectedSnapshot)) {
      diffRequestRef.current += 1;
      return undefined;
    }
    let cancelled = false;
    const run = async () => {
      if (cancelled) return;
      await loadDiff(currentSessionId, selectedSnapshot.resource_id);
    };
    void run();
    return () => {
      cancelled = true;
      diffRequestRef.current += 1;
    };
  }, [currentSessionId, loadDiff, selectedSnapshot]);

  // --- Handlers ---
  const handleRollback = async () => {
    if (!currentSessionId || !selectedSnapshot) return;
    if (!beginMutation()) return;
    setActionMessage(null);
    const confirmResult = confirmWithFallback(
      t('review.prompts.rejectChanges', { resourceId: selectedSnapshot.resource_id })
    );
    if (!confirmResult.available) {
      setActionMessage(t('review.errors.confirmUnavailable'));
      endMutation();
      return;
    }
    if (!confirmResult.confirmed) {
      endMutation();
      return;
    }
    try {
      const sessionId = currentSessionId;
      const resourceId = selectedSnapshot.resource_id;
      const rollbackResult = await rollbackResource(sessionId, resourceId);
      if (!isActiveSession(sessionId)) return;
      if (!rollbackResult?.success) {
        throw new Error(rollbackResult?.message || t('review.errors.rollback'));
      }
      // Rollback and snapshot cleanup are split calls; surface partial success explicitly.
      let cleanupError = null;
      try {
        await approveSnapshot(sessionId, resourceId);
      } catch (err) {
        cleanupError = err;
      }
      if (!isActiveSession(sessionId)) return;
      await loadSnapshots(sessionId);
      await loadSessions();
      if (cleanupError) {
        const message = t('review.alerts.rollbackCleanupFailed', {
          detail: extractApiError(cleanupError, cleanupError?.message || t('review.errors.approve')),
        });
        if (!alertWithFallback(message)) {
          setActionMessage(message);
        }
      }
    } catch (err) {
      if (!mountedRef.current) return;
      const message = t('review.alerts.rejectionFailed', {
        detail: extractApiError(err, err?.message || t('review.errors.rollback')),
      });
      if (!alertWithFallback(message)) {
        setActionMessage(message);
      }
    } finally {
      endMutation();
    }
  };

  const handleApprove = async () => {
    if (!currentSessionId || !selectedSnapshot) return;
    if (!beginMutation()) return;
    setActionMessage(null);
    try {
      const sessionId = currentSessionId;
      const resourceId = selectedSnapshot.resource_id;
      await approveSnapshot(sessionId, resourceId);
      if (!isActiveSession(sessionId)) return;
      await loadSnapshots(sessionId);
      await loadSessions();
    } catch (err) {
      if (!mountedRef.current) return;
      const message = t('review.alerts.integrationFailed', {
        detail: extractApiError(err, err?.message || t('review.errors.approve')),
      });
      if (!alertWithFallback(message)) {
        setActionMessage(message);
      }
    } finally {
      endMutation();
    }
  };
  
  const handleClearSession = async () => {
    if (!currentSessionId) return;
    if (!beginMutation()) return;
    setActionMessage(null);
    const confirmResult = confirmWithFallback(t('review.prompts.integrateAll'));
    if (!confirmResult.available) {
      setActionMessage(t('review.errors.confirmUnavailable'));
      endMutation();
      return;
    }
    if (!confirmResult.confirmed) {
      endMutation();
      return;
    }
    try {
      const sessionId = currentSessionId;
      await clearSession(sessionId);
      if (!isActiveSession(sessionId)) return;
      await loadSessions();
    } catch (err) {
      if (!mountedRef.current) return;
      const message = t('review.alerts.massIntegrationFailed', {
        detail: extractApiError(err, err?.message || t('review.errors.clearSession')),
      });
      if (!alertWithFallback(message)) {
        setActionMessage(message);
      }
    } finally {
      endMutation();
    }
  };

  // --- Render Helpers ---
  
  // Surviving Paths Renderer (for DELETE operations)
  const renderSurvivingPaths = () => {
    if (!selectedSnapshot || selectedSnapshot.operation_type !== 'delete') return null;
    if (!diffData?.current_data) return null;
    
    const survivingPathsRaw = diffData.current_data.surviving_paths;
    if (survivingPathsRaw === undefined) return null;  // Data not loaded yet
    const survivingPaths = Array.isArray(survivingPathsRaw) ? survivingPathsRaw : [];
    
    const isFullDeletion = survivingPaths.length === 0;

    return (
      <div className={clsx(
        "mb-8 p-4 rounded-lg border backdrop-blur-sm",
        isFullDeletion 
          ? "bg-rose-950/20 border-rose-800/40" 
          : "bg-stone-900/40 border-stone-800/60"
      )}>
        <h3 className="text-xs font-bold uppercase mb-3 flex items-center gap-2 tracking-widest">
          {isFullDeletion ? (
            <>
              <Trash2 size={12} className="text-rose-500" />
              <span className="text-rose-400">{t('review.memoryFullyOrphaned')}</span>
            </>
          ) : (
            <>
              <Link2 size={12} className="text-stone-500" />
              <span className="text-stone-500">{t('review.survivingPaths')}</span>
            </>
          )}
        </h3>
        
        {isFullDeletion ? (
          <p className="text-xs text-rose-300/70">
            {t('review.noOtherPaths')}
          </p>
        ) : (
          <div className="space-y-1.5">
            <p className="text-xs text-stone-500 mb-2">
              {t('review.stillReachable', { count: survivingPaths.length })}
            </p>
            {survivingPaths.map((path, idx) => (
              <div key={idx} className="flex items-center gap-2 text-xs font-mono text-emerald-400/80 bg-emerald-950/20 rounded px-2.5 py-1.5 border border-emerald-900/30">
                <Link2 size={10} className="text-emerald-600 flex-shrink-0" />
                <span className="truncate">{path}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  // Custom Metadata Renderer
  const renderMetadataChanges = () => {
    if (!diffData?.snapshot_data || !diffData?.current_data) return null;
    const metaKeys = ['priority', 'disclosure'];
    const changes = metaKeys.filter(key => {
      const oldVal = diffData.snapshot_data[key];
      const newVal = diffData.current_data[key];
      return JSON.stringify(oldVal) !== JSON.stringify(newVal);
    });

    if (changes.length === 0) return null;

    return (
      <div className="mb-8 p-4 bg-stone-900/40 border border-stone-800/60 rounded-lg backdrop-blur-sm">
        <h3 className="text-xs font-bold text-stone-500 uppercase mb-4 flex items-center gap-2 tracking-widest">
          <Activity size={12} /> {t('review.metadataShifts')}
        </h3>
        <div className="space-y-3">
          {changes.map(key => {
            const oldVal = diffData.snapshot_data[key];
            const newVal = diffData.current_data[key];
            return (
              <div key={key} className="grid grid-cols-[100px_1fr_20px_1fr] gap-4 text-sm items-start">
                <span className="text-stone-400 font-medium capitalize text-xs pt-0.5">
                  {key === 'priority' ? t('common.labels.priority') : t('common.labels.disclosure')}
                </span>
                <div className="text-rose-400/70 line-through text-xs font-mono text-right break-words">
                  {oldVal != null ? String(oldVal) : t('common.states.empty')}
                </div>
                <div className="text-center text-stone-700 pt-0.5">→</div>
                <div className="text-emerald-400 text-xs font-mono font-bold break-words">
                  {newVal != null ? String(newVal) : t('common.states.empty')}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  return (
    <div className="palace-harmonized relative flex h-full overflow-hidden bg-[color:var(--palace-bg)] text-[color:var(--palace-ink)] font-sans selection:bg-[rgba(179,133,79,0.28)] selection:text-[color:var(--palace-ink)]">
      
      {/* Sidebar: The Void */}
      <div className="w-72 flex-shrink-0 flex flex-col border-r border-[color:var(--palace-line)] bg-[rgba(255,250,244,0.9)] backdrop-blur-sm">
        {/* Header */}
        <div className="border-b border-[color:var(--palace-line)]/90 bg-[linear-gradient(180deg,rgba(255,252,247,0.88),rgba(244,235,223,0.68))] p-5">
            <div className="flex items-center gap-3 text-stone-100 mb-6">
            <div className="w-8 h-8 rounded bg-gradient-to-br from-amber-500 to-amber-600 flex items-center justify-center shadow-lg shadow-amber-900/20">
              <ShieldCheck className="w-4 h-4 text-white" />
            </div>
            <span className="font-display text-sm tracking-wide text-amber-50">{t('review.ledgerTitle')}</span>
          </div>
          
          <div className="relative group">
            <label
              htmlFor="review-session-select"
              className="text-[10px] text-stone-600 uppercase font-bold mb-1.5 block tracking-widest pl-1"
            >
              {t('review.targetSession')}
            </label>
            <div className="relative">
              <select 
                id="review-session-select"
                name="review_session_id"
                disabled={mutationInFlight}
                className="w-full cursor-pointer appearance-none rounded-md border border-[color:var(--palace-line)] bg-white/90 px-3 py-2 text-xs text-[color:var(--palace-ink)] outline-none transition-all hover:border-[color:var(--palace-accent)] focus:border-[color:var(--palace-accent)] focus:ring-1 focus:ring-[color:var(--palace-accent)]/40 disabled:cursor-not-allowed disabled:opacity-60"
                value={currentSessionId || ''}
                onChange={(e) => {
                  if (mutationInFlight) return;
                  setSelectedSnapshot(null);
                  setCurrentSessionId(e.target.value);
                }}
              >
                {sessions.length === 0 && <option>{t('review.noActiveSessions')}</option>}
                {sessions.map(s => (
                  <option key={s.session_id} value={s.session_id}>
                    {s.session_id}
                  </option>
                ))}
              </select>
              <div className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-stone-600">
                <ChevronRight size={12} className="rotate-90" />
              </div>
            </div>
          </div>
        </div>

        {/* Snapshot List */}
        <div className="flex-1 overflow-y-auto py-2">
            {loading ? (
                <div className="p-8 flex justify-center">
                    <div className="w-6 h-6 border-2 border-amber-500/30 border-t-amber-500 rounded-full animate-spin"></div>
                </div>
            ) : (
                <SnapshotList 
                    snapshots={snapshots} 
                    selectedId={selectedSnapshot?.resource_id} 
                    onSelect={(snapshot) => {
                      if (!mutationInFlight) {
                        setSelectedSnapshot(snapshot);
                      }
                    }}
                />
            )}
        </div>

        {/* Footer */}
        {snapshots.length > 0 && (
             <div className="border-t border-[color:var(--palace-line)] bg-[rgba(255,250,244,0.86)] p-4 backdrop-blur-sm">
                 <button 
                    onClick={handleClearSession}
                    disabled={mutationInFlight}
                    className="group flex w-full items-center justify-center gap-2 rounded-md border border-[color:var(--palace-line)] bg-white/90 py-2.5 text-xs font-medium text-[color:var(--palace-muted)] transition-all duration-300 hover:border-[color:var(--palace-accent)] hover:bg-[rgba(237,226,211,0.72)] hover:text-[color:var(--palace-ink)]"
                 >
                     <Check size={14} className="group-hover:scale-110 transition-transform" /> 
                     <span>{t('review.integrateAll')}</span>
                 </button>
             </div>
        )}
      </div>

      {/* Main Stage */}
      <div className="relative flex min-w-0 flex-1 flex-col bg-[rgba(255,250,244,0.7)]">
        {/* Background Ambient Gradient */}
        <div className="pointer-events-none absolute left-0 right-0 top-0 h-96 bg-[radial-gradient(circle_at_top_left,rgba(198,165,126,0.2),rgba(246,242,234,0.08)_52%,transparent_72%)]" />

        {selectedSnapshot ? (
          <>
            {/* Context Header */}
            <div className="relative z-10 flex h-20 items-center justify-between border-b border-[color:var(--palace-line)] bg-white/62 px-8 backdrop-blur-sm">
              <div className="flex items-center gap-4 min-w-0">
                 <div className={clsx(
                    "w-10 h-10 rounded-full flex items-center justify-center border",
                    {
                      'create':         "bg-amber-950/10 border-amber-500/20 text-amber-400 shadow-[0_0_14px_rgba(179,133,79,0.16)]",
                      'create_alias':   "bg-amber-950/10 border-amber-500/20 text-amber-400 shadow-[0_0_14px_rgba(179,133,79,0.16)]",
                      'delete':         "bg-amber-950/10 border-amber-500/20 text-amber-400 shadow-[0_0_14px_rgba(163,124,82,0.14)]",
                      'modify_meta':    "bg-amber-950/10 border-amber-500/20 text-amber-400 shadow-[0_0_14px_rgba(163,124,82,0.14)]",
                      'modify_content': "bg-amber-950/10 border-amber-500/20 text-amber-400 shadow-[0_0_14px_rgba(163,124,82,0.14)]",
                      'modify':         "bg-amber-950/10 border-amber-500/20 text-amber-400 shadow-[0_0_14px_rgba(163,124,82,0.14)]",
                    }[selectedSnapshot.operation_type] || "bg-amber-950/10 border-amber-500/20 text-amber-400 shadow-[0_0_14px_rgba(163,124,82,0.14)]"
                 )}>
                    {{
                      'create':         <Database size={18} />,
                      'create_alias':   <Link2 size={18} />,
                      'delete':         <Trash2 size={18} />,
                      'modify_meta':    <Settings2 size={18} />,
                      'modify_content': <FileText size={18} />,
                      'modify':         <RefreshCw size={18} />,
                    }[selectedSnapshot.operation_type] || <RefreshCw size={18} />}
                 </div>
                 <div className="min-w-0 flex flex-col">
                    <h2 className="font-display text-lg tracking-tight text-amber-50 truncate">
                        {selectedSnapshot.uri || selectedSnapshot.resource_id}
                    </h2>
                    <div className="flex items-center gap-2 text-xs text-stone-500">
                        <span className="bg-stone-800/50 px-1.5 py-0.5 rounded text-stone-400">
                          {t(`resourceTypes.${selectedSnapshot.resource_type}`, {
                            defaultValue: selectedSnapshot.resource_type,
                          })}
                        </span>
                        <span>•</span>
                        <span className="flex items-center gap-1 font-mono opacity-70">
                            <Clock size={10} />
                            {formatSnapshotTime(
                              selectedSnapshot.snapshot_time,
                              i18n.resolvedLanguage,
                              t('common.states.unknown')
                            )}
                        </span>
                    </div>
                 </div>
              </div>
              
              <div className="flex items-center gap-3">
                <button 
                    onClick={handleRollback}
                    disabled={mutationInFlight}
                    className="flex items-center gap-2 px-5 py-2 bg-stone-900 hover:bg-rose-950/30 border border-stone-700 hover:border-rose-800 text-stone-400 hover:text-rose-400 rounded-md transition-all duration-200 text-xs font-medium uppercase tracking-wider"
                >
                    <RotateCcw size={14} /> {t('review.reject')}
                </button>
                <button 
                    onClick={handleApprove}
                    disabled={mutationInFlight}
                    className="flex items-center gap-2 rounded-md border border-amber-600/40 bg-amber-950/35 px-6 py-2 text-xs font-bold uppercase tracking-wider text-amber-100 transition-all duration-200 hover:bg-amber-900/45 hover:border-amber-500/60 shadow-[0_0_15px_rgba(245,158,11,0.18)] hover:shadow-[0_0_20px_rgba(245,158,11,0.28)]"
                >
                    <Check size={14} /> {t('review.integrate')}
                </button>
              </div>
            </div>

            {/* Reading/Diff Area */}
            <div className="flex-1 overflow-y-auto px-8 py-8 custom-scrollbar">
               <div className="max-w-4xl mx-auto">
                   {actionMessage ? (
                     <div
                       role="alert"
                       className="mb-6 rounded-md border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-900"
                     >
                       {actionMessage}
                     </div>
                   ) : null}
                   
                   {diffError ? (
                       <div className="mt-20 flex flex-col items-center justify-center text-rose-500 gap-6 animate-in fade-in zoom-in duration-300">
                           <div className="w-20 h-20 bg-rose-950/20 rounded-full flex items-center justify-center border border-rose-900/50 shadow-xl">
                                <Activity size={32} />
                           </div>
                           <div className="text-center">
                                <p className="text-lg font-medium text-rose-200">{t('review.currentDiffFailure')}</p>
                                <p className="text-rose-400/60 mt-2 max-w-md text-sm">{diffError}</p>
                           </div>
                           <button 
                               onClick={() => loadDiff(currentSessionId, selectedSnapshot.resource_id)} 
                               className="px-6 py-2 bg-stone-800/50 hover:bg-stone-800 rounded-full text-stone-300 text-xs transition-colors border border-stone-700"
                           >
                               {t('review.retryConnection')}
                           </button>
                       </div>
                   ) : diffData ? (
                       <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
                           {/* Diff Summary Badge */}
                           <div className="mb-6 flex justify-end">
                               <div className={clsx(
                                   "inline-flex items-center gap-2 px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest border",
                                   diffData.has_changes 
                                    ? "bg-amber-500/5 border-amber-500/20 text-amber-500" 
                                    : "bg-stone-800/50 border-stone-700 text-stone-500"
                               )}>
                                   {diffData.has_changes ? t('review.modificationDetected') : t('review.noContentDeviation')}
                               </div>
                           </div>

                           {renderMetadataChanges()}
                           {renderSurvivingPaths()}
                           
                           {/* The Core Content */}
                           <div className="bg-stone-900/50 rounded-xl border border-stone-800/50 p-1 min-h-[200px] shadow-2xl relative overflow-hidden">
                                <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-amber-500/20 to-transparent opacity-50"></div>
                                <div className="p-6 md:p-10">
                                    <SimpleDiff 
                                        oldText={diffData.snapshot_data?.content ?? ''} 
                                        newText={diffData.current_data?.content ?? ''} 
                                    />
                                </div>
                           </div>
                       </div>
                   ) : (
                       <div className="flex flex-col items-center justify-center h-64 text-stone-700">
                           <div className="w-2 h-2 bg-amber-500 rounded-full animate-ping mb-4"></div>
                           <span className="text-xs tracking-widest uppercase opacity-50">{t('review.synchronizing')}</span>
                       </div>
                   )}
               </div>
            </div>
          </>
        ) : diffError ? (
           <div className="flex-1 flex flex-col items-center justify-center text-rose-500 gap-4">
             <Activity size={48} className="opacity-20" />
             <p className="text-sm font-medium opacity-50">{t('common.states.connectionLost')}</p>
             <p className="max-w-md px-6 text-center text-xs text-rose-400/80">{diffError}</p>
           </div>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-stone-700 gap-6 select-none">
            <div className="relative">
                <div className="absolute inset-0 bg-amber-500/20 blur-3xl rounded-full opacity-20 animate-pulse"></div>
                <Layout size={64} className="opacity-20 relative z-10" />
            </div>
            <div className="text-center">
                <p className="text-lg font-light text-stone-500">{t('common.states.awaitingInput')}</p>
                <p className="text-xs text-stone-600 mt-2 tracking-wide uppercase">{t('review.selectFragment')}</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default ReviewPage
