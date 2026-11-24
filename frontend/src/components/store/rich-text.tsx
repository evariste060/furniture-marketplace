import { Check, Info } from "lucide-react";
import type { ReactNode } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Table, Td, Th } from "@/components/ui/table";
import { Link } from "@/i18n/navigation";

/** Policy page text (module 19): Markdown written by staff, drawn in Policy.dc.html's styles.
 * Raw HTML and images are never rendered; links are underlined (they sit in running text) and keep only safe addresses (react-markdown's
 * default check: http, https, mailto, tel and relative paths). Headings start at h2, since the
 * page title is the h1. The first paragraph is the larger lead text; a quote is the light-blue
 * info box; bullet lists use the green check marks, numbered lists their numbers. */
export function RichText({ markdown }: { markdown: string }) {
  const components: Components = {
    h1: ({ children }) => <h2 className="t-h3">{children}</h2>,
    h2: ({ children }) => <h2 className="t-h3">{children}</h2>,
    h3: ({ children }) => <h3 className="t-h4">{children}</h3>,
    h4: ({ children }) => <h3 className="t-h4">{children}</h3>,
    h5: ({ children }) => <h3 className="t-h4">{children}</h3>,
    h6: ({ children }) => <h3 className="t-h4">{children}</h3>,
    p: ({ children }) => <p className="text-tx2">{children}</p>,
    ul: ({ children }) => <ul className="m-0 flex list-none flex-col gap-2.5 p-0">{children}</ul>,
    li: ({ children }) => <ListItem>{children}</ListItem>,
    // Numbered lists keep their numbers: the items go back to list items without the check mark.
    ol: ({ children }) => (
      <ol className="m-0 flex list-decimal flex-col gap-2.5 pl-5 text-tx2 marker:text-tx2 [&>li]:list-item [&>li>svg]:hidden">{children}</ol>
    ),
    blockquote: ({ children }) => (
      <div className="flex items-start gap-3 rounded-xl bg-light p-4 text-sm text-tx2 [&_p]:text-sm [&_p]:text-tx2">
        <Info size={20} aria-hidden="true" className="mt-0.5 flex-none text-pri-fg" />
        <div className="flex flex-col gap-2">{children}</div>
      </div>
    ),
    table: ({ children }) => (
      <div className="overflow-hidden rounded-xl border border-bd">
        <Table>{children}</Table>
      </div>
    ),
    th: ({ children }) => <Th>{children}</Th>,
    td: ({ children }) => <Td>{children}</Td>,
    a: ({ href, children }) => {
      if (!href) return <>{children}</>;
      if (href.startsWith("/") && !href.startsWith("//")) return (
          <Link href={href} className="underline">
            {children}
          </Link>
        );
      const external = /^https?:\/\//i.test(href);
      return (
        <a href={href} className="underline" {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}>
          {children}
        </a>
      );
    },
    hr: () => <hr className="hr" />,
  };
  return (
    <div className="flex flex-col gap-5 [&>p:first-of-type]:text-lg">
      <Markdown remarkPlugins={[remarkGfm]} skipHtml disallowedElements={["img"]} unwrapDisallowed={false} components={components}>
        {markdown}
      </Markdown>
    </div>
  );
}

function ListItem({ children }: { children: ReactNode }) {
  return (
    <li className="flex items-start gap-2.5">
      <Check size={16} aria-hidden="true" className="mt-[5px] flex-none text-ok" />
      <span className="text-tx2">{children}</span>
    </li>
  );
}
