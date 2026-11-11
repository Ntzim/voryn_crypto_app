import {
  Bell,
  ChartCandlestick,
  ChartLine,
  FlaskConical,
  LayoutDashboard,
  Radar,
  Settings,
  ShieldHalf,
  Sparkles,
  Wallet,
  type LucideIcon,
} from "lucide-react";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  /** False while the module is still on the roadmap: the page shows an honest "em breve" state. */
  available: boolean;
  /** Position in the mobile bottom bar (five slots); absent = only in the menu. */
  mobileOrder?: number;
  /** Bottom-bar label: one fifth of a 320px screen fits about 10 characters. */
  short?: string;
  /** Other routes that belong to this entry (one entry per area: crypto and B3 are tabs inside). */
  also?: string[];
};

export type NavSection = { label: string; items: NavItem[]; footer?: boolean };

export const NAV_SECTIONS: NavSection[] = [
  {
    label: "Visão geral",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard, available: true, mobileOrder: 1, short: "Início" },
      { href: "/carteira", label: "Minha carteira", icon: Wallet, available: true, mobileOrder: 4, short: "Carteira" },
    ],
  },
  {
    label: "Mercado",
    items: [
      { href: "/mercado", label: "Mercado", icon: ChartLine, available: true, mobileOrder: 2, also: ["/b3"] },
      { href: "/oportunidades", label: "Oportunidades", icon: Radar, available: true, mobileOrder: 3, short: "Sinais", also: ["/oportunidades-b3"] },
      { href: "/analise", label: "Análise de ativos", icon: ChartCandlestick, available: true },
    ],
  },
  {
    label: "Inteligência",
    items: [
      { href: "/voryn-ai", label: "Voryn AI", icon: Sparkles, available: true, mobileOrder: 5 },
      { href: "/risco", label: "Risco", icon: ShieldHalf, available: true },
      { href: "/estrategias", label: "Estratégias", icon: FlaskConical, available: true },
    ],
  },
  {
    label: "Conta",
    footer: true,
    items: [
      { href: "/alertas", label: "Alertas", icon: Bell, available: true },
      { href: "/configuracoes", label: "Configurações", icon: Settings, available: true },
    ],
  },
];

export const NAV_ITEMS = NAV_SECTIONS.flatMap((s) => s.items);

export const MOBILE_ITEMS = NAV_ITEMS.filter((item) => item.mobileOrder !== undefined).sort(
  (a, b) => (a.mobileOrder ?? 0) - (b.mobileOrder ?? 0),
);

function matches(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function isActive(pathname: string, item: NavItem): boolean {
  return matches(pathname, item.href) || (item.also ?? []).some((href) => matches(pathname, href));
}
