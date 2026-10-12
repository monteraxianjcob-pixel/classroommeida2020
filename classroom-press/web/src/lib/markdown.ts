// Tiny, safe markdown renderer for article bodies.
// Everything is HTML-escaped first, so classmates' text can never inject markup.
// Supports: paragraphs, # headings, - / 1. lists, > quotes, ---, **bold**, *italic*,
// `code`, and [links](https://…) (http, https, mailto or site-relative only).

const esc = (s: string): string =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

function inline(raw: string): string {
  let s = esc(raw);
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, text: string, url: string) =>
    /^(https?:\/\/|mailto:|\/)/i.test(url)
      ? `<a href="${url}" rel="noopener noreferrer">${text}</a>`
      : text);
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>');
  return s;
}

export function renderMarkdown(md: string, opts: { dateline?: string } = {}): string {
  const lines = md.replace(/\r\n?/g, '\n').split('\n');
  const out: string[] = [];
  let para: string[] = [];
  let list: { tag: 'ul' | 'ol'; items: string[] } | null = null;
  let quote: string[] = [];
  let datelineUsed = !opts.dateline;
  const dateline = opts.dateline ? `<span class="dateline">${esc(opts.dateline)}</span> ` : '';

  const flushPara = () => {
    if (!para.length) return;
    const prefix = datelineUsed ? '' : dateline;
    datelineUsed = true;
    out.push(`<p>${prefix}${inline(para.join(' '))}</p>`);
    para = [];
  };
  const flushList = () => {
    if (!list) return;
    out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join('')}</${list.tag}>`);
    list = null;
  };
  const flushQuote = () => {
    if (!quote.length) return;
    out.push(`<blockquote><p>${inline(quote.join(' '))}</p></blockquote>`);
    quote = [];
  };
  const flushAll = () => { flushPara(); flushList(); flushQuote(); };

  for (const line of lines) {
    const t = line.trim();
    let m: RegExpMatchArray | null;
    if (!t) { flushAll(); continue; }
    if ((m = t.match(/^(#{1,3})\s+(.*)$/))) {
      flushAll();
      const level = m[1].length + 1; // the article headline is the only h1
      out.push(`<h${level}>${inline(m[2])}</h${level}>`);
    } else if (/^(-{3,}|\*{3,})$/.test(t)) {
      flushAll(); out.push('<hr />');
    } else if ((m = t.match(/^[-*]\s+(.*)$/))) {
      flushPara(); flushQuote();
      if (!list || list.tag !== 'ul') { flushList(); list = { tag: 'ul', items: [] }; }
      list.items.push(m[1]);
    } else if ((m = t.match(/^\d+[.)]\s+(.*)$/))) {
      flushPara(); flushQuote();
      if (!list || list.tag !== 'ol') { flushList(); list = { tag: 'ol', items: [] }; }
      list.items.push(m[1]);
    } else if ((m = t.match(/^>\s?(.*)$/))) {
      flushPara(); flushList(); quote.push(m[1]);
    } else {
      flushList(); flushQuote(); para.push(t);
    }
  }
  flushAll();

  if (!datelineUsed) out.unshift(`<p>${dateline}</p>`);
  return out.join('\n');
}
