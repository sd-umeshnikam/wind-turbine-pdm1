import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// react-markdown renders no raw HTML, so model cards and assistant answers cannot inject markup.
export function Markdown({ children }: { children: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  );
}
