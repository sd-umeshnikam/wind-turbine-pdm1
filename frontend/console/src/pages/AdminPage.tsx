import { UserPlus } from "lucide-react";
import { useMemo, useState } from "react";
import { useAudit, useCreateUser, useUpdateUser, useUsers } from "../api/hooks";
import type { Role, User } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../components/Toasts";
import { Badge, Card, Dialog, Empty, PageHead, QueryView, Tabs } from "../components/ui";
import { ago, wallTime } from "../lib/format";

const ROLES: Role[] = ["viewer", "engineer", "admin"];
const PAGE = 50;

function CreateUser({ onClose }: { onClose: () => void }) {
  const toast = useToast();
  const create = useCreateUser();
  const [form, setForm] = useState({ username: "", display_name: "", password: "", role: "viewer" as Role });
  const valid = /^[a-z0-9][a-z0-9._-]{2,63}$/.test(form.username) && form.display_name.trim() && form.password.length >= 12;
  return (
    <Dialog title="Add user" onClose={onClose}>
      <form
        className="stack"
        style={{ gap: 12 }}
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate(form, {
            onSuccess: () => {
              toast(`User ${form.username} created`);
              onClose();
            },
            onError: (err) => toast(err.message, "error"),
          });
        }}
      >
        <div className="field">
          <label htmlFor="u-name">Username (lowercase letters, digits, . _ -)</label>
          <input id="u-name" className="input" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value.toLowerCase() })} required />
        </div>
        <div className="field">
          <label htmlFor="u-display">Display name</label>
          <input id="u-display" className="input" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} required />
        </div>
        <div className="field">
          <label htmlFor="u-pass">Initial password (at least 12 characters)</label>
          <input id="u-pass" className="input" type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
        </div>
        <div className="field">
          <label htmlFor="u-role">Role</label>
          <select id="u-role" className="select" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn primary" disabled={!valid || create.isPending}>
            Create user
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function ResetPassword({ user, onClose }: { user: User; onClose: () => void }) {
  const toast = useToast();
  const update = useUpdateUser();
  const [password, setPassword] = useState("");
  return (
    <Dialog title={`Reset password: ${user.username}`} onClose={onClose}>
      <form
        className="stack"
        style={{ gap: 12 }}
        onSubmit={(e) => {
          e.preventDefault();
          update.mutate(
            { username: user.username, password },
            {
              onSuccess: () => {
                toast("Password changed");
                onClose();
              },
              onError: (err) => toast(err.message, "error"),
            },
          );
        }}
      >
        <div className="field">
          <label htmlFor="p-new">New password (at least 12 characters)</label>
          <input id="p-new" className="input" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn primary" disabled={password.length < 12 || update.isPending}>
            Change password
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function Users() {
  const { user: me } = useAuth();
  const toast = useToast();
  const users = useUsers(true);
  const update = useUpdateUser();
  const [creating, setCreating] = useState(false);
  const [resetting, setResetting] = useState<User | null>(null);
  const change = (username: string, body: Partial<User>, done: string) =>
    update.mutate({ username, ...body }, { onSuccess: () => toast(done), onError: (e) => toast(e.message, "error") });

  return (
    <Card
      title="Users"
      hint="viewer: read · engineer: work alerts · admin: users, retraining, approvals"
      tools={
        <button className="btn primary" onClick={() => setCreating(true)}>
          <UserPlus size={14} /> Add user
        </button>
      }
      flush
    >
      <QueryView query={users} height={200}>
        {(list) => (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>User</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Last visit</th>
                  <th>Created</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {list.map((u) => {
                  const self = u.username === me?.username;
                  return (
                    <tr key={u.username}>
                      <td>
                        <div style={{ fontWeight: 600 }}>{u.display_name}</div>
                        <div className="subtle">{u.username}</div>
                      </td>
                      <td>
                        <select
                          className="select"
                          value={u.role}
                          disabled={self || update.isPending}
                          aria-label={`Role of ${u.username}`}
                          onChange={(e) => change(u.username, { role: e.target.value as Role }, `${u.username} is now ${e.target.value}`)}
                        >
                          {ROLES.map((r) => (
                            <option key={r} value={r}>
                              {r}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>{u.is_active ? <Badge tone="good">active</Badge> : <Badge tone="neutral">deactivated</Badge>}</td>
                      <td>{u.last_seen_at ? ago(u.last_seen_at) : "never"}</td>
                      <td>{wallTime(u.created_at)}</td>
                      <td>
                        <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                          <button className="btn sm" onClick={() => setResetting(u)}>
                            Reset password
                          </button>
                          {!self && (
                            <button
                              className={`btn sm ${u.is_active ? "danger" : ""}`}
                              disabled={update.isPending}
                              onClick={() =>
                                change(u.username, { is_active: !u.is_active }, `${u.username} ${u.is_active ? "deactivated" : "reactivated"}`)
                              }
                            >
                              {u.is_active ? "Deactivate" : "Reactivate"}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </QueryView>
      {creating && <CreateUser onClose={() => setCreating(false)} />}
      {resetting && <ResetPassword user={resetting} onClose={() => setResetting(null)} />}
    </Card>
  );
}

function Audit() {
  const [group, setGroup] = useState("");
  const [actor, setActor] = useState("");
  const [page, setPage] = useState(0);
  const filters = useMemo(
    () => ({ action: group || undefined, actor: actor.trim() || undefined, limit: PAGE, offset: page * PAGE }),
    [group, actor, page],
  );
  const audit = useAudit(filters, true);
  return (
    <Card
      title="Audit log"
      hint="every sign-in, alert action, model change and retrain"
      tools={
        <>
          <select className="select" value={group} onChange={(e) => (setGroup(e.target.value), setPage(0))} aria-label="Action group">
            <option value="">All actions</option>
            <option value="alert.">Alerts</option>
            <option value="model.">Models</option>
            <option value="retrain.">Retraining</option>
            <option value="user.">Users</option>
            <option value="auth.">Sign-ins</option>
            <option value="catalog.">Catalog</option>
          </select>
          <input className="input" placeholder="Actor" value={actor} onChange={(e) => (setActor(e.target.value), setPage(0))} aria-label="Actor" style={{ width: 160 }} />
        </>
      }
      flush
    >
      <QueryView query={audit} height={300}>
        {(p) =>
          p.items.length ? (
            <>
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>When</th>
                      <th>Actor</th>
                      <th>Action</th>
                      <th>Entity</th>
                      <th>Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {p.items.map((a) => (
                      <tr key={a.id}>
                        <td style={{ whiteSpace: "nowrap" }}>{wallTime(a.ts)}</td>
                        <td>{a.actor}</td>
                        <td>
                          <code>{a.action}</code>
                        </td>
                        <td>
                          {a.entity}
                          {a.entity_id && <div className="subtle mono">{a.entity_id.slice(0, 36)}</div>}
                        </td>
                        <td className="mono" style={{ maxWidth: 420, overflowWrap: "anywhere" }}>
                          {a.details ? JSON.stringify(a.details) : ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="pager">
                <span>
                  {page * PAGE + 1}–{Math.min((page + 1) * PAGE, p.total)} of {p.total.toLocaleString()}
                </span>
                <button className="btn sm" disabled={page === 0} onClick={() => setPage(page - 1)}>
                  Previous
                </button>
                <button className="btn sm" disabled={(page + 1) * PAGE >= p.total} onClick={() => setPage(page + 1)}>
                  Next
                </button>
              </div>
            </>
          ) : (
            <Empty title="No audit entries match" />
          )
        }
      </QueryView>
    </Card>
  );
}

export function AdminPage() {
  const { can } = useAuth();
  const [tab, setTab] = useState<"users" | "audit">(can("admin") ? "users" : "audit");
  if (!can("engineer")) return <Empty title="Not permitted">The audit log needs the engineer role.</Empty>;
  return (
    <>
      <PageHead title={can("admin") ? "Users & audit" : "Audit log"} lede="Access control and the platform's record of who did what, and when." />
      {can("admin") && (
        <Tabs
          value={tab}
          onChange={setTab}
          tabs={[
            { id: "users", label: "Users" },
            { id: "audit", label: "Audit log" },
          ]}
        />
      )}
      {tab === "users" && can("admin") ? <Users /> : <Audit />}
    </>
  );
}
