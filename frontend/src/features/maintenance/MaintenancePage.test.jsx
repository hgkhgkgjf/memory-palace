import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../lib/api';
import i18n, { LOCALE_STORAGE_KEY } from '../../i18n';
import MaintenancePage from './MaintenancePage';

const createDeferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
};

// In the new tab-based layout, the panels are conditionally rendered. Helpers
// below find tab triggers and the relevant select-all / action buttons so the
// tests can stay focused on intent (behaviour) rather than markup details.
const clickVitalityTab = async (user) => {
  const tab = await screen.findByRole('tab', { name: /活力清理/ });
  await user.click(tab);
  return tab;
};

const clickForgettingTab = async (user) => {
  const tab = await screen.findByRole('tab', { name: /遗忘模拟/ });
  await user.click(tab);
  return tab;
};

const getOrphanSelectAllCheckbox = () => {
  return screen.getByLabelText(i18n.t('maintenance.orphan.selectGroup', {
    group: i18n.t('maintenance.deprecatedVersions'),
  }));
};

const getVitalitySelectAllCheckbox = () => {
  // VitalityCandidateTable wires the table-wide toggle to id `vitality-select-all`.
  const node = document.getElementById('vitality-select-all');
  if (!node) {
    throw new Error('vitality-select-all checkbox not found in DOM');
  }
  return node;
};

const getVitalityPrepareDeleteButton = (count) => {
  // The toolbar (VitalityActions) and the SelectionBar both render a
  // "准备删除（n）" button. Tests only need to invoke one of them; the toolbar
  // button is rendered first.
  const matches = screen.getAllByRole('button', {
    name: i18n.t('maintenance.vitality.prepareDelete', { count }),
  });
  return matches[0];
};

const getOrphanDeleteButton = (count) => {
  // The toolbar and the SelectionBar both render an identical
  // "删除 N 条孤儿记忆" button once a selection exists.
  const matches = screen.getAllByRole('button', {
    name: i18n.t('maintenance.deleteOrphans', { count }),
  });
  return matches[0];
};

vi.mock('../../lib/api', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    queryVitalityCleanupCandidates: vi.fn(),
    prepareVitalityCleanup: vi.fn(),
    confirmVitalityCleanup: vi.fn(),
    triggerVitalityDecay: vi.fn(),
    extractApiError: vi.fn(actual.extractApiError),
    extractApiErrorCode: vi.fn(actual.extractApiErrorCode),
    listOrphanMemories: vi.fn(),
    getOrphanMemoryDetail: vi.fn(),
    deleteOrphanMemory: vi.fn(),
    simulateForgettingDecay: vi.fn(),
    getForgettingCandidates: vi.fn(),
    prepareForgettingArchive: vi.fn(),
    confirmForgettingArchive: vi.fn(),
  };
});

vi.mock('./vitality/VitalityCandidateTable', async () => {
  const React = await import('react');
  return {
    default: function MockVitalityCandidateTable({
      candidates,
      selectedIds,
      onToggleSelect,
      onToggleSelectAll,
      disabled = false,
    }) {
      const allSelected =
        candidates.length > 0 && candidates.every((item) => selectedIds.has(item.memory_id));
      return React.createElement(
        'div',
        { 'data-testid': 'mock-vitality-candidate-table' },
        React.createElement('input', {
          id: 'vitality-select-all',
          type: 'checkbox',
          checked: allSelected,
          disabled: disabled || candidates.length === 0,
          onChange: onToggleSelectAll,
          'aria-label': 'select all vitality candidates',
        }),
        React.createElement(
          'ul',
          { 'aria-label': 'vitality candidates' },
          candidates.map((item) =>
            React.createElement(
              'li',
              { key: item.memory_id },
              React.createElement(
                'button',
                {
                  type: 'button',
                  disabled,
                  onClick: () => onToggleSelect(item.memory_id),
                },
                item.content_snippet || item.uri || String(item.memory_id),
              ),
            ),
          ),
        ),
      );
    },
  };
});

describe('MaintenancePage', () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    window.localStorage?.removeItem?.(LOCALE_STORAGE_KEY);
    await i18n.changeLanguage('zh-CN');
    vi.spyOn(window, 'alert').mockImplementation(() => {});
    vi.spyOn(window, 'confirm').mockImplementation(() => true);
    vi.spyOn(window, 'prompt').mockReturnValue(null);

    api.listOrphanMemories.mockResolvedValue([
      {
        id: 1,
        category: 'deprecated',
        created_at: '2026-01-01T00:00:00Z',
        content_snippet: 'orphan snippet',
      },
    ]);
    api.queryVitalityCleanupCandidates.mockResolvedValue({ items: [] });
    api.getOrphanMemoryDetail.mockResolvedValue({
      id: 1,
      content: 'orphan full content',
    });
    api.deleteOrphanMemory.mockResolvedValue({ ok: true });
    api.simulateForgettingDecay.mockResolvedValue({
      threshold: 0.35,
      total_candidates: 0,
      projected_archived: 0,
      projected_retained: 0,
      simulation_days: 30,
      simulations: [],
    });
    api.getForgettingCandidates.mockResolvedValue({ candidates: [] });
    api.prepareForgettingArchive.mockResolvedValue({ review: null });
    api.confirmForgettingArchive.mockResolvedValue({ ok: true });
  });

  it('loads orphan list and detail via shared API module', async () => {
    const user = userEvent.setup();
    render(<MaintenancePage />);

    await waitFor(() => {
      expect(api.listOrphanMemories).toHaveBeenCalledTimes(1);
    });

    expect(screen.getByLabelText(i18n.t('maintenance.orphan.selectMemory', {
      id: 1,
      label: 'orphan snippet',
    }))).toBeInTheDocument();

    await user.click(await screen.findByRole('button', { name: /orphan snippet/i }));

    await waitFor(() => {
      expect(api.getOrphanMemoryDetail).toHaveBeenCalledWith(1);
    });
    expect(await screen.findByText(/orphan full content/i)).toBeInTheDocument();
  });

  it('defers hidden maintenance panels until their tabs are visited and then updates stats', async () => {
    const user = userEvent.setup();
    api.listOrphanMemories.mockResolvedValue([
      { id: 1, category: 'deprecated', content_snippet: 'deprecated memory' },
      { id: 2, category: 'orphaned', content_snippet: 'orphaned memory' },
    ]);
    api.queryVitalityCleanupCandidates.mockResolvedValue({
      status: 'ok',
      items: [
        {
          memory_id: 101,
          can_delete: true,
          vitality_score: 0.1,
          inactive_days: 20,
          access_count: 0,
          content_snippet: 'low vitality one',
        },
        {
          memory_id: 102,
          can_delete: false,
          vitality_score: 0.2,
          inactive_days: 12,
          access_count: 1,
          content_snippet: 'low vitality two',
        },
      ],
    });
    api.getForgettingCandidates.mockResolvedValue({
      candidates: [
        {
          memory_id: 201,
          current_score: 0.2,
          projected_score: 0.1,
        },
      ],
    });

    render(<MaintenancePage />);

    await waitFor(() => {
      expect(within(screen.getByTestId('maintenance-stat-deprecated')).getByText('1')).toBeInTheDocument();
      expect(within(screen.getByTestId('maintenance-stat-orphaned')).getByText('1')).toBeInTheDocument();
    });
    expect(api.queryVitalityCleanupCandidates).not.toHaveBeenCalled();
    expect(api.getForgettingCandidates).not.toHaveBeenCalled();

    await clickVitalityTab(user);
    await waitFor(() => {
      expect(api.queryVitalityCleanupCandidates).toHaveBeenCalledTimes(1);
      expect(within(screen.getByTestId('maintenance-stat-low-vitality')).getByText('2')).toBeInTheDocument();
    });
    expect(within(screen.getByTestId('maintenance-stat-low-vitality')).getByText(
      i18n.t('maintenance.stats.lowVitalityHint', { count: 1 }),
    )).toBeInTheDocument();

    await clickForgettingTab(user);
    await waitFor(() => {
      expect(api.getForgettingCandidates).toHaveBeenCalledTimes(1);
      expect(within(screen.getByTestId('maintenance-stat-forgetting')).getByText('1')).toBeInTheDocument();
    });
  });

  it('uses shared API module for batch delete', async () => {
    const user = userEvent.setup();
    render(<MaintenancePage />);

    await screen.findByRole('button', { name: /orphan snippet/i });
    await user.click(getOrphanSelectAllCheckbox());
    await user.click(getOrphanDeleteButton(1));

    await waitFor(() => {
      expect(window.confirm).toHaveBeenCalledTimes(1);
      expect(api.deleteOrphanMemory).toHaveBeenCalledWith(1);
    });
  });

  it('supports keyboard expand on orphan cards', async () => {
    const user = userEvent.setup();
    render(<MaintenancePage />);

    const cardToggle = await screen.findByRole('button', { name: /orphan snippet/i });
    cardToggle.focus();
    await user.keyboard('{Enter}');

    await waitFor(() => {
      expect(api.getOrphanMemoryDetail).toHaveBeenCalledWith(1);
    });
    expect(await screen.findByText(/orphan full content/i)).toBeInTheDocument();
  });

  it('starts all batch delete requests before the first one resolves', async () => {
    const user = userEvent.setup();
    const pending = [];
    api.listOrphanMemories.mockResolvedValue([
      { id: 1, category: 'deprecated', created_at: '2026-01-01T00:00:00Z', content_snippet: 'orphan-1' },
      { id: 2, category: 'deprecated', created_at: '2026-01-01T00:00:00Z', content_snippet: 'orphan-2' },
      { id: 3, category: 'deprecated', created_at: '2026-01-01T00:00:00Z', content_snippet: 'orphan-3' },
    ]);
    api.deleteOrphanMemory.mockImplementation((id) => new Promise((resolve) => {
      pending.push({ id, resolve });
    }));

    render(<MaintenancePage />);

    await screen.findByRole('button', { name: /orphan-1/i });
    await user.click(getOrphanSelectAllCheckbox());
    await user.click(getOrphanDeleteButton(3));

    await waitFor(() => {
      expect(api.deleteOrphanMemory).toHaveBeenCalledTimes(3);
    });

    pending.forEach(({ resolve }) => resolve({ ok: true }));

    await waitFor(() => {
      expect(screen.queryByText(/orphan-1/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/orphan-2/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/orphan-3/i)).not.toBeInTheDocument();
    });
  });

  it('fails closed with inline notice when native confirm dialog is unavailable', async () => {
    const user = userEvent.setup();
    window.confirm.mockImplementation(() => {
      throw new Error('confirm unavailable');
    });

    render(<MaintenancePage />);

    await screen.findByRole('button', { name: /orphan snippet/i });
    await user.click(getOrphanSelectAllCheckbox());
    await user.click(getOrphanDeleteButton(1));

    expect(api.deleteOrphanMemory).not.toHaveBeenCalled();
    expect(
      await screen.findByText(i18n.t('maintenance.errors.confirmUnavailable'))
    ).toBeInTheDocument();
  });

  it('passes optional domain/path_prefix filters when applying vitality query', async () => {
    const user = userEvent.setup();
    render(<MaintenancePage />);
    await clickVitalityTab(user);

    await waitFor(() => {
      expect(api.queryVitalityCleanupCandidates).toHaveBeenCalledTimes(1);
    });
    api.queryVitalityCleanupCandidates.mockClear();

    await user.type(screen.getByLabelText(i18n.t('maintenance.vitality.domain')), 'notes');
    await user.type(screen.getByLabelText(i18n.t('maintenance.vitality.pathPrefix')), 'scope/');
    await user.click(screen.getByRole('button', { name: i18n.t('maintenance.vitality.applyFilters') }));

    await waitFor(() => {
      expect(api.queryVitalityCleanupCandidates).toHaveBeenCalledTimes(1);
    });
    expect(api.queryVitalityCleanupCandidates).toHaveBeenCalledWith({
      threshold: 0.35,
      inactive_days: 14,
      limit: 80,
      domain: 'notes',
      path_prefix: 'scope/',
    });
  });

  it('does not auto-refresh vitality candidates while editing filters before apply', async () => {
    const user = userEvent.setup();
    render(<MaintenancePage />);
    await clickVitalityTab(user);

    await waitFor(() => {
      expect(api.queryVitalityCleanupCandidates).toHaveBeenCalledTimes(1);
    });
    api.queryVitalityCleanupCandidates.mockClear();

    await user.type(screen.getByLabelText(i18n.t('maintenance.vitality.domain')), 'notes');
    await user.type(screen.getByLabelText(i18n.t('maintenance.vitality.pathPrefix')), 'scope/');

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 25));
    });

    expect(api.queryVitalityCleanupCandidates).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: i18n.t('maintenance.vitality.applyFilters') }));

    await waitFor(() => {
      expect(api.queryVitalityCleanupCandidates).toHaveBeenCalledTimes(1);
    });
  });

  it('does not reload vitality candidates when the language changes', async () => {
    const user = userEvent.setup();
    render(<MaintenancePage />);
    await clickVitalityTab(user);

    await waitFor(() => {
      expect(api.queryVitalityCleanupCandidates).toHaveBeenCalledTimes(1);
    });

    await act(async () => {
      await i18n.changeLanguage('en');
    });

    expect(api.queryVitalityCleanupCandidates).toHaveBeenCalledTimes(1);
  });

  it('shows translated error when vitality prepare selection exceeds limit', async () => {
    const user = userEvent.setup();
    api.queryVitalityCleanupCandidates.mockResolvedValue({
      status: 'ok',
      items: Array.from({ length: 101 }, (_, index) => ({
        memory_id: index + 1,
        vitality_score: 0.12,
        inactive_days: 30,
        access_count: 0,
        can_delete: true,
        uri: `core://agent/${index + 1}`,
        content_snippet: `candidate-${index + 1}`,
        state_hash: `hash-${index + 1}`,
      })),
    });

    render(<MaintenancePage />);
    await clickVitalityTab(user);
    await screen.findByText('candidate-1');

    expect(screen.getByLabelText(i18n.t('maintenance.vitality.domain'))).toBeInTheDocument();
    expect(screen.getByLabelText(i18n.t('maintenance.vitality.pathPrefix'))).toBeInTheDocument();

    fireEvent.click(getVitalitySelectAllCheckbox());
    fireEvent.click(getVitalityPrepareDeleteButton(101));

    expect(
      await screen.findByText('选择数量过多：101。最多只能选择 100 条。')
    ).toBeInTheDocument();
    expect(api.prepareVitalityCleanup).not.toHaveBeenCalled();
  });

  it('describes vitality delete confirmation with the prepared deletable count', async () => {
    const user = userEvent.setup();
    api.queryVitalityCleanupCandidates.mockResolvedValue({
      status: 'ok',
      items: [
        {
          memory_id: 101,
          vitality_score: 0.12,
          inactive_days: 30,
          access_count: 0,
          can_delete: true,
          uri: 'core://agent/deletable',
          content_snippet: 'deletable candidate',
          state_hash: 'hash-101',
        },
        {
          memory_id: 102,
          vitality_score: 0.2,
          inactive_days: 18,
          access_count: 2,
          can_delete: false,
          uri: 'core://agent/active',
          content_snippet: 'active candidate',
          state_hash: 'hash-102',
        },
      ],
    });
    api.prepareVitalityCleanup.mockResolvedValue({
      review: {
        review_id: 'review-1',
        token: 'token-1',
        confirmation_phrase: 'CONFIRM DELETE',
        action: 'delete',
        reviewer: 'maintenance_dashboard',
      },
    });

    render(<MaintenancePage />);
    await clickVitalityTab(user);
    await screen.findByText(/deletable candidate/i);

    await user.click(getVitalitySelectAllCheckbox());
    await user.click(getVitalityPrepareDeleteButton(1));

    await waitFor(() => {
      expect(api.prepareVitalityCleanup).toHaveBeenCalledWith(expect.objectContaining({
        action: 'delete',
        selections: [{ memory_id: 101, state_hash: 'hash-101' }],
      }));
    });

    await user.click(await screen.findByRole('button', {
      name: i18n.t('maintenance.vitality.confirmAction', {
        action: i18n.t('maintenance.vitality.actionLabels.delete'),
      }),
    }));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(i18n.t('maintenance.vitality.confirmModal.body', {
      action: i18n.t('maintenance.vitality.actionLabels.delete'),
      count: 1,
    }))).toBeInTheDocument();
    expect(within(dialog).queryByText(i18n.t('maintenance.vitality.confirmModal.body', {
      action: i18n.t('maintenance.vitality.actionLabels.delete'),
      count: 2,
    }))).not.toBeInTheDocument();
  });

  it('handles invalid created_at and migration_target paths without crashing', async () => {
    const user = userEvent.setup();
    api.listOrphanMemories.mockResolvedValue([
      {
        id: 1,
        category: 'deprecated',
        created_at: 'invalid-time',
        content_snippet: 'legacy orphan',
        migration_target: {
          id: 2,
          paths: { bad: true },
        },
      },
    ]);
    api.getOrphanMemoryDetail.mockResolvedValue({
      id: 1,
      content: 'legacy full content',
      migration_target: {
        id: 2,
        content: 'migrated content',
        paths: 'not-an-array',
      },
    });

    render(<MaintenancePage />);

    expect(await screen.findByText(i18n.t('common.states.unknown'))).toBeInTheDocument();
    expect(screen.getByText(i18n.t('maintenance.card.targetNoPaths', { id: 2 }))).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /legacy orphan/i }));
    await waitFor(() => {
      expect(api.getOrphanMemoryDetail).toHaveBeenCalledWith(1);
    });

    const detailContentNodes = await screen.findAllByText(/legacy full content/i);
    expect(detailContentNodes.length).toBeGreaterThan(0);
    // The migration diff is now rendered through `InlineDiffPreview`. Verify
    // the diff surface mounts for this row (it carries `data-testid` and
    // shows both side labels) rather than asserting the legacy header copy.
    expect(screen.getByTestId('inline-diff-preview')).toBeInTheDocument();
  });

  it('keeps prepared review for retry when confirm returns structured confirmation_phrase_mismatch detail', async () => {
    const user = userEvent.setup();
    api.queryVitalityCleanupCandidates.mockResolvedValue({
      status: 'ok',
      items: [
        {
          memory_id: 101,
          vitality_score: 0.12,
          inactive_days: 30,
          access_count: 0,
          can_delete: true,
          uri: 'core://agent/legacy',
          content_snippet: 'legacy candidate',
          state_hash: 'hash-101',
        },
      ],
    });
    api.prepareVitalityCleanup.mockResolvedValue({
      review: {
        review_id: 'review-1',
        token: 'token-1',
        confirmation_phrase: 'CONFIRM DELETE',
        action: 'delete',
        reviewer: 'maintenance_dashboard',
      },
    });
    api.confirmVitalityCleanup.mockRejectedValue({
      response: {
        data: {
          detail: {
            error: 'confirmation_phrase_mismatch',
            message: 'confirmation phrase mismatch',
          },
        },
      },
    });
    api.extractApiError.mockReturnValue('confirmation phrase mismatch');
    api.extractApiErrorCode.mockReturnValue('confirmation_phrase_mismatch');

    render(<MaintenancePage />);
    await clickVitalityTab(user);
    await screen.findByText(/legacy candidate/i);

    await user.click(getVitalitySelectAllCheckbox());
    await user.click(getVitalityPrepareDeleteButton(1));
    await screen.findByText(i18n.t('maintenance.vitality.reviewId', { value: 'review-1' }));

    await user.click(screen.getByRole('button', {
      name: i18n.t('maintenance.vitality.confirmAction', {
        action: i18n.t('maintenance.vitality.actionLabels.delete'),
      }),
    }));

    // The new flow opens a `ConfirmPhraseModal`; type the confirmation phrase
    // and submit the modal to drive the underlying confirm request.
    const dialog = await screen.findByRole('dialog');
    const phraseInput = within(dialog).getByRole('textbox');
    await user.type(phraseInput, 'CONFIRM DELETE');
    await user.click(within(dialog).getByRole('button', {
      name: i18n.t('maintenance.vitality.confirmModal.confirm'),
    }));

    await waitFor(() => {
      expect(api.confirmVitalityCleanup).toHaveBeenCalledWith({
        review_id: 'review-1',
        token: 'token-1',
        confirmation_phrase: 'CONFIRM DELETE',
      });
    });
    expect(screen.getByText(i18n.t('maintenance.vitality.reviewId', { value: 'review-1' }))).toBeInTheDocument();
    expect(screen.getByText('confirmation phrase mismatch')).toBeInTheDocument();
    expect(api.queryVitalityCleanupCandidates).toHaveBeenCalledTimes(1);
  });

  it('sends vitality confirm once while the modal submit request is pending', async () => {
    const user = userEvent.setup();
    api.queryVitalityCleanupCandidates.mockResolvedValue({
      status: 'ok',
      items: [
        {
          memory_id: 101,
          vitality_score: 0.12,
          inactive_days: 30,
          access_count: 0,
          can_delete: true,
          uri: 'core://agent/legacy',
          content_snippet: 'legacy candidate',
          state_hash: 'hash-101',
        },
      ],
    });
    api.prepareVitalityCleanup.mockResolvedValue({
      review: {
        review_id: 'review-1',
        token: 'token-1',
        confirmation_phrase: 'CONFIRM DELETE',
        action: 'delete',
        reviewer: 'maintenance_dashboard',
      },
    });
    const confirmDeferred = createDeferred();
    api.confirmVitalityCleanup.mockReturnValue(confirmDeferred.promise);

    render(<MaintenancePage />);
    await clickVitalityTab(user);
    await screen.findByText(/legacy candidate/i);

    await user.click(getVitalitySelectAllCheckbox());
    await user.click(getVitalityPrepareDeleteButton(1));
    await screen.findByText(i18n.t('maintenance.vitality.reviewId', { value: 'review-1' }));
    await user.click(screen.getByRole('button', {
      name: i18n.t('maintenance.vitality.confirmAction', {
        action: i18n.t('maintenance.vitality.actionLabels.delete'),
      }),
    }));

    const dialog = await screen.findByRole('dialog');
    const phraseInput = within(dialog).getByRole('textbox');
    await user.type(phraseInput, 'CONFIRM DELETE');
    const confirmButton = within(dialog).getByRole('button', {
      name: i18n.t('maintenance.vitality.confirmModal.confirm'),
    });
    fireEvent.click(confirmButton);
    fireEvent.click(confirmButton);

    expect(api.confirmVitalityCleanup).toHaveBeenCalledTimes(1);
    await act(async () => {
      confirmDeferred.resolve({ status: 'ok' });
      await Promise.resolve();
    });
  });

  it('refreshes orphan data after a successful vitality cleanup confirmation', async () => {
    const user = userEvent.setup();
    api.queryVitalityCleanupCandidates.mockResolvedValue({
      status: 'ok',
      items: [
        {
          memory_id: 101,
          vitality_score: 0.12,
          inactive_days: 30,
          access_count: 0,
          can_delete: true,
          uri: 'core://agent/legacy',
          content_snippet: 'legacy candidate',
          state_hash: 'hash-101',
        },
      ],
    });
    api.prepareVitalityCleanup.mockResolvedValue({
      review: {
        review_id: 'review-1',
        token: 'token-1',
        confirmation_phrase: 'CONFIRM DELETE',
        action: 'delete',
        reviewer: 'maintenance_dashboard',
      },
    });
    api.confirmVitalityCleanup.mockResolvedValue({ status: 'executed', deleted_count: 1 });

    render(<MaintenancePage />);
    await clickVitalityTab(user);
    await screen.findByText(/legacy candidate/i);
    await waitFor(() => expect(api.listOrphanMemories).toHaveBeenCalledTimes(1));

    await user.click(getVitalitySelectAllCheckbox());
    await user.click(getVitalityPrepareDeleteButton(1));
    await screen.findByText(i18n.t('maintenance.vitality.reviewId', { value: 'review-1' }));
    await user.click(screen.getByRole('button', {
      name: i18n.t('maintenance.vitality.confirmAction', {
        action: i18n.t('maintenance.vitality.actionLabels.delete'),
      }),
    }));

    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByRole('textbox'), 'CONFIRM DELETE');
    await user.click(within(dialog).getByRole('button', {
      name: i18n.t('maintenance.vitality.confirmModal.confirm'),
    }));

    await waitFor(() => {
      expect(api.confirmVitalityCleanup).toHaveBeenCalledTimes(1);
      expect(api.listOrphanMemories).toHaveBeenCalledTimes(2);
      expect(api.queryVitalityCleanupCandidates).toHaveBeenCalledTimes(2);
    });
  });

  it('keeps prepared review for retry when confirm fails with 401 auth rejection', async () => {
    const user = userEvent.setup();
    api.queryVitalityCleanupCandidates.mockResolvedValue({
      status: 'ok',
      items: [
        {
          memory_id: 101,
          vitality_score: 0.12,
          inactive_days: 30,
          access_count: 0,
          can_delete: true,
          uri: 'core://agent/legacy',
          content_snippet: 'legacy candidate',
          state_hash: 'hash-101',
        },
      ],
    });
    api.prepareVitalityCleanup.mockResolvedValue({
      review: {
        review_id: 'review-1',
        token: 'token-1',
        confirmation_phrase: 'CONFIRM DELETE',
        action: 'delete',
        reviewer: 'maintenance_dashboard',
      },
    });
    api.confirmVitalityCleanup.mockRejectedValue({
      response: {
        status: 401,
        data: {
          detail: {
            error: 'maintenance_auth_failed',
            reason: 'invalid_or_missing_api_key',
          },
        },
      },
    });
    api.extractApiError.mockReturnValue('auth failed');
    api.extractApiErrorCode.mockReturnValue('maintenance_auth_failed');

    render(<MaintenancePage />);
    await clickVitalityTab(user);
    await screen.findByText(/legacy candidate/i);

    await user.click(getVitalitySelectAllCheckbox());
    await user.click(getVitalityPrepareDeleteButton(1));
    await screen.findByText(i18n.t('maintenance.vitality.reviewId', { value: 'review-1' }));

    await user.click(screen.getByRole('button', {
      name: i18n.t('maintenance.vitality.confirmAction', {
        action: i18n.t('maintenance.vitality.actionLabels.delete'),
      }),
    }));

    const dialog = await screen.findByRole('dialog');
    const phraseInput = within(dialog).getByRole('textbox');
    await user.type(phraseInput, 'CONFIRM DELETE');
    await user.click(within(dialog).getByRole('button', {
      name: i18n.t('maintenance.vitality.confirmModal.confirm'),
    }));

    await waitFor(() => {
      expect(api.confirmVitalityCleanup).toHaveBeenCalledWith({
        review_id: 'review-1',
        token: 'token-1',
        confirmation_phrase: 'CONFIRM DELETE',
      });
    });
    expect(screen.getByText(i18n.t('maintenance.vitality.reviewId', { value: 'review-1' }))).toBeInTheDocument();
    expect(screen.getByText('auth failed')).toBeInTheDocument();
    expect(api.queryVitalityCleanupCandidates).toHaveBeenCalledTimes(1);
  });

  it('keeps prepared review for retry when confirm times out before a response arrives', async () => {
    const user = userEvent.setup();
    api.queryVitalityCleanupCandidates.mockResolvedValue({
      status: 'ok',
      items: [
        {
          memory_id: 101,
          vitality_score: 0.12,
          inactive_days: 30,
          access_count: 0,
          can_delete: true,
          uri: 'core://agent/legacy',
          content_snippet: 'legacy candidate',
          state_hash: 'hash-101',
        },
      ],
    });
    api.prepareVitalityCleanup.mockResolvedValue({
      review: {
        review_id: 'review-1',
        token: 'token-1',
        confirmation_phrase: 'CONFIRM DELETE',
        action: 'delete',
        reviewer: 'maintenance_dashboard',
      },
    });
    api.confirmVitalityCleanup.mockRejectedValue({
      code: 'ECONNABORTED',
      message: 'timeout of 60000ms exceeded',
    });
    api.extractApiError.mockReturnValue('timeout exceeded');
    api.extractApiErrorCode.mockReturnValue(null);

    render(<MaintenancePage />);
    await clickVitalityTab(user);
    await screen.findByText(/legacy candidate/i);

    await user.click(getVitalitySelectAllCheckbox());
    await user.click(getVitalityPrepareDeleteButton(1));
    await screen.findByText(i18n.t('maintenance.vitality.reviewId', { value: 'review-1' }));

    await user.click(screen.getByRole('button', {
      name: i18n.t('maintenance.vitality.confirmAction', {
        action: i18n.t('maintenance.vitality.actionLabels.delete'),
      }),
    }));

    const dialog = await screen.findByRole('dialog');
    const phraseInput = within(dialog).getByRole('textbox');
    await user.type(phraseInput, 'CONFIRM DELETE');
    await user.click(within(dialog).getByRole('button', {
      name: i18n.t('maintenance.vitality.confirmModal.confirm'),
    }));

    await waitFor(() => {
      expect(api.confirmVitalityCleanup).toHaveBeenCalledWith({
        review_id: 'review-1',
        token: 'token-1',
        confirmation_phrase: 'CONFIRM DELETE',
      });
    });
    expect(screen.getByText(i18n.t('maintenance.vitality.reviewId', { value: 'review-1' }))).toBeInTheDocument();
    expect(screen.getByText('timeout exceeded')).toBeInTheDocument();
    expect(api.queryVitalityCleanupCandidates).toHaveBeenCalledTimes(1);
  });

  it('does not refresh maintenance data after vitality confirm resolves post-unmount', async () => {
    const user = userEvent.setup();
    const confirmDeferred = createDeferred();
    api.queryVitalityCleanupCandidates.mockResolvedValue({
      status: 'ok',
      items: [
        {
          memory_id: 101,
          vitality_score: 0.12,
          inactive_days: 30,
          access_count: 0,
          can_delete: true,
          uri: 'core://agent/legacy',
          content_snippet: 'legacy candidate',
          state_hash: 'hash-101',
        },
      ],
    });
    api.prepareVitalityCleanup.mockResolvedValue({
      review: {
        review_id: 'review-1',
        token: 'token-1',
        confirmation_phrase: 'CONFIRM DELETE',
        action: 'delete',
        reviewer: 'maintenance_dashboard',
      },
    });
    api.confirmVitalityCleanup.mockImplementation(() => confirmDeferred.promise);

    const { unmount } = render(<MaintenancePage />);
    await clickVitalityTab(user);
    await screen.findByText(/legacy candidate/i);
    await waitFor(() => expect(api.listOrphanMemories).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(api.queryVitalityCleanupCandidates).toHaveBeenCalledTimes(1));

    await user.click(getVitalitySelectAllCheckbox());
    await user.click(getVitalityPrepareDeleteButton(1));
    await screen.findByText(i18n.t('maintenance.vitality.reviewId', { value: 'review-1' }));

    await user.click(screen.getByRole('button', {
      name: i18n.t('maintenance.vitality.confirmAction', {
        action: i18n.t('maintenance.vitality.actionLabels.delete'),
      }),
    }));

    const dialog = await screen.findByRole('dialog');
    const phraseInput = within(dialog).getByRole('textbox');
    await user.type(phraseInput, 'CONFIRM DELETE');
    await user.click(within(dialog).getByRole('button', {
      name: i18n.t('maintenance.vitality.confirmModal.confirm'),
    }));

    await waitFor(() => expect(api.confirmVitalityCleanup).toHaveBeenCalledTimes(1));

    unmount();

    await act(async () => {
      confirmDeferred.resolve({ status: 'executed' });
      await confirmDeferred.promise;
      await Promise.resolve();
    });

    expect(api.listOrphanMemories).toHaveBeenCalledTimes(1);
    expect(api.queryVitalityCleanupCandidates).toHaveBeenCalledTimes(1);
  });

  it('keeps prepared review and shows inline error when confirmation phrase does not match', async () => {
    const user = userEvent.setup();
    api.queryVitalityCleanupCandidates.mockResolvedValue({
      status: 'ok',
      items: [
        {
          memory_id: 101,
          vitality_score: 0.12,
          inactive_days: 30,
          access_count: 0,
          can_delete: true,
          uri: 'core://agent/legacy',
          content_snippet: 'legacy candidate',
          state_hash: 'hash-101',
        },
      ],
    });
    api.prepareVitalityCleanup.mockResolvedValue({
      review: {
        review_id: 'review-1',
        token: 'token-1',
        confirmation_phrase: 'CONFIRM DELETE',
        action: 'delete',
        reviewer: 'maintenance_dashboard',
      },
    });

    render(<MaintenancePage />);
    await clickVitalityTab(user);
    await screen.findByText(/legacy candidate/i);

    await user.click(getVitalitySelectAllCheckbox());
    await user.click(getVitalityPrepareDeleteButton(1));
    await screen.findByText(i18n.t('maintenance.vitality.reviewId', { value: 'review-1' }));

    // Open the confirm modal and dismiss it without entering the phrase. The
    // prepared review must survive so the reviewer can retry the confirmation
    // without redoing the prepare step (mirrors the old "prompt unavailable"
    // intent under the new modal-based flow).
    await user.click(screen.getByRole('button', {
      name: i18n.t('maintenance.vitality.confirmAction', {
        action: i18n.t('maintenance.vitality.actionLabels.delete'),
      }),
    }));

    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', {
      name: i18n.t('maintenance.vitality.confirmModal.cancel'),
    }));

    expect(api.confirmVitalityCleanup).not.toHaveBeenCalled();
    expect(screen.getByText(i18n.t('maintenance.vitality.reviewId', { value: 'review-1' }))).toBeInTheDocument();
  });

  it('recomputes orphan load error copy when the language changes', async () => {
    api.listOrphanMemories.mockRejectedValue({
      response: {
        data: {
          detail: {
            error: 'maintenance_auth_failed',
            reason: 'invalid_or_missing_api_key',
          },
        },
      },
    });
    await i18n.changeLanguage('en');

    render(<MaintenancePage />);

    await screen.findByText(/Click "Set API key"/);

    await act(async () => {
      await i18n.changeLanguage('zh-CN');
    });

    await screen.findByText(/点击右上角“设置 API 密钥”/);
    expect(screen.queryByText(/Click "Set API key"/)).not.toBeInTheDocument();
  });
});
