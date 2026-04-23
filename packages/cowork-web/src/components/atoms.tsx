/**
 * Shared atoms for the warm-editorial UI.
 *
 * Wraps `lucide-react` with a name-keyed ``Icon`` and supplies the
 * agent-identity primitives (``Mono``, ``AgentStack``) — Cowork's four
 * specialist agents map to fixed hues: researcher=Ada (260),
 * writer=Orson (30), analyst=Iris (160), reviewer=Kit (310). Anything
 * else (root, unknown) falls back to neutral ink.
 */

import {
  Bell,
  Bolt,
  Brain,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Circle,
  Code2,
  Eye,
  File as FileIco,
  FileText,
  FileCode,
  Folder,
  Globe,
  Image as ImageIco,
  Key,
  LayoutGrid,
  List as ListIco,
  MoreHorizontal,
  PanelLeft,
  Plus,
  Puzzle,
  RefreshCw,
  Search,
  Settings as SettingsIco,
  Shield,
  Table2,
  Terminal,
  TreePine,
  User,
  Wand2,
  X,
  Zap,
  type LucideIcon,
} from "lucide-react";

/* ───────────────────────────── Icons ───────────────────────────── */

const ICON_MAP: Record<string, LucideIcon> = {
  search: Search,
  plus: Plus,
  chevR: ChevronRight,
  chevD: ChevronDown,
  chevL: ChevronLeft,
  close: X,
  more: MoreHorizontal,
  refresh: RefreshCw,
  bell: Bell,
  settings: SettingsIco,
  globe: Globe,
  folderOpen: Folder,
  folder: Folder,
  doc: FileText,
  code: FileCode,
  source: Code2,
  eye: Eye,
  terminal: Terminal,
  zap: Zap,
  table: Table2,
  image: ImageIco,
  chart: Table2,
  grid: LayoutGrid,
  list: ListIco,
  tree: TreePine,
  panelLeft: PanelLeft,
  user: User,
  bolt: Bolt,
  brain: Brain,
  wand: Wand2,
  shield: Shield,
  key: Key,
  puzzle: Puzzle,
  dot: Circle,
};

interface IconProps {
  name: keyof typeof ICON_MAP | string;
  size?: number;
  className?: string;
}

export function Icon({ name, size = 14, className }: IconProps) {
  const Cmp = ICON_MAP[name] ?? FileIco;
  return <Cmp size={size} strokeWidth={1.75} className={className} />;
}

/* ──────────────────────────── Agents ───────────────────────────── */

/**
 * Map cowork's descriptive sub-agent names to the visual agent identities
 * from the design. Also accepts the design's own ids for symmetry.
 */
const AGENT_STYLE: Record<string, { letter: string; color: string; soft: string }> = {
  researcher: { letter: "R", color: "var(--ada)", soft: "var(--ada-soft)" },
  ada:        { letter: "A", color: "var(--ada)", soft: "var(--ada-soft)" },
  writer:     { letter: "W", color: "var(--orson)", soft: "var(--orson-soft)" },
  orson:      { letter: "O", color: "var(--orson)", soft: "var(--orson-soft)" },
  analyst:    { letter: "A", color: "var(--iris)", soft: "var(--iris-soft)" },
  iris:       { letter: "I", color: "var(--iris)", soft: "var(--iris-soft)" },
  reviewer:   { letter: "R", color: "var(--kit)", soft: "var(--kit-soft)" },
  kit:        { letter: "K", color: "var(--kit)", soft: "var(--kit-soft)" },
};

const NEUTRAL = { letter: "·", color: "var(--ink-3)", soft: "var(--paper-3)" };

export function agentStyle(name: string | undefined | null) {
  if (!name) return NEUTRAL;
  return AGENT_STYLE[name.toLowerCase()] ?? NEUTRAL;
}

/** Circular monogram for a single agent — currently used only by
 *  ``AgentStack`` below. Kept in-file (not exported) since no other
 *  component reaches for it directly. */
function Mono({
  agent,
  size = 22,
}: {
  agent: string | undefined | null;
  size?: number;
}) {
  const s = agentStyle(agent);
  return (
    <span
      className="av"
      title={agent ?? ""}
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        background: s.color,
        color: "white",
        display: "grid",
        placeItems: "center",
        fontFamily: "var(--serif)",
        fontSize: Math.max(9, Math.round(size * 0.5)),
        fontWeight: 500,
        flexShrink: 0,
      }}
    >
      {s.letter}
    </span>
  );
}

/** Overlapping monograms (right-to-left). */
export function AgentStack({
  agents,
  size = 14,
}: {
  agents: string[];
  size?: number;
}) {
  if (!agents.length) return null;
  return (
    <span style={{ display: "inline-flex" }}>
      {agents.map((a, i) => (
        <span
          key={`${a}-${i}`}
          style={{
            marginLeft: i === 0 ? 0 : -Math.round(size * 0.3),
            borderRadius: "50%",
            border: "1.5px solid var(--paper-2)",
            display: "inline-flex",
          }}
        >
          <Mono agent={a} size={size} />
        </span>
      ))}
    </span>
  );
}

/* ───────────────────── File-kind icons ──────────────────────── */

const FILE_KIND_ICON: Record<string, keyof typeof ICON_MAP> = {
  md: "doc",
  html: "code",
  code: "code",
  table: "table",
  image: "image",
  pdf: "doc",
  dir: "folder",
  file: "doc",
};

export function FileIcon({ kind, size = 13 }: { kind: string; size?: number }) {
  return <Icon name={FILE_KIND_ICON[kind] ?? "doc"} size={size} />;
}
