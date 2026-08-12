import React, { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion, useScroll, useTransform } from 'motion/react';
import { ArrowUp, Loader2, Plus } from 'lucide-react';
import { useSearch } from '../context/SearchContext';
import { fetchAutocomplete } from '../lib/api';
import { LoadingCard, StreamingCard, ErrorCard, SearchResults, type ClarifyStep } from './SearchResults';

export const Hero = () => {
  const containerRef = useRef<HTMLDivElement>(null);
  const { scrollY } = useScroll();

  const yText = useTransform(scrollY, [0, 500], [0, 200]);
  const yBg = useTransform(scrollY, [0, 500], [0, 100]);
  const opacityText = useTransform(scrollY, [0, 300], [1, 0]);

  const {
    query,
    setQuery,
    status,
    result,
    errorMessage,
    streamingStage,
    streamingProposals,
    runSearch,
    handleImageUpload,
    handleReset,
  } = useSearch();

  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const searchBarRef = useRef<HTMLFormElement>(null);

  // Human-in-the-loop 드릴다운(브랜드→제품→용량→개수) 중 사용자가 실제로 클릭해
  // 답한 단계를 기록한다 — 백엔드가 "이미 답했는지"를 질의 텍스트 매칭으로
  // 근사 판정하는 것과 별개로, 여기 있는 단계는 이번 라운드 응답이 뭘 내려주든
  // 절대 다시 후보로 보여주지 않는다(SearchResults.tsx 참고). 새 검색을
  // 시작하거나 리셋하면 새 드릴다운이므로 비운다.
  const [resolvedSteps, setResolvedSteps] = useState<Set<ClarifyStep>>(new Set());

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setShowSuggestions(false);
    setResolvedSteps(new Set());
    runSearch(query);
  };

  const handleSelectOption = (step: ClarifyStep, value: string) => {
    setResolvedSteps((prev) => new Set(prev).add(step));
    runSearch(`${query} ${value}`.trim(), undefined, true);
  };

  const handleResetAll = () => {
    setResolvedSteps(new Set());
    handleReset();
  };

  const onFileSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ''; // 같은 파일을 다시 선택해도 onChange가 또 발생하도록 초기화
    if (!file) return;
    handleImageUpload(file);
  };

  const isBusy = status === 'ocr' || status === 'loading';
  const isSearching = status !== 'idle';

  // 자동완성: 검색 로그가 없는 콜드스타트 제품이라, 카테고리/리테일러로 시드해둔 인덱스에
  // 실제 검색어·판정된 상품명이 쌓이며 자라나는 자체 인덱스를 prefix로 조회한다.
  // status === 'idle'일 때(사용자가 아직 검색을 시작하지 않고 타이핑 중일 때)만
  // 띄운다 — 안 그러면 검색이 끝나(status가 'result'로 바뀌어 isBusy가 false가
  // 되는 순간, 또는 Human-in-the-loop으로 옵션을 골라 query가 계속 바뀔 때마다)
  // 이 이펙트가 다시 돌면서 결과/선택 화면 뒤에 추천창이 또 뜬다.
  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed || isBusy || status !== 'idle') {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }

    const controller = new AbortController();
    const timer = setTimeout(() => {
      fetchAutocomplete(trimmed, controller.signal)
        .then((results) => {
          setSuggestions(results);
          setShowSuggestions(results.length > 0);
          setActiveIndex(-1);
        })
        .catch(() => {});
    }, 200);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query, isBusy, status]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (searchBarRef.current && !searchBarRef.current.contains(event.target as Node)) {
        setShowSuggestions(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const selectSuggestion = (term: string) => {
    setQuery(term);
    setShowSuggestions(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!showSuggestions || suggestions.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((prev) => (prev + 1) % suggestions.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((prev) => (prev <= 0 ? suggestions.length - 1 : prev - 1));
    } else if (e.key === 'Enter' && activeIndex >= 0) {
      e.preventDefault();
      selectSuggestion(suggestions[activeIndex]);
    } else if (e.key === 'Escape') {
      setShowSuggestions(false);
    }
  };

  return (
    <section ref={containerRef} className="relative min-h-screen flex items-center justify-center px-6 pt-16 pb-32 bg-white">

      {/* 1. Cinematic Grain & Gradient Background */}
      <motion.div style={{ y: yBg }} className="absolute inset-0 z-0 pointer-events-none overflow-hidden">
        {/* Subtle Noise Texture */}
        <div className="absolute inset-0 opacity-[0.05] mix-blend-overlay bg-[url('https://grainy-gradients.vercel.app/noise.svg')]" />

        {/* Deep Atmospheric Glows - Boosted Visibility */}
        <div className="absolute top-[-20%] left-[20%] w-[60vw] h-[60vw] bg-violet-900/[0.06] rounded-full blur-[120px] mix-blend-multiply" />
        <div className="absolute bottom-[-20%] right-[20%] w-[50vw] h-[50vw] bg-blue-900/[0.06] rounded-full blur-[120px] mix-blend-multiply" />
      </motion.div>

      {/* 2. Technical Grid Overlay */}
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#00000008_1px,transparent_1px),linear-gradient(to_bottom,#00000008_1px,transparent_1px)] bg-[size:4rem_4rem] [mask-image:radial-gradient(ellipse_80%_80%_at_50%_50%,#000_70%,transparent_100%)] pointer-events-none z-0" />

      {/* 3. Precision Geometric Rings (The "Sleek" Animation) */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-0 overflow-hidden">
        {/* Ring 1: Slow Clockwise - Increased Opacity */}
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ duration: 60, repeat: Infinity, ease: "linear" }}
          className="absolute w-[600px] h-[600px] md:w-[800px] md:h-[800px] rounded-full border border-black/10 border-dashed opacity-50"
        />
        {/* Ring 2: Counter-Clockwise, Solid - Increased Opacity */}
        <motion.div
          animate={{ rotate: -360 }}
          transition={{ duration: 80, repeat: Infinity, ease: "linear" }}
          className="absolute w-[450px] h-[450px] md:w-[600px] md:h-[600px] rounded-full border border-black/10 opacity-40"
        >
          {/* Orbital Dot */}
          <div className="absolute top-1/2 left-0 -translate-x-1/2 -translate-y-1/2 w-2 h-2 bg-black rounded-full shadow-[0_0_15px_rgba(0,0,0,0.8)]" />
        </motion.div>
        {/* Ring 3: Large Outer Ring - Increased Opacity */}
        <motion.div
          animate={{ rotate: 180 }}
          transition={{ duration: 100, repeat: Infinity, ease: "linear" }}
          className="absolute w-[800px] h-[800px] md:w-[1100px] md:h-[1100px] rounded-full border border-black/5 border-dotted opacity-50"
        />
      </div>

      {/* Main Content */}
      <motion.div
        style={{ y: yText, opacity: opacityText }}
        className="relative z-10 w-full max-w-6xl mx-auto flex flex-col items-center text-center"
      >
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, ease: "easeOut" }}
          className="mb-8 text-6xl md:text-8xl font-medium tracking-tighter leading-none"
          style={{ fontFamily: "'Times New Roman', Times, serif", color: 'rgb(64,117,38)' }}
        >
          αlpha Pick
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 1, delay: 0.1, ease: [0.16, 1, 0.3, 1] }}
          className="w-full max-w-4xl mx-auto mb-12"
        >
          <form
            ref={searchBarRef}
            onSubmit={handleSubmit}
            className="relative flex items-center gap-3 pl-2 pr-2 py-2 rounded-full border border-black/10 bg-white/70 backdrop-blur-md shadow-[0_8px_30px_rgba(0,0,0,0.06)]"
          >
            <label
              htmlFor="hero-image-upload"
              aria-label="이미지로 검색"
              className="shrink-0 w-10 h-10 rounded-full flex items-center justify-center border border-black/10 text-neutral-600 hover:bg-black/5 transition-colors cursor-pointer has-[input:disabled]:opacity-50 has-[input:disabled]:pointer-events-none"
            >
              {status === 'ocr' ? (
                <Loader2 className="w-5 h-5 animate-spin" strokeWidth={2.5} />
              ) : (
                <Plus className="w-5 h-5" strokeWidth={2.5} />
              )}
              <input
                id="hero-image-upload"
                type="file"
                accept="image/*"
                className="hidden"
                disabled={isBusy}
                onChange={onFileSelected}
              />
            </label>
            <input
              type="text"
              value={query}
              onChange={(e) => {
                if (status === 'result' || status === 'error') {
                  handleResetAll();
                }
                setQuery(e.target.value);
              }}
              onKeyDown={handleKeyDown}
              onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
              disabled={isBusy}
              placeholder="무엇이든 구매하세요, 또는 상품 사진을 올려보세요"
              autoComplete="off"
              className="flex-1 bg-transparent text-base md:text-lg font-light text-neutral-800 placeholder:text-neutral-400 outline-none disabled:opacity-50"
            />
            <button
              type="submit"
              aria-label="Send"
              disabled={isBusy || !query.trim()}
              className="shrink-0 w-10 h-10 rounded-full flex items-center justify-center transition-transform hover:scale-105 disabled:opacity-50 disabled:hover:scale-100"
              style={{ backgroundColor: '#4ADE80' }}
            >
              {status === 'loading' ? (
                <Loader2 className="w-5 h-5 text-white animate-spin" strokeWidth={2.5} />
              ) : (
                <ArrowUp className="w-5 h-5 text-white" strokeWidth={2.5} />
              )}
            </button>

            <AnimatePresence>
              {showSuggestions && (
                <motion.div
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: 4 }}
                  transition={{ duration: 0.15 }}
                  className="absolute left-0 right-0 top-full mt-2 py-2 rounded-2xl border border-black/10 bg-white/95 backdrop-blur-md shadow-[0_8px_30px_rgba(0,0,0,0.08)] overflow-hidden z-20"
                >
                  {suggestions.map((term, index) => (
                    <button
                      key={term}
                      type="button"
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => selectSuggestion(term)}
                      className={`w-full flex items-center gap-3 px-5 py-2.5 text-left text-sm md:text-base font-light transition-colors ${
                        index === activeIndex ? 'bg-black/5 text-neutral-900' : 'text-neutral-600 hover:bg-black/5'
                      }`}
                    >
                      {term}
                    </button>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </form>
        </motion.div>

        <AnimatePresence mode="wait">
          {!isSearching ? (
            <motion.div key="marketing" exit={{ opacity: 0, y: -10 }} transition={{ duration: 0.3 }}>
              <motion.p
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 1, delay: 0.15, ease: [0.16, 1, 0.3, 1] }}
                className="text-xl md:text-3xl tracking-normal italic text-neutral-500 mb-12"
                style={{ fontFamily: "'Times New Roman', Times, serif" }}
              >
                Compare less, αlpha Pick more
              </motion.p>

              <motion.div
                initial={{ opacity: 0, y: 30 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 1, delay: 0.2, ease: [0.16, 1, 0.3, 1] }}
                className="flex flex-col md:flex-row items-center gap-6 md:gap-16 text-lg font-light text-neutral-600 max-w-4xl mx-auto"
              >
                <p className="md:text-right flex-1 leading-relaxed">
                  Redefining price comparison with clarity<br />
                  and intelligent depth.
                </p>
                <div className="w-px h-16 bg-black/10 hidden md:block" />
                <p className="md:text-left flex-1 leading-relaxed">
                  Based in Korea, Seoul<br />
                  Working Globally
                </p>
              </motion.div>
            </motion.div>
          ) : (
            <motion.div key="results" className="w-full">
              {status === 'ocr' && (
                <LoadingCard message="이미지에서 텍스트를 읽고 있습니다" caption="잠시만 기다려주세요" />
              )}
              {status === 'loading' && (
                <StreamingCard stage={streamingStage || 'refining'} proposals={streamingProposals} />
              )}
              {status === 'error' && <ErrorCard message={errorMessage} onReset={handleResetAll} />}
              {status === 'result' && result && (
                <SearchResults
                  result={result}
                  onSelectOption={handleSelectOption}
                  onReset={handleResetAll}
                  resolvedSteps={resolvedSteps}
                />
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>

      {/* Minimal Scroll Indicator */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1.2, duration: 1 }}
        className="absolute bottom-12 flex flex-col items-center gap-4"
      >
        <span className="text-[10px] font-mono uppercase tracking-widest text-neutral-400">Scroll</span>
        <div className="w-[1px] h-24 bg-gradient-to-b from-transparent via-black/20 to-transparent overflow-hidden">
          <motion.div
            animate={{ y: [-100, 100] }}
            transition={{ repeat: Infinity, duration: 2, ease: "linear" }}
            className="w-full h-1/2 bg-gradient-to-b from-transparent via-black to-transparent"
          />
        </div>
      </motion.div>
    </section>
  );
};
