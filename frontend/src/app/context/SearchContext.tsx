import React, { createContext, useContext, useEffect, useState } from 'react';
import {
  decideStream,
  extractOcr,
  fetchServerHistory,
  saveServerHistory,
  deleteServerHistoryEntry,
  clearServerHistory,
  ApiError,
  type DecideResult,
  type DecideStage,
  type Proposal,
  type ServerHistoryEntry,
} from '../lib/api';
import { getStoredToken } from '../lib/auth';
import { useAuth } from './AuthContext';
import {
  deleteHistoryEntry,
  clearHistory,
  loadHistory,
  saveHistoryEntry,
  type HistoryEntry,
} from '../lib/history';

const fromServerEntry = (entry: ServerHistoryEntry): HistoryEntry => ({
  id: entry.id,
  query: entry.query,
  timestamp: entry.timestamp * 1000, // 서버는 초 단위, 프론트는 Date.now() 기준 ms 단위로 통일
  result: entry.result,
});

export type SearchStatus = 'idle' | 'ocr' | 'loading' | 'result' | 'error';

interface SearchContextValue {
  query: string;
  setQuery: (q: string) => void;
  status: SearchStatus;
  result: DecideResult | null;
  errorMessage: string;
  history: HistoryEntry[];
  streamingStage: DecideStage | null;
  streamingProposals: Proposal[];
  runSearch: (q: string, brand?: string, skipIntentCheck?: boolean) => Promise<void>;
  handleImageUpload: (file: File) => Promise<void>;
  handleReset: () => void;
  loadFromHistory: (entry: HistoryEntry) => void;
  deleteFromHistory: (id: string) => void;
  clearAllHistory: () => void;
}

const SearchContext = createContext<SearchContextValue | null>(null);

export const SearchProvider = ({ children }: { children: React.ReactNode }) => {
  const { user } = useAuth();
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState<SearchStatus>('idle');
  const [result, setResult] = useState<DecideResult | null>(null);
  const [errorMessage, setErrorMessage] = useState('');
  const [history, setHistory] = useState<HistoryEntry[]>(() => loadHistory());
  const [streamingStage, setStreamingStage] = useState<DecideStage | null>(null);
  const [streamingProposals, setStreamingProposals] = useState<Proposal[]>([]);

  // 로그인 상태가 바뀌면 기록 소스를 전환한다 — 로그인하면 그 계정의 서버 기록을
  // 불러오고, 로그아웃하면 이 브라우저의 로컬 기록으로 되돌아간다.
  useEffect(() => {
    if (!user) {
      setHistory(loadHistory());
      return;
    }
    const token = getStoredToken();
    if (!token) return;
    fetchServerHistory(token).then((entries) => setHistory(entries.map(fromServerEntry)));
  }, [user]);

  const persistHistoryEntry = async (q: string, data: DecideResult) => {
    if (user) {
      const token = getStoredToken();
      if (!token) return;
      const saved = await saveServerHistory(token, q, data);
      if (saved) {
        setHistory((prev) => [fromServerEntry(saved), ...prev]);
      }
      return;
    }
    setHistory(saveHistoryEntry(q, data));
  };

  const runSearch = async (q: string, brand?: string, skipIntentCheck?: boolean) => {
    if (!q.trim()) return;
    // 검색어 자체를 상태로도 반영해둔다 — Human-in-the-loop으로 브랜드→용량→수량을
    // 순차 선택할 때, 각 선택이 "원래 입력한 질의"가 아니라 "직전까지 좁혀온 질의"에
    // 이어붙어야 누적된다(안 그러면 용량을 고르는 순간 앞서 고른 브랜드가 날아간다).
    setQuery(q);
    setStatus('loading');
    setErrorMessage('');
    setStreamingStage('searching');
    setStreamingProposals([]);
    try {
      let data: DecideResult | null = null;
      let streamError: string | null = null;

      await decideStream(q, (event) => {
        if (event.type === 'status') {
          setStreamingStage(event.stage);
        } else if (event.type === 'proposal') {
          setStreamingProposals((prev) => [...prev, event.proposal]);
        } else if (event.type === 'final') {
          data = event.result;
        } else if (event.type === 'error') {
          streamError = event.message;
        }
      }, brand, undefined, skipIntentCheck);

      if (streamError || !data) {
        throw new ApiError(streamError || '요청 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.');
      }

      setResult(data);
      setStatus('result');
      persistHistoryEntry(q, data).catch(() => {});
    } catch (err) {
      setErrorMessage(
        err instanceof ApiError ? err.message : '요청 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.'
      );
      setStatus('error');
    } finally {
      setStreamingStage(null);
      setStreamingProposals([]);
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
    setQuery('');
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
    if (user) {
      const token = getStoredToken();
      if (token) deleteServerHistoryEntry(token, id).catch(() => {});
      setHistory((prev) => prev.filter((h) => h.id !== id));
      return;
    }
    setHistory(deleteHistoryEntry(id));
  };

  const clearAllHistory = () => {
    if (user) {
      const token = getStoredToken();
      if (token) clearServerHistory(token).catch(() => {});
      setHistory([]);
      return;
    }
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
        streamingStage,
        streamingProposals,
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
