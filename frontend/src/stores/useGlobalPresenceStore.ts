// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { create } from 'zustand';

export interface GlobalPresenceUser {
  user_id: string;
  user_name: string;
  route: string;
  status: 'active' | 'idle';
  last_active: string; // ISO timestamp
}

export type GlobalPresenceWsStatus =
  | 'idle'
  | 'connecting'
  | 'open'
  | 'closed'
  | 'error';

export interface GlobalPresenceState {
  users: Record<string, GlobalPresenceUser>; // keyed by user_id
  wsStatus: GlobalPresenceWsStatus;
  setUsers: (users: GlobalPresenceUser[]) => void;
  upsertUser: (user: GlobalPresenceUser) => void;
  removeUser: (userId: string) => void;
  setWsStatus: (status: GlobalPresenceWsStatus) => void;
  clear: () => void;
}

export const useGlobalPresenceStore = create<GlobalPresenceState>((set) => ({
  users: {},
  wsStatus: 'idle',

  setUsers: (users) => {
    const record: Record<string, GlobalPresenceUser> = {};
    for (const u of users) {
      record[u.user_id] = u;
    }
    set({ users: record });
  },

  upsertUser: (user) =>
    set((state) => ({
      users: { ...state.users, [user.user_id]: user },
    })),

  removeUser: (userId) =>
    set((state) => {
      const next = { ...state.users };
      delete next[userId];
      return { users: next };
    }),

  setWsStatus: (wsStatus) => set({ wsStatus }),

  clear: () => set({ users: {}, wsStatus: 'idle' }),
}));
