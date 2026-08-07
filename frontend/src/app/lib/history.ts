import type { DecideResult } from './api';

export interface HistoryEntry {
  id: string;
  query: string;
  timestamp: number;
  result: DecideResult;
}

const STORAGE_KEY = 'etiquette-search-history';
const MAX_ENTRIES = 50;

export function loadHistory(): HistoryEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as HistoryEntry[]) : [];
  } catch {
    return [];
  }
}

function persist(entries: HistoryEntry[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
}

export function saveHistoryEntry(query: string, result: DecideResult): HistoryEntry[] {
  const entry: HistoryEntry = { id: crypto.randomUUID(), query, timestamp: Date.now(), result };
  const next = [entry, ...loadHistory()].slice(0, MAX_ENTRIES);
  persist(next);
  return next;
}

export function deleteHistoryEntry(id: string): HistoryEntry[] {
  const next = loadHistory().filter((h) => h.id !== id);
  persist(next);
  return next;
}

export function clearHistory(): HistoryEntry[] {
  localStorage.removeItem(STORAGE_KEY);
  return [];
}
