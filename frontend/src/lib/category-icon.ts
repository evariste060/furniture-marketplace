import { Archive, Armchair, Baby, BedDouble, Briefcase, LampDesk, Library, Sofa, Tag, TreePalm, Tv, UtensilsCrossed, type LucideIcon } from "lucide-react";

/** The nav icon for a category, picked from the words of its slug and name (categories have no
 * icon field; their image is a photo, too detailed at 16px). Earlier rules win, so "kids-beds" is
 * a kids' category, "office-chairs" an office one and "tv-stands" a TV unit; anything unmatched
 * gets the generic tag. The words are those of the furniture taxonomy (ADR-014 phase 6). */
const RULES: [RegExp, LucideIcon][] = [
  [/^(kids?|children|nursery|baby|abana)$/, Baby],
  [/^(outdoor|garden|patio|terrace|balcony|hanze)$/, TreePalm],
  [/^(office|offices|desks?|meeting|workspace|ibiro)$/, Briefcase],
  [/^(tvs?|television)$/, Tv],
  [/^(bedroom|beds?|mattress(es)?|bedside)$/, BedDouble],
  [/^(dining|kitchen|sideboards?|stools?)$/, UtensilsCrossed],
  [/^(sofas?|couch(es)?|living|lounge)$/, Sofa],
  [/^(armchairs?|chairs?|seating)$/, Armchair],
  [/^(shelves|shelf|shelving|bookcases?|books?)$/, Library],
  [/^(wardrobes?|dressers?|storage|cabinets?|drawers?)$/, Archive],
  [/^(lamps?|lighting)$/, LampDesk],
];

export function categoryIcon(category: { slug: string; name: string }): LucideIcon {
  const words = `${category.slug} ${category.name}`.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
  for (const [rule, icon] of RULES) {
    if (words.some((word) => rule.test(word))) return icon;
  }
  return Tag;
}
