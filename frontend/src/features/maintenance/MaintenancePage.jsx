import React, { useCallback, useId, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Archive, Activity, TrendingDown } from 'lucide-react';

import MaintenanceShell from './layout/MaintenanceShell';
import MaintenanceHeader from './layout/MaintenanceHeader';
import MaintenanceTabs from './layout/MaintenanceTabs';
import StatStrip from './layout/StatStrip';
import { CATEGORY_COLORS } from './shared/palette';

const TAB_ORPHANS = 'orphans';
const TAB_VITALITY = 'vitality';
const TAB_FORGETTING = 'forgetting';

const OrphanPanel = React.lazy(() => import('./orphan/OrphanPanel'));
const VitalityPanel = React.lazy(() => import('./vitality/VitalityPanel'));
const ForgettingPanel = React.lazy(() => import('./ForgettingPanel'));

export default function MaintenancePage() {
  const { t } = useTranslation();
  const baseId = useId();
  const [activeTab, setActiveTab] = useState(TAB_ORPHANS);
  const [visitedTabs, setVisitedTabs] = useState(() => new Set([TAB_ORPHANS]));
  const [refreshKey, setRefreshKey] = useState(0);
  const orphanReloadRef = useRef(/** @type {null | (() => Promise<void> | void)} */ (null));
  const [statsCounts, setStatsCounts] = useState({
    deprecated: 0,
    orphaned: 0,
    lowVitality: 0,
    lowVitalityActionable: 0,
    forgetting: 0,
  });

  const handleGlobalRefresh = useCallback(() => {
    setRefreshKey((k) => k + 1);
  }, []);

  const refreshing = false;

  const updateStatsCount = useCallback((patch) => {
    setStatsCounts((prev) => ({ ...prev, ...patch }));
  }, []);

  const registerOrphanReload = useCallback((reload) => {
    orphanReloadRef.current = reload;
  }, []);

  const reloadOrphans = useCallback(() => {
    const reload = orphanReloadRef.current;
    return reload ? Promise.resolve(reload()) : Promise.resolve();
  }, []);

  const handleTabChange = useCallback((tabId) => {
    setActiveTab(tabId);
    setVisitedTabs((prev) => {
      if (prev.has(tabId)) return prev;
      const next = new Set(prev);
      next.add(tabId);
      return next;
    });
  }, []);

  const tabs = useMemo(
    () => [
      { id: TAB_ORPHANS, label: t('maintenance.tabs.orphans'), icon: Archive },
      { id: TAB_VITALITY, label: t('maintenance.tabs.vitality'), icon: Activity },
      { id: TAB_FORGETTING, label: t('maintenance.tabs.forgetting'), icon: TrendingDown },
    ],
    [t],
  );

  const stats = useMemo(
    () => [
      {
        id: 'deprecated',
        icon: Archive,
        label: t('maintenance.stats.deprecated'),
        value: statsCounts.deprecated,
        hint: t('maintenance.stats.deprecatedHint'),
        color: CATEGORY_COLORS.deprecated,
      },
      {
        id: 'orphaned',
        icon: Archive,
        label: t('maintenance.stats.orphaned'),
        value: statsCounts.orphaned,
        hint: t('maintenance.stats.orphanedHint'),
        color: CATEGORY_COLORS.orphaned,
      },
      {
        id: 'low-vitality',
        icon: Activity,
        label: t('maintenance.stats.lowVitality'),
        value: statsCounts.lowVitality,
        hint: t('maintenance.stats.lowVitalityHint', {
          count: statsCounts.lowVitalityActionable,
        }),
        color: CATEGORY_COLORS.lowVitality,
      },
      {
        id: 'forgetting',
        icon: TrendingDown,
        label: t('maintenance.stats.forgetting'),
        value: statsCounts.forgetting,
        hint: t('maintenance.stats.forgettingHint'),
        color: CATEGORY_COLORS.archive,
      },
    ],
    [statsCounts, t],
  );

  return (
      <MaintenanceShell>
      <MaintenanceHeader onRefresh={handleGlobalRefresh} refreshing={refreshing} />
      <StatStrip stats={stats} />
      <MaintenanceTabs baseId={baseId} activeTab={activeTab} onTabChange={handleTabChange} tabs={tabs} />

      <div>
        <div
          key={`${TAB_ORPHANS}-${refreshKey}`}
          id={`${baseId}-panel-${TAB_ORPHANS}`}
          role="tabpanel"
          aria-labelledby={`${baseId}-tab-${TAB_ORPHANS}`}
          hidden={activeTab !== TAB_ORPHANS}
        >
          {visitedTabs.has(TAB_ORPHANS) ? (
            <React.Suspense fallback={<div role="status">{t('maintenance.shared.loadingCandidates')}</div>}>
              <OrphanPanel
                onStatsChange={updateStatsCount}
                registerReload={registerOrphanReload}
              />
            </React.Suspense>
          ) : null}
        </div>

        <div
          key={`${TAB_VITALITY}-${refreshKey}`}
          id={`${baseId}-panel-${TAB_VITALITY}`}
          role="tabpanel"
          aria-labelledby={`${baseId}-tab-${TAB_VITALITY}`}
          hidden={activeTab !== TAB_VITALITY}
        >
          {visitedTabs.has(TAB_VITALITY) ? (
            <React.Suspense fallback={<div role="status">{t('maintenance.shared.loadingCandidates')}</div>}>
              <VitalityPanel
                reloadOrphans={reloadOrphans}
                onStatsChange={updateStatsCount}
              />
            </React.Suspense>
          ) : null}
        </div>

        <div
          key={`${TAB_FORGETTING}-${refreshKey}`}
          id={`${baseId}-panel-${TAB_FORGETTING}`}
          role="tabpanel"
          aria-labelledby={`${baseId}-tab-${TAB_FORGETTING}`}
          hidden={activeTab !== TAB_FORGETTING}
        >
          {visitedTabs.has(TAB_FORGETTING) ? (
            <React.Suspense fallback={<div role="status">{t('maintenance.shared.loadingCandidates')}</div>}>
              <ForgettingPanel
                onStatsChange={updateStatsCount}
              />
            </React.Suspense>
          ) : null}
        </div>
      </div>
    </MaintenanceShell>
  );
}
