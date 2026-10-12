// Reads the JSON the generator committed. Build-time only (Node): no model, no network.
import fs from 'node:fs';
import path from 'node:path';

export type Urgency = 'breaking' | 'banner' | 'front' | 'archive';
export type Category = 'exam' | 'deadline' | 'event' | 'academics' | 'sports' | 'general';

export interface Article {
  slug: string;
  title: string;
  headline: string | null;
  subhead: string | null;
  category: Category;
  subject: string | null;
  date: string | null;
  author: string | null;
  location: string | null;
  body: string;
  photo: string | null;
  photo_caption: string | null;
  photo_credit: string | null;
  urgency: Urgency;
  pinned: boolean;
  issue_number: number | null;
  due_at: string | null;
  scope: string | null;
  requirement: string | null;
  restriction: string | null;
}

export interface Section { slug: Category; label: string; description: string; count: number; slugs: string[] }
export interface EditionEntry { number: number; date: string }
export interface Data {
  edition: number;
  volume: number;
  generatedAt: string;
  articles: Article[];
  sections: Section[];
  editions: EditionEntry[];
}

export const SITE = {
  name: 'Classroom Press',
  className: 'Class 10B', // change this to your class
};

export const CATEGORY_LABELS: Record<string, string> = {
  exam: 'Exams', deadline: 'Deadlines', event: 'Events',
  academics: 'Academics', sports: 'Sports', general: 'General',
};

const DATA_DIR = path.resolve(process.cwd(), 'public', 'data');

function readJson<T>(name: string, fallback: T): T {
  try {
    return JSON.parse(fs.readFileSync(path.join(DATA_DIR, name), 'utf-8')) as T;
  } catch {
    return fallback;
  }
}

export function loadData(): Data {
  const a = readJson<{ edition?: number; generated_at?: string; articles?: Article[] }>('articles.json', {});
  const e = readJson<{ volume?: number; current?: number; editions?: EditionEntry[] }>('editions.json', {});
  const sections = readJson<Section[]>('sections.json', []);
  return {
    edition: a.edition ?? e.current ?? 1,
    volume: e.volume ?? 1,
    generatedAt: a.generated_at ?? new Date().toISOString(),
    articles: a.articles ?? [],
    sections,
    editions: e.editions ?? [],
  };
}

// ── helpers ────────────────────────────────────────────────────────────────
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export const displayHeadline = (a: Article): string => a.headline ?? a.title;
export const categoryLabel = (c: string): string => CATEGORY_LABELS[c] ?? 'General';

/** '2026-10-20' -> 'Oct 20' (no timezone maths: the string is a calendar date). */
export function formatShortDate(iso: string | null): string {
  if (!iso) return '';
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  if (!y || !m || !d) return '';
  return `${MONTHS[m - 1]} ${d}`;
}

/** Local calendar date at generation time, e.g. 'Monday, October 12, 2026'. */
export function formatLongDate(iso: string): string {
  const day = iso.slice(0, 10);
  const d = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString('en-US', {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC',
  });
}

export const dueMs = (a: Article): number => (a.due_at ? Date.parse(a.due_at) : Number.POSITIVE_INFINITY);

/** Same wording as the client-side updater in Base.astro. */
export function countdownLabel(ms: number): string {
  if (ms <= 0) return 'due now';
  const mins = Math.floor(ms / 60000);
  const days = Math.floor(mins / 1440);
  const hours = Math.floor((mins % 1440) / 60);
  if (days > 0) return `${days}d ${hours}h left`;
  if (hours > 0) return `${hours}h ${mins % 60}m left`;
  return `${Math.max(mins, 1)}m left`;
}

export function plainExcerpt(markdown: string, words = 55): string {
  const text = markdown
    .replace(/[#>*_`]/g, '')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/^\s*[-\d.]+\s+/gm, '')
    .replace(/\s+/g, ' ')
    .trim();
  const parts = text.split(' ');
  return parts.length > words ? parts.slice(0, words).join(' ') + '…' : text;
}

const RANK: Record<Urgency, number> = { breaking: 0, banner: 1, front: 2, archive: 3 };

function compareFront(x: Article, y: Article): number {
  if (RANK[x.urgency] !== RANK[y.urgency]) return RANK[x.urgency] - RANK[y.urgency];
  if (x.pinned !== y.pinned) return x.pinned ? -1 : 1;
  const dx = dueMs(x), dy = dueMs(y);
  if (dx === dy) return x.slug.localeCompare(y.slug);
  return dx < dy ? -1 : 1; // soonest first
}

export interface FrontPage {
  lead: Article | null;
  banners: Article[];
  secondary: Article[];
  ticker: Article[];
  deadlines: Article[];
}

/** Urgency drives placement; the generator already computed it at ingest time. */
export function frontPage(articles: Article[], nowMs: number): FrontPage {
  const ranked = articles.filter((a) => a.urgency !== 'archive').sort(compareFront);
  const lead = ranked[0] ?? null;
  return {
    lead,
    banners: ranked.filter((a) => a !== lead && a.urgency === 'banner'),
    secondary: ranked.filter((a) => a !== lead && a.urgency !== 'banner'),
    ticker: ranked.filter((a) => a.urgency === 'breaking'),
    deadlines: articles
      .filter((a) => a.due_at && dueMs(a) > nowMs && ['exam', 'deadline', 'event'].includes(a.category))
      .sort((x, y) => dueMs(x) - dueMs(y))
      .slice(0, 5),
  };
}

/** Section page order: upcoming (soonest first), then past (newest first). */
export function sectionOrder(articles: Article[], nowMs: number): Article[] {
  const upcoming = articles.filter((a) => dueMs(a) > nowMs && a.due_at).sort((x, y) => dueMs(x) - dueMs(y));
  const rest = articles
    .filter((a) => !upcoming.includes(a))
    .sort((x, y) => (y.date ?? '').localeCompare(x.date ?? ''));
  return [...upcoming, ...rest];
}
