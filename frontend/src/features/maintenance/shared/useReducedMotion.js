import { useEffect, useState } from 'react';
import { isEdgeBrowserProfile } from '../../../lib/browserProfile';

const QUERY = '(prefers-reduced-motion: reduce)';

const getInitialState = () => {
  if (isEdgeBrowserProfile()) return true;
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false;
  }
  return window.matchMedia(QUERY).matches;
};

export const useReducedMotion = () => {
  const [reduced, setReduced] = useState(getInitialState);

  useEffect(() => {
    if (isEdgeBrowserProfile()) {
      setReduced(true);
      return undefined;
    }
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return undefined;
    }

    const mediaQuery = window.matchMedia(QUERY);
    const handler = (event) => setReduced(event.matches);

    setReduced(mediaQuery.matches);

    if (typeof mediaQuery.addEventListener === 'function') {
      mediaQuery.addEventListener('change', handler);
      return () => mediaQuery.removeEventListener('change', handler);
    }

    mediaQuery.addListener(handler);
    return () => mediaQuery.removeListener(handler);
  }, []);

  return reduced;
};

export default useReducedMotion;
