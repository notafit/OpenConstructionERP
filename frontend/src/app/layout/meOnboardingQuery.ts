// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The query key for `GET /v1/users/me/onboarding/`, one entry per user.
//
// Four places share the entry: the sidebar picks its workspace from
// `company_type`, the dashboard's first-run check reads `completed`, and the
// wizard and the Modules page profile switch write their saved answer into it.
// Signing out keeps the query cache, so a key that named no user handed the
// next person on a shared browser the previous one's profile and `completed`
// flag until the entry went stale.
//
// Kept apart from `useCompanyWorkspace.ts` so the dashboard can share the key
// without pulling in the menu catalogue.

import { useMemo } from 'react';
import { useAuthStore } from '@/stores/useAuthStore';

/** One user's entry. Invalidating `['me-onboarding']` still reaches every
 *  user's entry, since query keys match by prefix. */
export function meOnboardingQueryKey(userId: string | null) {
  return ['me-onboarding', userId] as const;
}

/** The signed-in user's entry. A token refresh keeps the key; another user
 *  signing in on the same browser gets a different one. */
export function useMeOnboardingQueryKey() {
  const userId = useAuthStore((s) => s.userId) ?? null;
  return useMemo(() => meOnboardingQueryKey(userId), [userId]);
}
