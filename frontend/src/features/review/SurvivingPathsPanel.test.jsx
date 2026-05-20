import { act, fireEvent, render, screen } from '@testing-library/react';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import i18n from '../../i18n';
import SurvivingPathsPanel, { parseUri } from './SurvivingPathsPanel';

describe('parseUri', () => {
  it('returns empty parts for non-string or empty input', () => {
    // Empty/whitespace strings short-circuit with String(raw ?? '').
    expect(parseUri('')).toEqual({ protocol: '', segments: [], resource: '' });
    expect(parseUri('   ')).toEqual({ protocol: '', segments: [], resource: '   ' });
    // null and undefined are coerced via `raw ?? ''` to ''.
    expect(parseUri(null)).toEqual({ protocol: '', segments: [], resource: '' });
    expect(parseUri(undefined)).toEqual({ protocol: '', segments: [], resource: '' });
    // Non-string values that survive `?? ''` are stringified.
    expect(parseUri(42)).toEqual({ protocol: '', segments: [], resource: '42' });
  });

  it('handles uri without protocol as a single resource segment', () => {
    expect(parseUri('alpha')).toEqual({ protocol: '', segments: [], resource: 'alpha' });
  });

  it('handles uri without protocol but with multiple segments', () => {
    const out = parseUri('a/b/c');
    expect(out.protocol).toBe('');
    expect(out.segments).toEqual(['a', 'b']);
    expect(out.resource).toBe('c');
  });

  it('parses single-segment uri with protocol', () => {
    const out = parseUri('mem://alpha');
    expect(out.protocol).toBe('mem://');
    expect(out.segments).toEqual([]);
    expect(out.resource).toBe('alpha');
  });

  it('parses multi-segment uri with protocol', () => {
    const out = parseUri('mem://workspace/topic/leaf');
    expect(out.protocol).toBe('mem://');
    expect(out.segments).toEqual(['workspace', 'topic']);
    expect(out.resource).toBe('leaf');
  });

  it('parses uri with protocol but empty body', () => {
    const out = parseUri('mem://');
    expect(out.protocol).toBe('mem://');
    expect(out.segments).toEqual([]);
    expect(out.resource).toBe('');
  });

  it('filters out empty segments from collapsed slashes', () => {
    const out = parseUri('mem://a//b/c');
    expect(out.segments).toEqual(['a', 'b']);
    expect(out.resource).toBe('c');
  });

  it('preserves port, query, and fragment text in rendered URI parts', () => {
    const out = parseUri('mem://localhost:8765/a/b?x=1#frag');
    expect(out.protocol).toBe('mem://');
    expect(out.segments).toEqual(['localhost:8765', 'a']);
    expect(out.resource).toBe('b?x=1#frag');
  });
});

describe('SurvivingPathsPanel rendering', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('renders nothing when surviving_paths is not an array', () => {
    const { container } = render(<SurvivingPathsPanel survivingPaths={undefined} />);
    expect(container.firstChild).toBeNull();

    const second = render(<SurvivingPathsPanel survivingPaths={{ not: 'array' }} />);
    expect(second.container.firstChild).toBeNull();
  });

  it('renders the OrphanWarning when surviving_paths is empty', () => {
    render(<SurvivingPathsPanel survivingPaths={[]} />);
    // role="alert" is set on the orphan warning aside
    expect(screen.getByRole('alert')).toBeTruthy();
  });

  it('renders a breadcrumb list for non-empty surviving_paths', () => {
    render(
      <SurvivingPathsPanel
        survivingPaths={['mem://workspace/topic/leaf', 'mem://other/leaf2']}
      />,
    );
    expect(screen.getByText(i18n.t('review.paths.summary', { count: 2 }))).toBeTruthy();
    expect(screen.getByText('leaf')).toBeTruthy();
    expect(screen.getByText('leaf2')).toBeTruthy();
    // Two copy buttons (one per row)
    const copyButtons = screen.getAllByRole('button', { name: /^Copy URI / });
    expect(copyButtons).toHaveLength(2);
  });
});

describe('SurvivingPathsPanel clipboard interactions', () => {
  const originalClipboard = navigator.clipboard;
  const originalExecCommand = document.execCommand;
  let writeTextMock;

  beforeEach(async () => {
    await i18n.changeLanguage('en');
    writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: writeTextMock },
    });
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    if (originalExecCommand === undefined) {
      delete document.execCommand;
    } else {
      document.execCommand = originalExecCommand;
    }
    if (originalClipboard === undefined) {
      delete navigator.clipboard;
    } else {
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: originalClipboard,
      });
    }
  });

  it('shows the copied indicator when navigator.clipboard succeeds', async () => {
    render(<SurvivingPathsPanel survivingPaths={['mem://workspace/leaf']} />);
    const button = screen.getByRole('button', {
      name: i18n.t('review.paths.copyUri', { uri: 'mem://workspace/leaf' }),
    });
    await act(async () => {
      fireEvent.click(button);
      // flush awaited promise
      await Promise.resolve();
    });
    expect(writeTextMock).toHaveBeenCalledWith('mem://workspace/leaf');
    expect(screen.getByText(i18n.t('review.paths.copied'))).toBeTruthy();
  });

  it('falls back to execCommand when navigator.clipboard.writeText rejects', async () => {
    writeTextMock.mockRejectedValue(new Error('denied'));
    // jsdom does not implement document.execCommand by default; install a stub
    // so the legacy clipboard path is exercised.
    const execMock = vi.fn().mockReturnValue(true);
    document.execCommand = execMock;

    render(<SurvivingPathsPanel survivingPaths={['mem://workspace/leaf']} />);
    const button = screen.getByRole('button', {
      name: i18n.t('review.paths.copyUri', { uri: 'mem://workspace/leaf' }),
    });
    await act(async () => {
      fireEvent.click(button);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(execMock).toHaveBeenCalledWith('copy');
    expect(screen.getByText(i18n.t('review.paths.copied'))).toBeTruthy();
  });

  it('shows copyFailed indicator when both clipboard paths fail', async () => {
    writeTextMock.mockRejectedValue(new Error('denied'));
    const execMock = vi.fn().mockReturnValue(false);
    document.execCommand = execMock;

    render(<SurvivingPathsPanel survivingPaths={['mem://workspace/leaf']} />);
    const button = screen.getByRole('button', {
      name: i18n.t('review.paths.copyUri', { uri: 'mem://workspace/leaf' }),
    });
    await act(async () => {
      fireEvent.click(button);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText(i18n.t('review.paths.copyFailed'))).toBeTruthy();
  });

  it('does not throw when component unmounts during a pending async copy', async () => {
    // Make writeText hang so we can unmount before the await resolves.
    let resolveWrite;
    writeTextMock.mockImplementation(
      () => new Promise((resolve) => {
        resolveWrite = resolve;
      }),
    );

    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      const { unmount } = render(
        <SurvivingPathsPanel survivingPaths={['mem://workspace/leaf']} />,
      );
      const button = screen.getByRole('button', {
        name: i18n.t('review.paths.copyUri', { uri: 'mem://workspace/leaf' }),
      });
      fireEvent.click(button);
      unmount();
      // Resolve the await *after* unmount. The mounted-ref guard must prevent
      // any setState side-effects.
      await act(async () => {
        resolveWrite();
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(errorSpy).not.toHaveBeenCalled();
    } finally {
      errorSpy.mockRestore();
    }
  });
});
