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
  /** Shown in the mobile bottom bar (max 4; the 5th slot is "Mais"). */
  mobilePrimary?: boolean;
};

export type NavSection = { label: string; items: NavItem[] };

export const NAV_SECTIONS: NavSection[] = [
  {
    label: "Visão geral",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard, available: true, mobilePrimary: true },
      { href: "/carteira", label: "Minha Carteira", icon: Wallet, available: true, mobilePrimary: true },
    ],
  },
  {
    label: "Mercado",
    items: [
      { href: "/mercado", label: "Mercado", icon: ChartLine, available: true, mobilePrimary: true },
      { href: "/analise", label: "Análise de Ativos", icon: ChartCandlestick, available: true },
      { href: "/oportunidades", label: "Oportunidades", icon: Radar, available: true, mobilePrimary: true },
    ],
  },
  {
    label: "Inteligência",
    items: [
      { href: "/voryn-ai", label: "Voryn AI", icon: Sparkles, available: true },
      { href: "/risco", label: "Risco", icon: ShieldHalf, available: true },
      { href: "/estrategias", label: "Estratégias", icon: FlaskConical, available: true },
    ],
  },
  {
    label: "Conta",
    items: [
      { href: "/alertas", label: "Alertas", icon: Bell, available: true },
      { href: "/configuracoes", label: "Configurações", icon: Settings, available: true },
    ],
  },
];

export const NAV_ITEMS = NAV_SECTIONS.flatMap((s) => s.items);

export function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}
