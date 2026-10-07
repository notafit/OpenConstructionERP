/**
 * The presence socket reads what the server actually sends.
 *
 * ``presence_join`` and ``presence_update`` carry the user flat, as
 * ``app/modules/global_presence/router.py`` builds them. The hook read a
 * nested ``user`` and threw on every join, on every page.
 */
import { describe, it, expect } from 'vitest';

import { presenceUserFromWire } from './useGlobalPresenceSocket';

describe('presenceUserFromWire', () => {
  it('builds the user from a flat join message', () => {
    const msg = {
      event: 'presence_join',
      user_id: 'u-1',
      user_name: 'Ana',
      route: '/',
      status: 'active',
      ts: '2026-09-21T12:00:00+00:00',
    };
    expect(presenceUserFromWire(msg, msg.ts)).toEqual({
      user_id: 'u-1',
      user_name: 'Ana',
      route: '/',
      status: 'active',
      last_active: '2026-09-21T12:00:00+00:00',
    });
  });

  it('reads a snapshot entry, which has connected_at and no message time of its own', () => {
    const user = presenceUserFromWire({
      user_id: 'u-2',
      user_name: 'Ivo',
      route: '/boq/1',
      status: 'idle',
      connected_at: '2026-09-21T11:00:00+00:00',
    });
    expect(user?.status).toBe('idle');
    expect(user?.last_active).toBe('2026-09-21T11:00:00+00:00');
  });

  it('drops a message without a user id instead of throwing', () => {
    expect(presenceUserFromWire({ user_id: '' })).toBeNull();
    expect(presenceUserFromWire({} as { user_id: string })).toBeNull();
  });
});
