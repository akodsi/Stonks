/** Shared markdown renderer for AI narrative text used across components. */

/** Parse inline markdown (bold, italic, code) into JSX spans. */
export function renderInline(text: string, keyPrefix: string): (string | JSX.Element)[] {
  const parts: (string | JSX.Element)[] = [];
  const regex = /(\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let idx = 0;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    if (match[2] !== undefined) {
      parts.push(
        <strong key={`${keyPrefix}-b${idx}`} className="text-white font-semibold">
          {match[2]}
        </strong>
      );
    } else if (match[3] !== undefined) {
      parts.push(
        <em key={`${keyPrefix}-i${idx}`} className="text-slate-200 italic">
          {match[3]}
        </em>
      );
    } else if (match[4] !== undefined) {
      parts.push(
        <code key={`${keyPrefix}-c${idx}`} className="bg-slate-800 px-1.5 py-0.5 rounded text-xs text-blue-300">
          {match[4]}
        </code>
      );
    }
    lastIndex = match.index + match[0].length;
    idx++;
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  return parts.length > 0 ? parts : [text];
}

export function renderNarrativeText(text: string): JSX.Element {
  const lines = text.split("\n");
  const elements: JSX.Element[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (/^---+$/.test(line.trim())) {
      elements.push(<hr key={i} className="border-slate-700 my-4" />);
      i++;
      continue;
    }

    if (line.startsWith("## ")) {
      elements.push(
        <h3 key={i} className="text-sm font-semibold text-slate-200 mt-5 mb-2">
          {renderInline(line.slice(3), `h2-${i}`)}
        </h3>
      );
      i++;
      continue;
    }

    if (line.startsWith("### ")) {
      elements.push(
        <h4 key={i} className="text-sm font-medium text-slate-300 mt-4 mb-1.5">
          {renderInline(line.slice(4), `h3-${i}`)}
        </h4>
      );
      i++;
      continue;
    }

    if (line.startsWith("- ")) {
      const listItems: JSX.Element[] = [];
      while (i < lines.length && lines[i].startsWith("- ")) {
        listItems.push(
          <li key={i} className="text-sm text-slate-300 mb-1">
            {renderInline(lines[i].slice(2), `ul-${i}`)}
          </li>
        );
        i++;
      }
      elements.push(
        <ul key={`ul-${i}`} className="list-disc ml-5 mb-3">
          {listItems}
        </ul>
      );
      continue;
    }

    const olMatch = line.match(/^(\d+)\.\s/);
    if (olMatch) {
      const listItems: JSX.Element[] = [];
      while (i < lines.length && /^\d+\.\s/.test(lines[i])) {
        const content = lines[i].replace(/^\d+\.\s/, "");
        listItems.push(
          <li key={i} className="text-sm text-slate-300 mb-1">
            {renderInline(content, `ol-${i}`)}
          </li>
        );
        i++;
      }
      elements.push(
        <ol key={`ol-${i}`} className="list-decimal ml-5 mb-3">
          {listItems}
        </ol>
      );
      continue;
    }

    if (line.trim() === "") {
      elements.push(<div key={i} className="h-2" />);
      i++;
      continue;
    }

    elements.push(
      <p key={i} className="text-sm text-slate-300 mb-2 leading-relaxed">
        {renderInline(line, `p-${i}`)}
      </p>
    );
    i++;
  }

  return <div>{elements}</div>;
}
