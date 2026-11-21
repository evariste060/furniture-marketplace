import {
  Cable,
  Camera,
  Gamepad2,
  HardDrive,
  Headphones,
  Laptop,
  Printer,
  Refrigerator,
  Router,
  Smartphone,
  Tablet,
  Tag,
  Tv,
  Watch,
  type LucideIcon,
} from "lucide-react";

/** The nav icon for a category, picked from the words of its slug and name (categories have no
 * icon field; their image is a photo, too detailed at 16px). Earlier rules win, so "tvs-audio" is
 * a TV and "phone-accessories" a phone; anything unmatched gets the generic tag. */
const RULES: [RegExp, LucideIcon][] = [
  [/^(tvs?|televisions?|audio|speakers?|sound|home-?theat(er|re))$/, Tv],
  [/^(phones?|smartphones?|mobiles?|telefoni)$/, Smartphone],
  [/^(tablets?|ipads?)$/, Tablet],
  [/^(laptops?|computers?|notebooks?|pcs?|desktops?|mudasobwa)$/, Laptop],
  [/^(headphones?|earphones?|earbuds?|headsets?)$/, Headphones],
  [/^(appliances?|fridges?|refrigerators?|kitchen|freezers?)$/, Refrigerator],
  [/^(watch(es)?|wearables?|smartwatch(es)?)$/, Watch],
  [/^(cameras?|photography|photo)$/, Camera],
  [/^(gaming|games?|consoles?)$/, Gamepad2],
  [/^(network(ing)?|routers?|wi-?fi)$/, Router],
  [/^(printers?|printing|scanners?)$/, Printer],
  [/^(storage|drives?|memory|ssds?)$/, HardDrive],
  [/^(accessor(y|ies)|cables?|chargers?|power)$/, Cable],
];

export function categoryIcon(category: { slug: string; name: string }): LucideIcon {
  const words = `${category.slug} ${category.name}`.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
  for (const [rule, icon] of RULES) {
    if (words.some((word) => rule.test(word))) return icon;
  }
  return Tag;
}
