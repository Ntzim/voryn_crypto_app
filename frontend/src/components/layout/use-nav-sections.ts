import { useMarkets } from "@/lib/b3-queries";

import { NAV_SECTIONS, type NavSection } from "./nav-config";

/** Navigation for this session: entries of disabled markets are left out. */
export function useNavSections(): NavSection[] {
  const { data: markets } = useMarkets();
  return NAV_SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter((item) => !item.market || markets?.some((m) => m.market === item.market)),
  }));
}
