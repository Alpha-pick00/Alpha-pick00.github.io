import React, { createContext, useContext, useState } from 'react';
import { decide, extractOcr, ApiError, type DecideResult } from '../lib/api';
import {
  deleteHistoryEntry,
  clearHistory,
  loadHistory,
  saveHistoryEntry,
  type HistoryEntry,
} from '../lib/history';

export type SearchStatus = 'idle' | 'ocr' | 'loading' | 'result' | 'error';

interface SearchContextValue {
  query: string;
  setQuery: (q: string) => void;
  status: SearchStatus;
  result: DecideResult | null;
  errorMessage: string;
  history: HistoryEntry[];
  runSearch: (q: string, brand?: string) => Promise<void>;
  handleImageUpload: (file: File) => Promise<void>;
  handleReset: () => void;
  loadFromHistory: (entry: HistoryEntry) => void;
  deleteFromHistory: (id: string) => void;
  clearAllHistory: () => void;
}

const SearchContext = createContext<SearchContextValue | null>(null);

export const SearchProvider = ({ children }: { children: React.ReactNode }) => {
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState<SearchStatus>('idle');
  const [result, setResult] = useState<DecideResult | null>(null);
  const [errorMessage, setErrorMessage] = useState('');
  const [history, setHistory] = useState<HistoryEntry[]>(() => loadHistory());

  const runSearch = async (q: string, brand?: string) => {
    if (!q.trim()) return;
    setStatus('loading');
    setErrorMessage('');
    try {
      const data = await decide(q, brand);
      setResult(data);
      setStatus('result');
      setHistory(saveHistoryEntry(q, data));
    } catch (err) {
      setErrorMessage(
        err instanceof ApiError ? err.message : '요청 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.'
      );
      setStatus('error');
    }
  };

  const handleImageUpload = async (file: File) => {
    setStatus('ocr');
    setErrorMessage('');
    try {
      const { ocr, cleaned } = await extractOcr(file);
      const extractedText = (cleaned?.search_query || cleaned?.cleaned_text || ocr.text || '').trim();
      if (!extractedText) {
        setErrorMessage(ocr.error || '이미지에서 텍스트를 찾지 못했습니다.');
        setStatus('error');
        return;
      }
      setQuery(extractedText);
      await runSearch(extractedText);
    } catch (err) {
      setErrorMessage(
        err instanceof ApiError ? err.message : '이미지 분석 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.'
      );
      setStatus('error');
    }
  };

  const handleReset = () => {
    setStatus('idle');
    setResult(null);
    setErrorMessage('');
  };

  const loadFromHistory = (entry: HistoryEntry) => {
    setQuery(entry.query);
    setResult(entry.result);
    setErrorMessage('');
    setStatus('result');
  };

  const deleteFromHistory = (id: string) => {
    setHistory(deleteHistoryEntry(id));
  };

  const clearAllHistory = () => {
    setHistory(clearHistory());
  };

  return (
    <SearchContext.Provider
      value={{
        query,
        setQuery,
        status,
        result,
        errorMessage,
        history,
        runSearch,
        handleImageUpload,
        handleReset,
        loadFromHistory,
        deleteFromHistory,
        clearAllHistory,
      }}
    >
      {children}
    </SearchContext.Provider>
  );
};

export const useSearch = () => {
  const ctx = useContext(SearchContext);
  if (!ctx) throw new Error('useSearch는 SearchProvider 내부에서만 사용할 수 있습니다.');
  return ctx;
};
