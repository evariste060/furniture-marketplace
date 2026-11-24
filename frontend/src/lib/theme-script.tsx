/** Light or dark mode (SC-07): the key the choice is saved under in this browser, and the script
 * that applies a saved dark choice to <html> before the first paint, so pages never flash. Used
 * by every root layout (storefront, admin, seller); useTheme in theme.ts changes it. */
export const THEME_KEY = "furnihub-theme";

const THEME_SCRIPT = `try{if(localStorage.getItem("${THEME_KEY}")==="dark")document.documentElement.dataset.theme="dark"}catch(e){}`;

export function ThemeScript() {
  return <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />;
}
