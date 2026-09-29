import React, { useMemo, useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import { User } from '../types';
import { SafeMoveLogo } from './SafeMoveLogo';

interface AccessGateProps {
  users: User[];
  onEnter: (user: User) => void;
}

const roleLabel = (role: User['role']) => role.replaceAll('_', ' ');

export const AccessGate: React.FC<AccessGateProps> = ({ users, onEnter }) => {
  const [selectedUserId, setSelectedUserId] = useState(users[0]?.id ?? '');
  const selectedUser = useMemo(
    () => users.find((user) => user.id === selectedUserId),
    [selectedUserId, users]
  );

  const enterPortal = () => {
    if (selectedUser) onEnter(selectedUser);
  };

  return (
    <main className="min-h-screen bg-sm-bg p-4 flex items-center justify-center text-sm-text">
      <section className="w-full max-w-xl rounded-2xl bg-sm-panel border border-sm-border shadow-2xl overflow-hidden">
        <div className="bg-sm-panel-2 border-b border-sm-border p-7">
          <div className="flex items-center gap-3">
            <SafeMoveLogo variant="icon" size={40} />
            <div>
              <h1 className="text-xl font-extrabold tracking-tight">SafeMove AI</h1>
              <p className="text-xs text-sm-muted">National risk intelligence portal</p>
            </div>
          </div>
        </div>

        <div className="p-7 space-y-5">
          <div>
            <h2 className="font-bold text-lg">Choose your access context</h2>
            <p className="text-sm text-sm-muted mt-1">
              Sign in, then pick your region and map area from the Region Quick-Select in the sidebar.
            </p>
          </div>

          <label className="block text-sm font-semibold text-sm-text">
            Portal access role
            <select
              value={selectedUserId}
              onChange={(event) => setSelectedUserId(event.target.value)}
              className="mt-1.5 w-full rounded-lg border border-sm-border bg-sm-panel-2 p-2.5 text-sm text-sm-text focus:outline-none focus:ring-2 focus:ring-sm-green/40 focus:border-sm-green"
            >
              {users.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.full_name} — {roleLabel(user.role)}
                </option>
              ))}
            </select>
          </label>

          <button
            type="button"
            onClick={enterPortal}
            className="w-full rounded-lg bg-sm-green py-2.5 text-sm font-bold text-slate-900 hover:bg-sm-green-hover transition flex items-center justify-center gap-2 cursor-pointer"
          >
            <ShieldCheck className="w-4 h-4" />
            Enter portal
          </button>
        </div>
      </section>
    </main>
  );
};