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

import { useEffect, useState } from "react";
import type { CoworkClient } from "../transport/client";
import type { HealthInfo, PolicyMode, PythonExecPolicy } from "../transport/types";
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
            {tab === "profile" && <SecProfile userId={userId} />}
            {tab === "workspace" && <SecWorkspace />}
            {tab === "agents" && (
              <>
                <SecAgents
                  client={client}
                  sessionId={sessionId}
                  surface={surface}
                />
                <SecTools client={client} surface={surface} />
              </>
            )}
            {tab === "approvals" && <SecApprovals client={client} sessionId={sessionId} />}
            {tab === "system" && <SecSystem client={client} />}
            {tab === "appearance" && <SecAppearance />}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ───────────────────── Account ───────────────────── */

function SecProfile({ userId }: { userId?: string }) {
  return (
    <div className="sec">
      <h3>Profile</h3>
      <div className="desc">
        Identity is taken from the API token you authenticated with.
      </div>
      <Field label="User id">
        <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-sm)" }}>{userId ?? "local"}</span>
      </Field>
    </div>
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
  surface,
}: {
  client: CoworkClient;
  surface?: "managed" | "local";
}) {
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    client
      .health()
      .then(setHealth)
      .catch((e) => setError(String(e)));
  }, [client]);

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
      <h3 style={{ marginTop: 24 }}>Skills</h3>
      <div className="desc">Skill packs the server discovered at startup.</div>
      {(health?.skills ?? []).length === 0 ? (
        <div style={{ fontSize: "var(--fs-sm)", color: "var(--ink-3)" }}>No skills installed.</div>
      ) : (
        (health?.skills ?? []).map((s) => (
          <Field key={s} label={<span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-sm)" }}>{s}</span>}>
            <span style={{ color: "var(--ok)", fontSize: "var(--fs-xs)" }}>● installed</span>
          </Field>
        ))
      )}
    </div>
  );
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

  useEffect(() => {
    client
      .health()
      .then(setHealth)
      .catch((e) => setError(String(e)));
  }, [client]);

  return (
    <div className="sec">
      <h3>System</h3>
      <div className="desc">
        Runtime configuration discovered from the server. The TOML file
        lives at ``$COWORK_CONFIG_PATH``; in-memory backends are the default
        and Tier E will introduce Redis / Postgres adapters behind the same
        protocols.
      </div>
      <Field label="Status">
        {error ? (
          <span style={{ color: "var(--danger)" }}>{error}</span>
        ) : (
          <span style={{ color: "var(--ok)" }}>● {health?.status ?? "unknown"}</span>
        )}
      </Field>
      <Field label="Model" sub="Active LLM identifier from cowork.toml.">
        <span
          style={{
            fontFamily: "var(--mono)",
            fontSize: "var(--fs-sm)",
            color: "var(--ink-2)",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
          title={health?.model ?? ""}
        >
          {health?.model ?? "—"}
        </span>
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
      <Field label="Backends">
        <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-sm)" }}>
          local in-memory (event bus · limiter · sessions)
        </span>
      </Field>
      <Field
        label="Compaction"
        sub="ADK's sliding-window + token-threshold summary of old invocations. Keeps long sessions within the model's context window."
      >
        {health?.compaction ? (
          <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-sm)" }}>
            {health.compaction.enabled
              ? `every ${health.compaction.compaction_interval} turns · overlap ${health.compaction.overlap_size} · >${health.compaction.token_threshold} tokens · keep last ${health.compaction.event_retention_size}`
              : "disabled"}
          </span>
        ) : (
          <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-sm)", color: "var(--ink-4)" }}>
            —
          </span>
        )}
      </Field>
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
