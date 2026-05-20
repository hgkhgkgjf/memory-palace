import React, { useMemo } from 'react';
import { isEdgeBrowserProfile } from '../../../lib/browserProfile';

export default function MaintenanceShell({ children }) {
  const reducedEffects = useMemo(() => {
    if (typeof window === 'undefined') return false;
    try {
      return isEdgeBrowserProfile();
    } catch {
      return false;
    }
  }, []);

  return (
    <div
      className="h-full w-full overflow-y-auto bg-transparent"
      data-reduced-effects={reducedEffects ? 'true' : 'false'}
    >
      <div className="mx-auto w-full max-w-6xl px-4 py-4 pb-12 md:px-6 lg:px-10">
        <div className="flex flex-col gap-6">
          {children}
        </div>
      </div>
    </div>
  );
}
