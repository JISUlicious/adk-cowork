/**
 * Settings overlay — single home for every runtime knob.
 *
 *   Account      → Profile (read-only user identity), Workspace (root + tier).
 *   Agents       → Roster (4 specialists), Tools & MCP (server-reported),
 *                  Approvals policy (per-session python_exec / mode).
 *   System       → Config path, runtime backend, health components.
 *   Appearance   → Theme · Density · Accent · Layout · Tool-call style ·
 *                  Approval style.  This is the home for what the design
 *                  prototype called "Tweaks" — users get real controls,
 *                  no hidden dev panel.
 *
 * Persistence: server-side knobs go through ``CoworkClient`` per-session
 * endpoints; appearance prefs go through ``usePreferences`` (localStorage
 * + custom event for live updates).
 */

import { useEffect, useRef, useState } from "react";
import type { CoworkClient } from "../transport/client";
import type {
  AddMcpServerRequest,
  ConfigCompactionPatch,
  ConfigModelPatch,
  HealthInfo,
  McpServerRecord,
  McpTransport,
  MemoryPageInfo,
  PolicyMode,
  PythonExecPolicy,
  UserProfile,
} from "../transport/types";
import { usePreferences } from "../preferences";
import {
  type ThemeMode,
  applyThemeMode,
  persistThemeMode,
} from "../theme";
import { agentStyle, AgentStack, Icon } from "./atoms";

interface Props {
  client: CoworkClient;
  sessionId: string | null;
  userId?: string;
  /** Surface in use. ``local`` hides tools that are no-ops in local-dir
   *  mode (e.g. ``fs_promote`` which moves scratch → files/ on managed
   *  projects but has no meaning under an arbitrary workdir). */
  surface?: "managed" | "local";
  onClose: () => void;
}

type TabId =
  | "profile"
  | "workspace"
  | "agents"
  | "approvals"
  | "memory"
  | "system"
  | "appearance";

const NAV: { group: string; items: { id: TabId; label: string; icon: string }[] }[] = [
  {
    group: "Account",
    items: [
      { id: "profile", label: "Profile", icon: "user" },
      { id: "workspace", label: "Workspace", icon: "folder" },
    ],
  },
  {
    group: "Agents",
    items: [
      // "Agent roster" and "Tools & MCP" were two nav entries in V6;
      // Phase F.P1 merges them into a single read-only pane since
      // both sourced from ``/v1/health``.
      { id: "agents", label: "Agents & tools", icon: "brain" },
      { id: "approvals", label: "Approvals policy", icon: "shield" },
      // Slice T2 — memory page management. Adjacent to Skills + MCP
      // conceptually (all three are agent-facing knowledge surfaces).
      { id: "memory", label: "Memory", icon: "brain" },
    ],
  },
  {
    group: "System",
    items: [
      { id: "system", label: "System", icon: "settings" },
      { id: "appearance", label: "Appearance", icon: "bolt" },
    ],
  },
];

export function Settings({ client, sessionId, userId, surface, onClose }: Props) {
  const [tab, setTab] = useState<TabId>("appearance");

  // Close on Escape
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-panel" onClick={(e) => e.stopPropagation()}>
        <div className="hd">
          <div className="t">Settings</div>
          <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-3)" }}>
            {userId ?? "local"}
          </span>
          <button className="close" type="button" onClick={onClose}>
            <Icon name="close" size={15} />
          </button>
        </div>
        <div className="body-row">
          <nav>
            {NAV.map((g) => (
              <div key={g.group}>
                <div className="grp">{g.group}</div>
                {g.items.map((it) => (
                  <a
                    key={it.id}
                    className={tab === it.id ? "active" : ""}
                    onClick={() => setTab(it.id)}
                  >
                    <span className="nav-item">
                      <Icon name={it.icon} size={13} /> {it.label}
                    </span>
                  </a>
                ))}
              </div>
            ))}
          </nav>
          <div className="content">
            {tab === "profile" && <SecProfile client={client} userId={userId} />}
            {tab === "workspace" && <SecWorkspace />}
            {tab === "agents" && (
              <>
                <SecAgents
                  client={client}
                  sessionId={sessionId}
                  surface={surface}
                />
                <SecTools client={client} sessionId={sessionId} surface={surface} />
              </>
            )}
            {tab === "approvals" && <SecApprovals client={client} sessionId={sessionId} />}
            {tab === "memory" && <SecMemory client={client} sessionId={sessionId} />}
            {tab === "system" && <SecSystem client={client} />}
            {tab === "appearance" && <SecAppearance />}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ───────────────────── Account ───────────────────── */

function SecProfile({
  client,
  userId,
}: {
  client: CoworkClient;
  userId?: string;
}) {
  // Slice T2 — editable display name + email. user_id stays
  // read-only (sourced from the auth token). Profile persists in the
  // calling user's UserStore at ``settings/profile.json`` so multi-
  // user mode keeps each user's name/email isolated.
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedTick, setSavedTick] = useState(false);

  useEffect(() => {
    let cancelled = false;
    client
      .getProfile()
      .then((p) => {
        if (cancelled) return;
        setProfile(p);
        setDisplayName(p.display_name);
        setEmail(p.email);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [client]);

  const dirty =
    profile !== null &&
    (displayName !== profile.display_name || email !== profile.email);

  const onSave = async () => {
    if (!dirty || busy) return;
    setBusy(true);
    setError(null);
    setSavedTick(false);
    try {
      const next = await client.updateProfile({
        display_name: displayName,
        email,
      });
      setProfile(next);
      setSavedTick(true);
      window.setTimeout(() => setSavedTick(false), 1500);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const onReset = () => {
    if (!profile) return;
    setDisplayName(profile.display_name);
    setEmail(profile.email);
    setError(null);
  };

  return (
    <div className="sec">
      <h3>Profile</h3>
      <div className="desc">
        Identity is taken from the API token you authenticated with.
        Display name and email persist per user — in multi-user mode
        each authenticated user has their own profile.
      </div>
      <Field label="User id" sub="From your auth token. Read-only.">
        <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-sm)" }}>
          {profile?.user_id ?? userId ?? "local"}
        </span>
      </Field>
      <Field
        label="Display name"
        sub="Shown in chat in place of your raw user id."
      >
        <input
          type="text"
          value={displayName}
          maxLength={80}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder="(unset)"
          style={editorInputStyle}
        />
      </Field>
      <Field label="Email" sub="Used for future notifications.">
        <input
          type="email"
          value={email}
          maxLength={200}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="(unset)"
          style={editorInputStyle}
        />
      </Field>
      {error && (
        <div style={{ fontSize: "var(--fs-xs)", color: "var(--danger)" }}>
          {error}
        </div>
      )}
      <div
        style={{
          display: "flex",
          gap: 8,
          alignItems: "center",
          marginTop: 4,
        }}
      >
        <button
          type="button"
          onClick={() => void onSave()}
          disabled={!dirty || busy}
          style={editorBtnStyle(busy || !dirty)}
        >
          {busy ? "saving…" : "Save"}
        </button>
        <button
          type="button"
          onClick={onReset}
          disabled={!dirty || busy}
          style={editorBtnStyle(!dirty)}
        >
          Reset
        </button>
        {savedTick && (
          <span
            style={{
              fontSize: "var(--fs-xs)",
              color: "var(--ok, #2a7)",
              fontFamily: "var(--mono)",
            }}
          >
            ✓ saved
          </span>
        )}
      </div>
    </div>
  );
}

const editorInputStyle: React.CSSProperties = {
  width: "100%",
  fontFamily: "var(--mono)",
  fontSize: 12,
  padding: "4px 6px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--line)",
  background: "var(--paper)",
  color: "var(--ink-1)",
};

function editorBtnStyle(disabled: boolean): React.CSSProperties {
  return {
    fontFamily: "var(--mono)",
    fontSize: 11,
    padding: "3px 12px",
    borderRadius: "var(--radius-sm)",
    border: "1px solid var(--line)",
    background: "var(--paper)",
    color: disabled ? "var(--ink-4)" : "var(--ink-2)",
    cursor: disabled ? "not-allowed" : "pointer",
  };
}

/** Slice U1 — small mono badge next to each editable field
 *  indicating where its current value comes from
 *  (``"db"`` = DB-overridden via the workspace_settings table,
 *  ``"toml"`` = cowork.toml default, anything else hides the badge).
 */
function SourceBadge({ value }: { value: string | undefined }) {
  if (value !== "db" && value !== "toml") return null;
  return (
    <span
      style={{
        marginLeft: 6,
        fontSize: 10,
        fontFamily: "var(--mono)",
        color: "var(--ink-3)",
        border: "1px solid var(--line)",
        borderRadius: 3,
        padding: "1px 4px",
      }}
      title={
        value === "db"
          ? "Override stored in multiuser.db (operator-edited via UI)"
          : "Default from cowork.toml"
      }
    >
      ({value})
    </span>
  );
}

function SecWorkspace() {
  return (
    <div className="sec">
      <h3>Workspace</h3>
      <div className="desc">
        Cowork keeps each user's projects in their own subtree under the
        workspace root. Multi-user mode is wired through ``[auth].keys`` in
        ``cowork.toml``.
      </div>
      <Field label="Layout">
        <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-sm)" }}>
          {"<workspace>/users/<uid>/projects/<slug>/"}
        </span>
      </Field>
    </div>
  );
}

/* ───────────────────── Agents ───────────────────── */

const AGENT_ROSTER = [
  { id: "researcher", name: "Ada", role: "research", about: "gathers sources, summarizes findings" },
  { id: "writer", name: "Orson", role: "writer", about: "drafts, revises, narrative" },
  { id: "analyst", name: "Iris", role: "analysis", about: "tables, charts, numbers" },
  { id: "reviewer", name: "Kit", role: "review", about: "edits, sanity-checks, runs commands" },
];

function SecAgents({
  client,
  sessionId,
  surface,
}: {
  client: CoworkClient;
  sessionId: string | null;
  surface?: "managed" | "local";
}) {
  const [allowlist, setAllowlist] = useState<Record<string, string[]>>({});
  const [tools, setTools] = useState<string[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    client
      .health()
      .then((h) =>
        setTools(
          (h.tools ?? []).filter(
            (t) => !(surface === "local" && LOCAL_MODE_HIDDEN_TOOLS.has(t)),
          ),
        ),
      )
      .catch(() => {});
  }, [client, surface]);

  useEffect(() => {
    if (!sessionId) {
      setAllowlist({});
      return;
    }
    client
      .getSessionToolAllowlist(sessionId)
      .then(setAllowlist)
      .catch(() => setAllowlist({}));
  }, [client, sessionId]);

  const toggleOpen = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const isRestricted = (agentId: string) =>
    Object.prototype.hasOwnProperty.call(allowlist, agentId);

  const effectiveTools = (agentId: string): Set<string> => {
    if (!isRestricted(agentId)) return new Set(tools);
    return new Set(allowlist[agentId] ?? []);
  };

  const persist = async (next: Record<string, string[]>) => {
    if (!sessionId) return;
    const prev = allowlist;
    setAllowlist(next);
    try {
      const confirmed = await client.setSessionToolAllowlist(sessionId, next);
      setAllowlist(confirmed);
    } catch {
      setAllowlist(prev);
    }
  };

  const setAgentAllowlist = (agentId: string, nextTools: string[] | null) => {
    const next: Record<string, string[]> = { ...allowlist };
    if (nextTools === null) delete next[agentId];
    else next[agentId] = nextTools;
    void persist(next);
  };

  const toggleTool = (agentId: string, tool: string) => {
    const current = effectiveTools(agentId);
    const next = new Set(current);
    if (next.has(tool)) next.delete(tool);
    else next.add(tool);
    // Preserve input order (matches the catalog) for stable diffs.
    setAgentAllowlist(agentId, tools.filter((t) => next.has(t)));
  };

  return (
    <div className="sec">
      <h3>Agent roster</h3>
      <div className="desc">
        Cowork ships four specialists. Expand an agent to restrict its tool
        access for this session. The root agent is unrestricted by design —
        if you need to block a tool everywhere, use the policy knobs in
        Approvals instead.
      </div>
      {AGENT_ROSTER.map((a) => {
        const s = agentStyle(a.id);
        const restricted = isRestricted(a.id);
        const allowed = effectiveTools(a.id);
        const isOpen = expanded.has(a.id);
        const summary = restricted
          ? `${allowed.size} of ${tools.length} tools`
          : `all ${tools.length} tools`;
        return (
          <div
            key={a.id}
            style={{
              marginBottom: 10,
              border: "1px solid var(--line)",
              borderRadius: "var(--radius-md)",
              overflow: "hidden",
              background: "var(--paper)",
            }}
          >
            <button
              type="button"
              onClick={() => toggleOpen(a.id)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                width: "100%",
                padding: "10px 12px",
                background: "transparent",
                textAlign: "left",
                cursor: "pointer",
              }}
            >
              <span
                style={{
                  width: 28,
                  height: 28,
                  borderRadius: "50%",
                  background: s.color,
                  color: "white",
                  display: "grid",
                  placeItems: "center",
                  fontFamily: "var(--serif)",
                  fontSize: 14,
                  flexShrink: 0,
                }}
              >
                {s.letter}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    fontFamily: "var(--serif)",
                    fontSize: "var(--fs-md)",
                    color: "var(--ink)",
                  }}
                >
                  {a.name}
                </div>
                <div style={{ fontSize: "var(--fs-xs)", color: "var(--ink-4)" }}>
                  {a.role} · {a.about}
                </div>
              </div>
              <span
                style={{
                  fontFamily: "var(--mono)",
                  fontSize: 11,
                  color: restricted ? "var(--warn)" : "var(--ink-4)",
                  flexShrink: 0,
                }}
              >
                {summary}
              </span>
              <Icon name={isOpen ? "chevD" : "chevR"} size={11} />
            </button>
            {isOpen && (
              <div
                style={{
                  padding: "10px 12px",
                  borderTop: "1px solid var(--line)",
                  background: "var(--paper-2)",
                }}
              >
                {!sessionId ? (
                  <div
                    style={{
                      fontSize: "var(--fs-xs)",
                      color: "var(--ink-3)",
                      fontFamily: "var(--serif)",
                    }}
                  >
                    Open a session to configure tool access.
                  </div>
                ) : (
                  <>
                    <div
                      style={{
                        display: "flex",
                        gap: 12,
                        marginBottom: 8,
                        fontSize: "var(--fs-xs)",
                        fontFamily: "var(--mono)",
                      }}
                    >
                      <button
                        type="button"
                        onClick={() => setAgentAllowlist(a.id, null)}
                        style={{
                          color: restricted ? "var(--accent)" : "var(--ink-4)",
                          cursor: "pointer",
                        }}
                      >
                        allow all
                      </button>
                      <button
                        type="button"
                        onClick={() => setAgentAllowlist(a.id, [])}
                        style={{
                          color: "var(--danger)",
                          cursor: "pointer",
                        }}
                      >
                        block all
                      </button>
                    </div>
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "repeat(2, 1fr)",
                        gap: 4,
                      }}
                    >
                      {tools.map((t) => (
                        <label
                          key={t}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 6,
                            fontFamily: "var(--mono)",
                            fontSize: 11,
                            color: "var(--ink-2)",
                            cursor: "pointer",
                          }}
                        >
                          <input
                            type="checkbox"
                            checked={allowed.has(t)}
                            onChange={() => toggleTool(a.id, t)}
                          />
                          <span
                            style={{
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                            }}
                          >
                            {t}
                          </span>
                        </label>
                      ))}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

const LOCAL_MODE_HIDDEN_TOOLS = new Set(["fs_promote"]);

function SecTools({
  client,
  sessionId,
  surface,
}: {
  client: CoworkClient;
  sessionId: string | null;
  surface?: "managed" | "local";
}) {
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [installBusy, setInstallBusy] = useState(false);
  const [installError, setInstallError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // Slice II — per-session skill enable overrides. Empty map = all
  // enabled (the default). Loaded once per session change; the row
  // toggle does an optimistic flip + PUT, with revert on failure.
  const [skillsEnabled, setSkillsEnabled] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (!sessionId) {
      setSkillsEnabled({});
      return;
    }
    client
      .getSessionSkillsEnabled(sessionId)
      .then(setSkillsEnabled)
      .catch(() => setSkillsEnabled({}));
  }, [client, sessionId]);

  const isSkillEnabled = (name: string) => skillsEnabled[name] !== false;
  const toggleSkillEnabled = async (name: string) => {
    if (!sessionId) return;
    const next = { ...skillsEnabled, [name]: !isSkillEnabled(name) };
    setSkillsEnabled(next);
    try {
      const applied = await client.setSessionSkillsEnabled(sessionId, next);
      setSkillsEnabled(applied);
    } catch {
      setSkillsEnabled(skillsEnabled);
    }
  };

  const refreshHealth = () => {
    client
      .health()
      .then(setHealth)
      .catch((e) => setError(String(e)));
  };

  useEffect(() => {
    refreshHealth();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  const onInstallPicked = async (files: FileList | null) => {
    if (!files || !files.length) return;
    setInstallBusy(true);
    setInstallError(null);
    try {
      await client.installSkill(files[0], files[0].name);
      refreshHealth();
    } catch (e) {
      setInstallError(String(e));
    } finally {
      setInstallBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const onUninstallClick = async (name: string) => {
    if (!window.confirm(`Uninstall skill "${name}"? The folder and all its files will be removed.`)) {
      return;
    }
    try {
      await client.uninstallSkill(name);
      refreshHealth();
    } catch (e) {
      setInstallError(String(e));
    }
  };

  const visibleTools = (health?.tools ?? []).filter(
    (t) => !(surface === "local" && LOCAL_MODE_HIDDEN_TOOLS.has(t)),
  );

  if (error) {
    return (
      <div className="sec">
        <h3>Tools & MCP servers</h3>
        <div className="desc" style={{ color: "var(--danger)" }}>
          Failed to load: {error}
        </div>
      </div>
    );
  }

  return (
    <div className="sec">
      <h3>Tools & MCP servers</h3>
      <div className="desc">
        Tools registered with the running Cowork server. Per-agent
        access is configured in the Agent roster above; the monogram
        stack on each row is purely decorative here.
      </div>
      {visibleTools.map((t) => (
        <Field
          key={t}
          label={<span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-sm)" }}>{t}</span>}
          sub={describeTool(t)}
        >
          <AgentStack agents={["researcher", "writer", "analyst", "reviewer"]} size={16} />
        </Field>
      ))}
      <McpServersBlock
        client={client}
        sessionId={sessionId}
        onChanged={refreshHealth}
      />
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 12,
          marginTop: 24,
        }}
      >
        <h3 style={{ margin: 0, flex: 1 }}>Skills</h3>
        <input
          ref={fileInputRef}
          type="file"
          accept=".zip,application/zip"
          style={{ display: "none" }}
          onChange={(e) => void onInstallPicked(e.target.files)}
        />
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={installBusy}
          style={{
            fontFamily: "var(--mono)",
            fontSize: 11,
            padding: "3px 10px",
            borderRadius: "var(--radius-sm)",
            border: "1px solid var(--line)",
            background: "var(--paper)",
            color: installBusy ? "var(--ink-4)" : "var(--ink-2)",
            cursor: installBusy ? "wait" : "pointer",
          }}
          title="Install a skill from a .zip archive"
        >
          {installBusy ? "installing…" : "+ install (.zip)"}
        </button>
      </div>
      <div className="desc">
        Skill packs the agent can load on demand. The agent sees
        name + description in its prompt registry and calls
        <code style={{ margin: "0 4px" }}>load_skill(name)</code>
        to pull the body into context. Bundled skills ship with
        Cowork; user-installed skills live under
        <code style={{ margin: "0 4px" }}>&lt;workspace&gt;/global/skills/</code>.
      </div>
      {installError && (
        <div
          style={{
            fontSize: "var(--fs-xs)",
            color: "var(--danger)",
            marginBottom: 8,
          }}
        >
          {installError}
        </div>
      )}
      {(health?.skills ?? []).length === 0 ? (
        <div style={{ fontSize: "var(--fs-sm)", color: "var(--ink-3)" }}>No skills installed.</div>
      ) : (
        (health?.skills ?? []).map((s) => {
          const removable = s.source === "user";
          const enabled = isSkillEnabled(s.name);
          return (
            <Field
              key={s.name}
              label={
                <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-sm)" }}>
                  {s.name}
                </span>
              }
              sub={s.description}
            >
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                  opacity: enabled ? 1 : 0.55,
                }}
              >
                <button
                  type="button"
                  onClick={() => sessionId && void toggleSkillEnabled(s.name)}
                  disabled={!sessionId}
                  title={
                    !sessionId
                      ? "Open a session to toggle"
                      : enabled
                        ? "Disable for this session — hidden from prompt; load_skill refused"
                        : "Re-enable for this session"
                  }
                  style={{
                    fontSize: "var(--fs-xs)",
                    fontFamily: "var(--mono)",
                    padding: "1px 6px",
                    borderRadius: "var(--radius-sm)",
                    border: "1px solid var(--line)",
                    background: enabled ? "var(--paper)" : "var(--paper-2)",
                    color: enabled ? "var(--ok, #2a7)" : "var(--ink-4)",
                    cursor: sessionId ? "pointer" : "not-allowed",
                  }}
                >
                  {enabled ? "on" : "off"}
                </button>
                {s.version && s.version !== "0.0.0" && (
                  <span
                    style={{
                      color: "var(--ink-3)",
                      fontSize: "var(--fs-xs)",
                      fontFamily: "var(--mono)",
                      padding: "1px 6px",
                      border: "1px solid var(--line)",
                      borderRadius: "var(--radius-sm)",
                    }}
                    title={`Skill version${s.content_hash ? ` · sha256:${s.content_hash.slice(0, 12)}…` : ""}`}
                  >
                    v{s.version}
                  </span>
                )}
                <span
                  style={{
                    color: "var(--ink-4)",
                    fontSize: "var(--fs-xs)",
                    fontFamily: "var(--mono)",
                  }}
                  title={`Skill license · source: ${s.source}`}
                >
                  {s.license}
                </span>
                <button
                  type="button"
                  onClick={() => removable && void onUninstallClick(s.name)}
                  disabled={!removable}
                  title={
                    removable
                      ? "Uninstall"
                      : `Bundled skill — cannot uninstall (source: ${s.source})`
                  }
                  style={{
                    width: 20,
                    height: 20,
                    display: "grid",
                    placeItems: "center",
                    fontSize: 13,
                    color: removable ? "var(--ink-3)" : "var(--ink-4)",
                    opacity: removable ? 1 : 0.4,
                    cursor: removable ? "pointer" : "not-allowed",
                    background: "transparent",
                  }}
                >
                  {removable ? "×" : "🔒"}
                </button>
              </span>
            </Field>
          );
        })
      )}
    </div>
  );
}

/* ───────────────────── MCP servers ───────────────────── */

/** Slice IV — render + manage user-installed MCP servers. Sits between
 *  the Tools list and the Skills list inside the Agents tab. The list
 *  pairs each ``McpServerInfo`` with the live ``MCPServerStatusInfo``
 *  from the last toolset build, so the green/red pill matches what
 *  Settings → System renders. Bundled servers (declared in
 *  ``cowork.toml``) carry the lock icon — delete is gated. */
function McpServersBlock({
  client,
  sessionId,
  onChanged,
}: {
  client: import("../transport/client").CoworkClient;
  sessionId: string | null;
  onChanged: () => void;
}) {
  const [records, setRecords] = useState<McpServerRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [discovered, setDiscovered] = useState<{ name: string; tools: string[] } | null>(null);
  // Slice VI — per-session MCP disable list. Empty = all enabled
  // (default). Loaded once per session change; the row toggle does
  // an optimistic flip + PUT, with revert on failure.
  const [mcpDisabled, setMcpDisabled] = useState<string[]>([]);

  useEffect(() => {
    if (!sessionId) {
      setMcpDisabled([]);
      return;
    }
    client
      .getSessionMcpDisabled(sessionId)
      .then(setMcpDisabled)
      .catch(() => setMcpDisabled([]));
  }, [client, sessionId]);

  const isMcpEnabled = (name: string) => !mcpDisabled.includes(name);
  const toggleMcpEnabled = async (name: string) => {
    if (!sessionId) return;
    const next = mcpDisabled.includes(name)
      ? mcpDisabled.filter((s) => s !== name)
      : [...mcpDisabled, name];
    setMcpDisabled(next);
    try {
      const applied = await client.setSessionMcpDisabled(sessionId, next);
      setMcpDisabled(applied);
    } catch {
      setMcpDisabled(mcpDisabled);
    }
  };

  const refresh = () => {
    client
      .listMcpServers()
      .then((rs) => {
        setRecords(rs);
        setError(null);
      })
      .catch((e) => setError(String(e)));
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  const onDelete = async (name: string) => {
    if (!window.confirm(`Remove MCP server "${name}"? Takes effect on next restart.`)) {
      return;
    }
    try {
      await client.deleteMcpServer(name);
      refresh();
      onChanged();
    } catch (e) {
      setError(String(e));
    }
  };

  const onRestart = async () => {
    if (!window.confirm("Restart MCP toolsets? In-flight turns will terminate.")) {
      return;
    }
    setBusy(true);
    try {
      await client.restartMcp();
      refresh();
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 12,
          marginTop: 24,
        }}
      >
        <h3 style={{ margin: 0, flex: 1 }}>MCP servers</h3>
        <button
          type="button"
          onClick={() => void onRestart()}
          disabled={busy || (records?.length ?? 0) === 0}
          style={mcpBtnStyle(busy)}
          title="Re-mount toolsets from the current effective config"
        >
          {busy ? "restarting…" : "↻ restart"}
        </button>
        <button
          type="button"
          onClick={() => setAdding((v) => !v)}
          style={mcpBtnStyle(false)}
          title="Add a new MCP server"
        >
          {adding ? "cancel" : "+ add server"}
        </button>
      </div>
      <div className="desc">
        Model Context Protocol servers expose external tools to the
        agent. Bundled servers come from{" "}
        <code style={{ margin: "0 4px" }}>cowork.toml</code>; user
        servers persist to{" "}
        <code style={{ margin: "0 4px" }}>&lt;workspace&gt;/global/mcp/servers.json</code>.
        Add/remove takes effect on the next restart.
      </div>
      {error && (
        <div
          style={{
            fontSize: "var(--fs-xs)",
            color: "var(--danger)",
            marginBottom: 8,
          }}
        >
          {error}
        </div>
      )}
      {adding && (
        <McpAddForm
          client={client}
          onCancel={() => setAdding(false)}
          onSaved={(name, tools) => {
            setAdding(false);
            setDiscovered({ name, tools });
            refresh();
            onChanged();
          }}
        />
      )}
      {discovered && (
        <div
          style={{
            fontSize: "var(--fs-xs)",
            color: "var(--ink-3)",
            background: "var(--paper-2)",
            border: "1px solid var(--line)",
            borderRadius: "var(--radius-sm)",
            padding: "6px 10px",
            margin: "8px 0",
          }}
        >
          <div>
            Saved <code>{discovered.name}</code>. Discovered tools:
          </div>
          <div style={{ fontFamily: "var(--mono)", marginTop: 4 }}>
            {discovered.tools.length === 0 ? "(none)" : discovered.tools.join(", ")}
          </div>
          <div style={{ marginTop: 4 }}>
            Click <strong>↻ restart</strong> to make these available to the agent.
            To filter the tool list, edit{" "}
            <code>servers.json</code> and re-add with{" "}
            <code>tool_filter</code>.
          </div>
        </div>
      )}
      {records === null ? (
        <div style={{ fontSize: "var(--fs-sm)", color: "var(--ink-3)" }}>Loading…</div>
      ) : records.length === 0 ? (
        <div style={{ fontSize: "var(--fs-sm)", color: "var(--ink-3)" }}>
          No MCP servers configured.
        </div>
      ) : (
        records.map(({ server, status }) => (
          <Field
            key={server.name}
            label={
              <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-sm)" }}>
                {server.name}
              </span>
            }
            sub={server.description || mcpEndpointSummary(server)}
          >
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                opacity: isMcpEnabled(server.name) ? 1 : 0.55,
              }}
            >
              <button
                type="button"
                onClick={() => sessionId && void toggleMcpEnabled(server.name)}
                disabled={!sessionId}
                title={
                  !sessionId
                    ? "Open a session to toggle"
                    : isMcpEnabled(server.name)
                      ? "Disable for this session — tools blocked at the agent layer"
                      : "Re-enable for this session"
                }
                style={{
                  fontSize: "var(--fs-xs)",
                  fontFamily: "var(--mono)",
                  padding: "1px 6px",
                  borderRadius: "var(--radius-sm)",
                  border: "1px solid var(--line)",
                  background: isMcpEnabled(server.name) ? "var(--paper)" : "var(--paper-2)",
                  color: isMcpEnabled(server.name) ? "var(--ok, #2a7)" : "var(--ink-4)",
                  cursor: sessionId ? "pointer" : "not-allowed",
                }}
              >
                {isMcpEnabled(server.name) ? "on" : "off"}
              </button>
              <span
                title={
                  status.status === "error"
                    ? status.last_error ?? "error"
                    : `${status.tool_count ?? "?"} tool(s)`
                }
                style={{
                  fontSize: "var(--fs-xs)",
                  fontFamily: "var(--mono)",
                  padding: "1px 6px",
                  border: "1px solid var(--line)",
                  borderRadius: "var(--radius-sm)",
                  color: status.status === "ok" ? "var(--ok, #2a7)" : "var(--danger)",
                }}
              >
                {status.status === "ok" ? `ok · ${status.tool_count ?? 0}` : "error"}
              </span>
              <span
                title={`Transport: ${server.transport}`}
                style={{
                  color: "var(--ink-4)",
                  fontSize: "var(--fs-xs)",
                  fontFamily: "var(--mono)",
                }}
              >
                {server.transport}
              </span>
              <button
                type="button"
                onClick={() => !server.bundled && void onDelete(server.name)}
                disabled={server.bundled}
                title={
                  server.bundled
                    ? "Bundled server — declared in cowork.toml"
                    : "Remove"
                }
                style={{
                  width: 20,
                  height: 20,
                  display: "grid",
                  placeItems: "center",
                  fontSize: 13,
                  color: server.bundled ? "var(--ink-4)" : "var(--ink-3)",
                  opacity: server.bundled ? 0.4 : 1,
                  cursor: server.bundled ? "not-allowed" : "pointer",
                  background: "transparent",
                }}
              >
                {server.bundled ? "🔒" : "×"}
              </button>
            </span>
          </Field>
        ))
      )}
    </div>
  );
}

function mcpBtnStyle(disabled: boolean): React.CSSProperties {
  return {
    fontFamily: "var(--mono)",
    fontSize: 11,
    padding: "3px 10px",
    borderRadius: "var(--radius-sm)",
    border: "1px solid var(--line)",
    background: "var(--paper)",
    color: disabled ? "var(--ink-4)" : "var(--ink-2)",
    cursor: disabled ? "wait" : "pointer",
  };
}

function mcpEndpointSummary(server: {
  transport: McpTransport;
  command: string;
  args: string[];
  url: string;
}): string {
  if (server.transport === "stdio") {
    const parts = [server.command, ...server.args].filter(Boolean);
    return parts.length ? parts.join(" ") : "(stdio: missing command)";
  }
  return server.url || `(${server.transport}: missing url)`;
}

/** Slice V — pre-filled configs for the three official Anthropic MCP
 *  servers documented in `docs/MCP.md`. The dropdown drops the user
 *  into the closest-to-correct shape; they fill in the
 *  workspace-specific bits (path, token, name) themselves. None of
 *  these ship as a *runtime* default — Cowork stays neutral on
 *  which servers a workspace cares about. */
const MCP_PRESETS: Record<
  string,
  {
    label: string;
    name: string;
    transport: McpTransport;
    command?: string;
    args?: string;
    env?: string;
    description: string;
  }
> = {
  filesystem: {
    label: "Filesystem (npx · @modelcontextprotocol/server-filesystem)",
    name: "fs",
    transport: "stdio",
    command: "npx",
    args: "-y\n@modelcontextprotocol/server-filesystem\n/path/to/dir",
    env: "",
    description: "Filesystem MCP server (read/write under a directory)",
  },
  github: {
    label: "GitHub (npx · @modelcontextprotocol/server-github)",
    name: "github",
    transport: "stdio",
    command: "npx",
    args: "-y\n@modelcontextprotocol/server-github",
    env: "GITHUB_PERSONAL_ACCESS_TOKEN=env:GITHUB_TOKEN",
    description: "GitHub API",
  },
  memory: {
    label: "Memory (npx · @modelcontextprotocol/server-memory)",
    name: "memory",
    transport: "stdio",
    command: "npx",
    args: "-y\n@modelcontextprotocol/server-memory",
    env: "",
    description: "Persistent key-value memory",
  },
};

function McpAddForm({
  client,
  onCancel,
  onSaved,
}: {
  client: import("../transport/client").CoworkClient;
  onCancel: () => void;
  onSaved: (name: string, tools: string[]) => void;
}) {
  const [name, setName] = useState("");
  const [transport, setTransport] = useState<McpTransport>("stdio");
  const [command, setCommand] = useState("");
  const [argsText, setArgsText] = useState("");
  const [envText, setEnvText] = useState("");
  const [url, setUrl] = useState("");
  const [headersText, setHeadersText] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const applyPreset = (key: string) => {
    if (!key) return;
    const preset = MCP_PRESETS[key];
    if (!preset) return;
    setName(preset.name);
    setTransport(preset.transport);
    setCommand(preset.command ?? "");
    setArgsText(preset.args ?? "");
    setEnvText(preset.env ?? "");
    setUrl("");
    setHeadersText("");
    setDescription(preset.description);
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const req: AddMcpServerRequest = {
        name: name.trim(),
        transport,
        description: description.trim(),
      };
      if (transport === "stdio") {
        req.command = command.trim();
        req.args = argsText
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean);
        req.env = parseKvLines(envText);
      } else {
        req.url = url.trim();
        req.headers = parseKvLines(headersText);
      }
      const res = await client.addMcpServer(req);
      onSaved(res.server.name, res.tools);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      onSubmit={(e) => void onSubmit(e)}
      style={{
        background: "var(--paper-2)",
        border: "1px solid var(--line)",
        borderRadius: "var(--radius-sm)",
        padding: 12,
        margin: "8px 0",
        display: "grid",
        gap: 8,
      }}
    >
      <McpFormRow label="Common servers">
        <select
          defaultValue=""
          onChange={(e) => {
            applyPreset(e.target.value);
            e.target.value = "";
          }}
          style={mcpInputStyle}
        >
          <option value="">— pick a preset to pre-fill —</option>
          {Object.entries(MCP_PRESETS).map(([key, preset]) => (
            <option key={key} value={key}>
              {preset.label}
            </option>
          ))}
        </select>
      </McpFormRow>
      <McpFormRow label="Name">
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          placeholder="my-server"
          style={mcpInputStyle}
        />
      </McpFormRow>
      <McpFormRow label="Transport">
        <select
          value={transport}
          onChange={(e) => setTransport(e.target.value as McpTransport)}
          style={mcpInputStyle}
        >
          <option value="stdio">stdio</option>
          <option value="sse">sse</option>
          <option value="http">http</option>
        </select>
      </McpFormRow>
      {transport === "stdio" ? (
        <>
          <McpFormRow label="Command">
            <input
              type="text"
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              placeholder="npx"
              style={mcpInputStyle}
            />
          </McpFormRow>
          <McpFormRow label="Args (one per line)">
            <textarea
              value={argsText}
              onChange={(e) => setArgsText(e.target.value)}
              rows={3}
              placeholder={"-y\n@modelcontextprotocol/server-filesystem\n/path/to/dir"}
              style={mcpInputStyle}
            />
          </McpFormRow>
          <McpFormRow label="Env (KEY=VAL, one per line)">
            <textarea
              value={envText}
              onChange={(e) => setEnvText(e.target.value)}
              rows={2}
              placeholder="GITHUB_TOKEN=env:GITHUB_TOKEN"
              style={mcpInputStyle}
            />
          </McpFormRow>
        </>
      ) : (
        <>
          <McpFormRow label="URL">
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com/mcp"
              style={mcpInputStyle}
            />
          </McpFormRow>
          <McpFormRow label="Headers (KEY=VAL, one per line)">
            <textarea
              value={headersText}
              onChange={(e) => setHeadersText(e.target.value)}
              rows={2}
              placeholder="Authorization=Bearer xxx"
              style={mcpInputStyle}
            />
          </McpFormRow>
        </>
      )}
      <McpFormRow label="Description">
        <input
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Shown in Settings"
          style={mcpInputStyle}
        />
      </McpFormRow>
      {error && (
        <div style={{ fontSize: "var(--fs-xs)", color: "var(--danger)" }}>{error}</div>
      )}
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button type="button" onClick={onCancel} disabled={busy} style={mcpBtnStyle(busy)}>
          cancel
        </button>
        <button type="submit" disabled={busy || !name.trim()} style={mcpBtnStyle(busy)}>
          {busy ? "saving…" : "save (dry-run + persist)"}
        </button>
      </div>
    </form>
  );
}

function McpFormRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label
      style={{
        display: "grid",
        gridTemplateColumns: "180px 1fr",
        alignItems: "start",
        gap: 8,
        fontSize: "var(--fs-xs)",
        color: "var(--ink-3)",
      }}
    >
      <span style={{ paddingTop: 4 }}>{label}</span>
      {children}
    </label>
  );
}

const mcpInputStyle: React.CSSProperties = {
  width: "100%",
  fontFamily: "var(--mono)",
  fontSize: 12,
  padding: "4px 6px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--line)",
  background: "var(--paper)",
  color: "var(--ink-1)",
  resize: "vertical",
};

function parseKvLines(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const idx = line.indexOf("=");
    if (idx <= 0) continue;
    out[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
  }
  return out;
}

function describeTool(name: string): string {
  const map: Record<string, string> = {
    fs_read: "Read a file from the workspace",
    fs_write: "Create or overwrite a file",
    fs_edit: "Search-and-replace a unique string",
    fs_list: "List entries in a directory",
    fs_glob: "Find files by glob pattern",
    fs_stat: "Inspect file metadata",
    fs_promote: "Move a draft from scratch into files/",
    shell_run: "Run a shell command (allow-listed)",
    python_exec_run: "Execute Python in a sandboxed venv",
    http_fetch: "Fetch a URL",
    search_web: "Search the web",
    email_draft: "Draft an email",
    email_send: "Send an email (gated)",
    load_skill: "Load a skill pack into the session",
  };
  return map[name] ?? "tool";
}

function SecApprovals({ client, sessionId }: { client: CoworkClient; sessionId: string | null }) {
  const [mode, setMode] = useState<PolicyMode>("work");
  const [pyExec, setPyExec] = useState<PythonExecPolicy>("confirm");

  useEffect(() => {
    if (sessionId) {
      client.getSessionPolicyMode(sessionId).then(setMode).catch(() => {});
      client.getSessionPythonExec(sessionId).then(setPyExec).catch(() => {});
    } else {
      client.getPolicyMode().then(setMode).catch(() => {});
    }
  }, [client, sessionId]);

  const setModeIfActive = async (next: PolicyMode) => {
    if (!sessionId) return;
    const previous = mode;
    setMode(next);
    try {
      const confirmed = await client.setSessionPolicyMode(sessionId, next);
      setMode(confirmed);
    } catch {
      setMode(previous);
    }
  };
  const setPyIfActive = async (next: PythonExecPolicy) => {
    if (!sessionId) return;
    const previous = pyExec;
    setPyExec(next);
    try {
      const confirmed = await client.setSessionPythonExec(sessionId, next);
      setPyExec(confirmed);
    } catch {
      setPyExec(previous);
    }
  };

  return (
    <div className="sec">
      <h3>Approvals policy</h3>
      <div className="desc">
        Per-session knobs. ``Plan`` blocks all writes; ``Work`` runs
        non-destructive tools but asks for confirmation on destructive ones;
        ``Auto`` skips confirmation prompts.
      </div>
      <Field label="Policy mode" sub="Applies to the active session.">
        <Chips
          value={mode}
          onChange={(v) => setModeIfActive(v as PolicyMode)}
          options={["plan", "work", "auto"]}
          disabled={!sessionId}
        />
      </Field>
      <Field
        label={<span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-sm)" }}>python_exec_run</span>}
        sub="Default-gated. Approve once, the next call is allowed; permission expires after one use."
      >
        <Chips
          value={pyExec}
          onChange={(v) => setPyIfActive(v as PythonExecPolicy)}
          options={["confirm", "allow", "deny"]}
          disabled={!sessionId}
        />
      </Field>
      {!sessionId && (
        <div style={{ fontSize: "var(--fs-xs)", color: "var(--ink-4)", marginTop: 8 }}>
          Open a session to change these.
        </div>
      )}
    </div>
  );
}

/* ───────────────────── System ───────────────────── */

function SecSystem({ client }: { client: CoworkClient }) {
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Slice T2 — sticky banner on saving. Cleared by Dismiss.
  const [restartBanner, setRestartBanner] = useState(false);
  // Slice U1 — per-key source map (db | toml) from
  // /v1/config/effective. Drives the (db) / (toml) badges next to
  // each editable field so operators see which values came from DB
  // overrides vs cowork.toml defaults.
  const [effectiveSource, setEffectiveSource] = useState<
    Record<string, string>
  >({});

  const refreshHealth = () => {
    client
      .health()
      .then(setHealth)
      .catch((e) => setError(String(e)));
  };

  const refreshEffective = () => {
    client
      .getEffectiveConfig()
      .then((eff) => setEffectiveSource(eff.source ?? {}))
      .catch(() => setEffectiveSource({}));
  };

  useEffect(() => {
    refreshHealth();
    refreshEffective();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  // Slice U1 — gate flips to !is_operator. SU mode reports
  // is_operator=true unconditionally (the local user is the
  // operator). MU mode reports per-caller. The notice text branches
  // on operator_configured to distinguish "no operator set" from
  // "operator is someone else".
  const isMu = health?.is_multi_user === true;
  const hasConfigFile = health?.has_config_file === true;
  const isOperator = health?.is_operator === true;
  const operatorConfigured = health?.operator_configured === true;
  // env-only SU mode still blocks (no cowork.toml to write); R5
  // covers the rest via the operator gate.
  const editsBlocked = !isOperator || !hasConfigFile;
  const editsBlockedReason = !hasConfigFile && !isMu
    ? "server is in env-only mode (no cowork.toml on disk) — set COWORK_CONFIG_PATH and restart"
    : !isOperator && isMu
    ? operatorConfigured
      ? "operator-only — only the configured operator can edit shared settings"
      : "no operator configured — set [auth].operator in cowork.toml to a user label and restart"
    : "";

  return (
    <div className="sec">
      <h3>System</h3>
      <div className="desc">
        Runtime configuration discovered from the server. The TOML file
        lives at ``$COWORK_CONFIG_PATH``; in-memory backends are the default
        and Tier E will introduce Redis / Postgres adapters behind the same
        protocols.
      </div>
      {restartBanner && (
        <div
          style={{
            background: "var(--paper-2)",
            border: "1px solid var(--warn, #c80)",
            color: "var(--warn, #c80)",
            padding: "6px 10px",
            borderRadius: "var(--radius-sm)",
            fontSize: "var(--fs-xs)",
            marginBottom: 12,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 8,
          }}
        >
          <span>
            ⚠ Restart required — config edits take effect on next
            server restart.
          </span>
          <button
            type="button"
            onClick={() => setRestartBanner(false)}
            style={{
              background: "transparent",
              border: "none",
              color: "var(--warn, #c80)",
              cursor: "pointer",
              fontSize: "var(--fs-xs)",
              textDecoration: "underline",
            }}
          >
            Dismiss
          </button>
        </div>
      )}
      <SecConfigModel
        client={client}
        health={health}
        editsBlocked={editsBlocked}
        editsBlockedReason={editsBlockedReason}
        sourceMap={effectiveSource}
        onSaved={() => {
          setRestartBanner(true);
          refreshHealth();
          refreshEffective();
        }}
      />
      <SecConfigCompaction
        client={client}
        health={health}
        editsBlocked={editsBlocked}
        editsBlockedReason={editsBlockedReason}
        sourceMap={effectiveSource}
        onSaved={() => {
          setRestartBanner(true);
          refreshHealth();
          refreshEffective();
        }}
      />
      <Field label="Status">
        {error ? (
          <span style={{ color: "var(--danger)" }}>{error}</span>
        ) : (
          <span style={{ color: "var(--ok)" }}>● {health?.status ?? "unknown"}</span>
        )}
      </Field>
      <Field label="Tools loaded">
        <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-sm)" }}>
          {health?.tools?.length ?? "—"}
        </span>
      </Field>
      <Field label="Skills loaded">
        <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-sm)" }}>
          {health?.skills?.length ?? "—"}
        </span>
      </Field>
      <Field
        label="MCP servers"
        sub="Configured Model Context Protocol servers. ✓ healthy / ✗ failed; hover an error pill for the detail."
      >
        {(() => {
          const mcp = health?.mcp ?? [];
          if (mcp.length === 0) {
            return (
              <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-sm)", color: "var(--ink-4)" }}>
                none configured
              </span>
            );
          }
          const ok = mcp.filter((m) => m.status === "ok").length;
          const err = mcp.length - ok;
          return (
            <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
              <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-sm)", color: "var(--ok)" }}>
                ● {ok} ok
              </span>
              {err > 0 && (
                <span
                  style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-sm)", color: "var(--danger)" }}
                  title={mcp
                    .filter((m) => m.status === "error")
                    .map((m) => `${m.name}: ${m.last_error ?? "error"}`)
                    .join("\n")}
                >
                  ✗ {err} error
                </span>
              )}
            </span>
          );
        })()}
      </Field>
      <Field label="Backends">
        <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-sm)" }}>
          local in-memory (event bus · limiter · sessions)
        </span>
      </Field>
    </div>
  );
}

/* ───────── Settings → System sub-blocks (Slice T2) ───────── */

function SecConfigModel({
  client,
  health,
  editsBlocked,
  editsBlockedReason,
  sourceMap,
  onSaved,
}: {
  client: CoworkClient;
  health: HealthInfo | null;
  editsBlocked: boolean;
  editsBlockedReason: string;
  sourceMap: Record<string, string>;
  onSaved: () => void;
}) {
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [origBaseUrl, setOrigBaseUrl] = useState("");
  const [origModel, setOrigModel] = useState("");
  const [origApiKey, setOrigApiKey] = useState("");
  const [showSecret, setShowSecret] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Bootstrap from /v1/health.model — that's all we have for the
  // current model identifier. base_url + api_key aren't in health
  // (avoiding accidental leak); we read on first PUT-success echo
  // OR show empty until the user types. To populate them up-front
  // we'd need a GET /v1/config/model route; deferred.
  useEffect(() => {
    if (health?.model && !origModel) {
      setModel(health.model);
      setOrigModel(health.model);
    }
  }, [health?.model, origModel]);

  const apiKeyIsEnvRef = apiKey.startsWith("env:");
  const dirty =
    baseUrl !== origBaseUrl ||
    model !== origModel ||
    apiKey !== origApiKey;

  const onSave = async () => {
    if (!dirty || busy || editsBlocked) return;
    setBusy(true);
    setError(null);
    try {
      // Only send fields the user touched, so an empty input on a
      // pre-existing config field doesn't accidentally clobber the
      // server's stored value.
      const patch: ConfigModelPatch = {};
      if (baseUrl !== origBaseUrl) patch.base_url = baseUrl;
      if (model !== origModel) patch.model = model;
      if (apiKey !== origApiKey) patch.api_key = apiKey;
      const view = await client.updateConfigModel(patch);
      setBaseUrl(view.base_url);
      setModel(view.model);
      setApiKey(view.api_key);
      setOrigBaseUrl(view.base_url);
      setOrigModel(view.model);
      setOrigApiKey(view.api_key);
      onSaved();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const onReset = () => {
    setBaseUrl(origBaseUrl);
    setModel(origModel);
    setApiKey(origApiKey);
    setError(null);
  };

  return (
    <div style={{ marginTop: 16 }}>
      <h4 style={{ margin: "0 0 4px 0", fontSize: "var(--fs-md)" }}>
        Model endpoint
      </h4>
      <div className="desc">
        OpenAI-compatible HTTP API. ``base_url`` is the API root,
        ``model`` is the identifier sent on each request, ``api_key``
        is either a literal secret or an{" "}
        <code style={{ margin: "0 4px" }}>env:VAR</code> reference
        Cowork resolves at consumption time.
      </div>
      {editsBlocked && (
        <div
          style={{
            fontSize: "var(--fs-xs)",
            color: "var(--ink-3)",
            background: "var(--paper-2)",
            border: "1px solid var(--line)",
            borderRadius: "var(--radius-sm)",
            padding: "4px 8px",
            margin: "0 0 8px 0",
          }}
        >
          {editsBlockedReason}
        </div>
      )}
      <Field
        label={
          <span>
            base_url
            <SourceBadge value={sourceMap["model.base_url"]} />
          </span>
        }
      >
        <input
          type="text"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          disabled={editsBlocked || busy}
          placeholder={origBaseUrl || "http://localhost:18000/v1"}
          style={editorInputStyle}
        />
      </Field>
      <Field
        label={
          <span>
            model
            <SourceBadge value={sourceMap["model.model"]} />
          </span>
        }
      >
        <input
          type="text"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          disabled={editsBlocked || busy}
          placeholder="(unset)"
          style={editorInputStyle}
        />
      </Field>
      <Field
        label={
          <span>
            api_key
            <SourceBadge value={sourceMap["model.api_key"]} />
            {apiKeyIsEnvRef && (
              <span
                style={{
                  marginLeft: 6,
                  fontSize: 10,
                  fontFamily: "var(--mono)",
                  color: "var(--ink-3)",
                  border: "1px solid var(--line)",
                  borderRadius: 3,
                  padding: "1px 4px",
                }}
              >
                env-resolved
              </span>
            )}
          </span>
        }
        sub={
          apiKeyIsEnvRef
            ? "env: prefix — Cowork reads the actual secret from the named environment variable at runtime."
            : "Plaintext secret stored in cowork.toml. Prefer env:VAR for production."
        }
      >
        <span style={{ display: "inline-flex", gap: 6, width: "100%" }}>
          <input
            type={apiKeyIsEnvRef || showSecret ? "text" : "password"}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            disabled={editsBlocked || busy}
            placeholder={origApiKey || "env:OPENAI_API_KEY"}
            style={{ ...editorInputStyle, flex: 1 }}
          />
          {!apiKeyIsEnvRef && apiKey && (
            <button
              type="button"
              onClick={() => setShowSecret((v) => !v)}
              style={editorBtnStyle(false)}
              title={showSecret ? "Hide secret" : "Show secret"}
            >
              {showSecret ? "hide" : "show"}
            </button>
          )}
        </span>
      </Field>
      {error && (
        <div style={{ fontSize: "var(--fs-xs)", color: "var(--danger)" }}>
          {error}
        </div>
      )}
      {!editsBlocked && (
        <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
          <button
            type="button"
            onClick={() => void onSave()}
            disabled={!dirty || busy}
            style={editorBtnStyle(busy || !dirty)}
          >
            {busy ? "saving…" : "Save model"}
          </button>
          <button
            type="button"
            onClick={onReset}
            disabled={!dirty || busy}
            style={editorBtnStyle(!dirty)}
          >
            Reset
          </button>
        </div>
      )}
    </div>
  );
}

function SecConfigCompaction({
  client,
  health,
  editsBlocked,
  editsBlockedReason,
  sourceMap,
  onSaved,
}: {
  client: CoworkClient;
  health: HealthInfo | null;
  editsBlocked: boolean;
  editsBlockedReason: string;
  sourceMap: Record<string, string>;
  onSaved: () => void;
}) {
  const c = health?.compaction;
  const [enabled, setEnabled] = useState<boolean>(c?.enabled ?? true);
  const [interval, setInterval] = useState<number>(c?.compaction_interval ?? 6);
  const [overlap, setOverlap] = useState<number>(c?.overlap_size ?? 1);
  const [tokenThreshold, setTokenThreshold] = useState<number>(
    c?.token_threshold ?? 32000,
  );
  const [retention, setRetention] = useState<number>(
    c?.event_retention_size ?? 20,
  );
  const [orig, setOrig] = useState({
    enabled: c?.enabled ?? true,
    interval: c?.compaction_interval ?? 6,
    overlap: c?.overlap_size ?? 1,
    tokenThreshold: c?.token_threshold ?? 32000,
    retention: c?.event_retention_size ?? 20,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!c) return;
    setEnabled(c.enabled);
    setInterval(c.compaction_interval);
    setOverlap(c.overlap_size);
    setTokenThreshold(c.token_threshold);
    setRetention(c.event_retention_size);
    setOrig({
      enabled: c.enabled,
      interval: c.compaction_interval,
      overlap: c.overlap_size,
      tokenThreshold: c.token_threshold,
      retention: c.event_retention_size,
    });
  }, [
    c?.enabled,
    c?.compaction_interval,
    c?.overlap_size,
    c?.token_threshold,
    c?.event_retention_size,
  ]);

  const dirty =
    enabled !== orig.enabled ||
    interval !== orig.interval ||
    overlap !== orig.overlap ||
    tokenThreshold !== orig.tokenThreshold ||
    retention !== orig.retention;

  const onSave = async () => {
    if (!dirty || busy || editsBlocked) return;
    setBusy(true);
    setError(null);
    try {
      const patch: ConfigCompactionPatch = {};
      if (enabled !== orig.enabled) patch.enabled = enabled;
      if (interval !== orig.interval) patch.compaction_interval = interval;
      if (overlap !== orig.overlap) patch.overlap_size = overlap;
      if (tokenThreshold !== orig.tokenThreshold) patch.token_threshold = tokenThreshold;
      if (retention !== orig.retention) patch.event_retention_size = retention;
      await client.updateConfigCompaction(patch);
      setOrig({ enabled, interval, overlap, tokenThreshold, retention });
      onSaved();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const onReset = () => {
    setEnabled(orig.enabled);
    setInterval(orig.interval);
    setOverlap(orig.overlap);
    setTokenThreshold(orig.tokenThreshold);
    setRetention(orig.retention);
    setError(null);
  };

  return (
    <div style={{ marginTop: 24 }}>
      <h4 style={{ margin: "0 0 4px 0", fontSize: "var(--fs-md)" }}>
        Compaction
      </h4>
      <div className="desc">
        ADK's sliding-window + token-threshold summary of old
        invocations. Keeps long sessions within the model's context
        window. ``compaction_interval`` triggers every N turns;
        ``token_threshold`` triggers mid-turn when context grows
        past N tokens.
      </div>
      {editsBlocked && (
        <div
          style={{
            fontSize: "var(--fs-xs)",
            color: "var(--ink-3)",
            background: "var(--paper-2)",
            border: "1px solid var(--line)",
            borderRadius: "var(--radius-sm)",
            padding: "4px 8px",
            margin: "0 0 8px 0",
          }}
        >
          {editsBlockedReason}
        </div>
      )}
      <Field
        label={
          <span>
            enabled
            <SourceBadge value={sourceMap["compaction.enabled"]} />
          </span>
        }
      >
        <label style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            disabled={editsBlocked || busy}
          />
          <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-sm)" }}>
            {enabled ? "on" : "off"}
          </span>
        </label>
      </Field>
      <Field
        label={
          <span>
            compaction_interval
            <SourceBadge value={sourceMap["compaction.compaction_interval"]} />
          </span>
        }
        sub="Min 1."
      >
        <input
          type="number"
          value={interval}
          min={1}
          onChange={(e) => setInterval(Number(e.target.value) || 1)}
          disabled={editsBlocked || busy || !enabled}
          style={editorInputStyle}
        />
      </Field>
      <Field
        label={
          <span>
            overlap_size
            <SourceBadge value={sourceMap["compaction.overlap_size"]} />
          </span>
        }
        sub="Min 0."
      >
        <input
          type="number"
          value={overlap}
          min={0}
          onChange={(e) => setOverlap(Number(e.target.value) || 0)}
          disabled={editsBlocked || busy || !enabled}
          style={editorInputStyle}
        />
      </Field>
      <Field
        label={
          <span>
            token_threshold
            <SourceBadge value={sourceMap["compaction.token_threshold"]} />
          </span>
        }
        sub="Min 1."
      >
        <input
          type="number"
          value={tokenThreshold}
          min={1}
          onChange={(e) => setTokenThreshold(Number(e.target.value) || 1)}
          disabled={editsBlocked || busy || !enabled}
          style={editorInputStyle}
        />
      </Field>
      <Field
        label={
          <span>
            event_retention_size
            <SourceBadge value={sourceMap["compaction.event_retention_size"]} />
          </span>
        }
        sub="Min 0."
      >
        <input
          type="number"
          value={retention}
          min={0}
          onChange={(e) => setRetention(Number(e.target.value) || 0)}
          disabled={editsBlocked || busy || !enabled}
          style={editorInputStyle}
        />
      </Field>
      {error && (
        <div style={{ fontSize: "var(--fs-xs)", color: "var(--danger)" }}>
          {error}
        </div>
      )}
      {!editsBlocked && (
        <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
          <button
            type="button"
            onClick={() => void onSave()}
            disabled={!dirty || busy}
            style={editorBtnStyle(busy || !dirty)}
          >
            {busy ? "saving…" : "Save compaction"}
          </button>
          <button
            type="button"
            onClick={onReset}
            disabled={!dirty || busy}
            style={editorBtnStyle(!dirty)}
          >
            Reset
          </button>
        </div>
      )}
    </div>
  );
}

/* ───────── Settings → Memory tab (Slice T2) ───────── */

function SecMemory({
  client,
  sessionId,
}: {
  client: CoworkClient;
  sessionId: string | null;
}) {
  const [scope, setScope] = useState<"user" | "project">("project");
  const [pages, setPages] = useState<MemoryPageInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [content, setContent] = useState<string>("");

  const refresh = () => {
    setError(null);
    setExpanded(null);
    setContent("");
    if (scope === "project" && !sessionId) {
      setPages([]);
      setError("Open a session to browse project memory.");
      return;
    }
    client
      .listMemoryPages(scope, sessionId ?? undefined)
      .then((p) => setPages(p.pages))
      .catch((e) => setError(String(e)));
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, sessionId]);

  const onView = async (name: string) => {
    if (expanded === name) {
      setExpanded(null);
      setContent("");
      return;
    }
    try {
      const body = await client.readMemoryPage(scope, name, sessionId ?? undefined);
      setExpanded(name);
      setContent(body.content);
    } catch (e) {
      setError(String(e));
    }
  };

  const onDelete = async (name: string) => {
    if (!window.confirm(`Delete memory page "${name}"?`)) return;
    try {
      await client.deleteMemoryPage(scope, name, sessionId ?? undefined);
      if (expanded === name) {
        setExpanded(null);
        setContent("");
      }
      refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div className="sec">
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 12,
        }}
      >
        <h3 style={{ margin: 0, flex: 1 }}>Memory</h3>
        <button
          type="button"
          onClick={refresh}
          style={editorBtnStyle(false)}
          title="Refresh page list"
        >
          ↻ refresh
        </button>
      </div>
      <div className="desc">
        LLM-maintained markdown wiki — see{" "}
        <code style={{ margin: "0 4px" }}>docs/MEMORY.md</code>. Pages
        live under the scope's <code>memory/pages/</code> directory.
        ``user`` scope is cross-project; ``project`` scope is bound to
        the active session's project.
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", margin: "8px 0" }}>
        <Chips
          value={scope}
          onChange={(v) => setScope(v as "user" | "project")}
          options={["user", "project"]}
        />
      </div>
      {error && (
        <div
          style={{
            fontSize: "var(--fs-xs)",
            color: "var(--danger)",
            marginBottom: 8,
          }}
        >
          {error}
        </div>
      )}
      {pages === null ? (
        <div style={{ fontSize: "var(--fs-sm)", color: "var(--ink-3)" }}>
          Loading…
        </div>
      ) : pages.length === 0 ? (
        <div style={{ fontSize: "var(--fs-sm)", color: "var(--ink-3)" }}>
          No pages yet — the agent files into <code>pages/</code> as it
          ingests sources or you ask it to remember things.
        </div>
      ) : (
        pages.map((p) => (
          <div key={p.name} style={{ marginBottom: 6 }}>
            <Field
              label={
                <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-sm)" }}>
                  {p.name}
                </span>
              }
              sub={p.preview}
            >
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                <span
                  style={{
                    color: "var(--ink-4)",
                    fontSize: "var(--fs-xs)",
                    fontFamily: "var(--mono)",
                  }}
                >
                  {p.size} B
                </span>
                <button
                  type="button"
                  onClick={() => void onView(p.name)}
                  style={editorBtnStyle(false)}
                  title={expanded === p.name ? "Collapse" : "View content"}
                >
                  {expanded === p.name ? "hide" : "view"}
                </button>
                <button
                  type="button"
                  onClick={() => void onDelete(p.name)}
                  style={{
                    width: 20,
                    height: 20,
                    display: "grid",
                    placeItems: "center",
                    fontSize: 13,
                    color: "var(--ink-3)",
                    cursor: "pointer",
                    background: "transparent",
                    border: "none",
                  }}
                  title="Delete page"
                >
                  ×
                </button>
              </span>
            </Field>
            {expanded === p.name && (
              <pre
                style={{
                  fontFamily: "var(--mono)",
                  fontSize: 11,
                  background: "var(--paper-2)",
                  border: "1px solid var(--line)",
                  borderRadius: "var(--radius-sm)",
                  padding: 8,
                  maxHeight: 320,
                  overflow: "auto",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  color: "var(--ink-2)",
                  margin: "4px 0 12px 0",
                }}
              >
                {content}
              </pre>
            )}
          </div>
        ))
      )}
    </div>
  );
}

/* ───────────────────── Appearance ───────────────────── */

function SecAppearance() {
  const [prefs, update] = usePreferences();

  const setTheme = (next: ThemeMode) => {
    update({ theme: next });
    applyThemeMode(next);
    persistThemeMode(next);
  };

  return (
    <div className="sec">
      <h3>Appearance</h3>
      <div className="desc">
        Visual preferences. Stored in this browser only — not synced.
      </div>
      <Field label="Theme" sub="System follows your OS preference.">
        <Chips
          value={prefs.theme}
          options={["system", "light", "dark"]}
          onChange={(v) => setTheme(v as ThemeMode)}
        />
      </Field>
      <Field label="Accent hue" sub="Drives buttons, focus rings, the brand mark.">
        <input
          type="range"
          min={0}
          max={360}
          step={1}
          value={prefs.accentHue}
          onChange={(e) => update({ accentHue: Number(e.target.value) })}
          style={{ width: 200 }}
        />
        <span style={{ marginLeft: 10, fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-3)" }}>
          {prefs.accentHue}
        </span>
      </Field>
    </div>
  );
}

/* ───────────────────── Atoms ───────────────────── */

function Field({
  label,
  sub,
  children,
}: {
  label: React.ReactNode;
  sub?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="field">
      <div className="l">
        {label}
        {sub && <div className="sub">{sub}</div>}
      </div>
      <div className="r" style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        {children}
      </div>
    </div>
  );
}

function Chips({
  value,
  options,
  onChange,
  disabled,
}: {
  value: string;
  options: string[];
  onChange: (v: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="chips" style={{ opacity: disabled ? 0.55 : 1 }}>
      {options.map((o) => (
        <span
          key={o}
          className={`chip ${value === o ? "on" : ""}`}
          onClick={() => !disabled && onChange(o)}
          style={{ cursor: disabled ? "not-allowed" : "pointer" }}
        >
          {o}
        </span>
      ))}
    </div>
  );
}
