import { NAV_SECTIONS, type NavSection } from "./nav-config";

/** Navigation for this session. Markets are tabs inside each area, so nothing depends on them here. */
export function useNavSections(): NavSection[] {
  return NAV_SECTIONS;
}
