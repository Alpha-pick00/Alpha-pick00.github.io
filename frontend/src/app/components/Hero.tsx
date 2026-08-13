import React, { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion, useScroll, useTransform } from 'motion/react';
import { ArrowUp, Loader2, Plus, Search } from 'lucide-react';
import { useSearch } from '../context/SearchContext';
import { useSidebar } from '../context/SidebarContext';
import { fetchAutocomplete } from '../lib/api';
import { LoadingCard, ErrorCard, SearchResults } from './SearchResults';

export const Hero = () => {
  const containerRef = useRef<HTMLDivElement>(null);
  const { scrollY } = useScroll();

  const yBg = useTransform(scrollY, [0, 500], [0, 100]);
  const yText = useTransform(scrollY, [0, 500], [0, 200]);
  const opacityText = useTransform(scrollY, [0, 300], [1, 0]);

  const { turns, isBusy, ocrBusy, sendMessage, selectBrand, selectFacets, retryTurn, handleImageUpload, handleReset } =
    useSearch();
  const { isOpen: sidebarOpen } = useSidebar();

  const [draft, setDraft] = useState('');
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const searchBarRef = useRef<HTMLFormElement>(null);
  const threadEndRef = useRef<HTMLDivElement>(null);

  const hasConversation = turns.length > 0;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const text = draft;
    setDraft('');
    setShowSuggestions(false);
    sendMessage(text);
  };

  const onFileSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ''; // 같은 파일을 다시 선택해도 onChange가 또 발생하도록 초기화
    if (!file) return;
    handleImageUpload(file);
  };

  // 자동완성: 검색 로그가 없는 콜드스타트 제품이라, 카테고리/리테일러로 시드해둔 인덱스에
  // 실제 검색어·판정된 상품명이 쌓이며 자라나는 자체 인덱스를 prefix로 조회한다.
  useEffect(() => {
    const trimmed = draft.trim();
    if (!trimmed || isBusy) {
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
  }, [draft, isBusy]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (searchBarRef.current && !searchBarRef.current.contains(event.target as Node)) {
        setShowSuggestions(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // 새 메시지가 오가거나 답변 상태가 바뀔 때마다 스레드 맨 아래로 붙인다(사용자
  // 요청, 2026-08-15: "채팅은 밑에 붙이고"). 위쪽에 로고/배너용 여백을 따로 예약해
  // 두지 않는다 - 그 예약된 빈 공간 자체가 "배너처럼 떠 보인다"는 신고의 원인이었다.
  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [turns]);

  const selectSuggestion = (term: string) => {
    setDraft(term);
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

  const composer = (
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
        {ocrBusy ? (
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
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={handleKeyDown}
        onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
        disabled={isBusy}
        placeholder={hasConversation ? '무엇이든 더 물어보세요' : '무엇이든 구매하세요, 또는 상품 사진을 올려보세요'}
        autoComplete="off"
        className="flex-1 bg-transparent text-base md:text-lg font-light text-neutral-800 placeholder:text-neutral-400 outline-none disabled:opacity-50"
      />
      <button
        type="submit"
        aria-label="Send"
        disabled={isBusy || !draft.trim()}
        className="shrink-0 w-10 h-10 rounded-full flex items-center justify-center transition-transform hover:scale-105 disabled:opacity-50 disabled:hover:scale-100"
        style={{ backgroundColor: '#4ADE80' }}
      >
        {isBusy ? (
          <Loader2 className="w-5 h-5 text-white animate-spin" strokeWidth={2.5} />
        ) : (
          <ArrowUp className="w-5 h-5 text-white" strokeWidth={2.5} />
        )}
      </button>

      <AnimatePresence>
        {showSuggestions && (
          <motion.div
            initial={{ opacity: 0, y: hasConversation ? -4 : 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: hasConversation ? -4 : 4 }}
            transition={{ duration: 0.15 }}
            className={`absolute left-0 right-0 py-2 rounded-2xl border border-black/10 bg-white/95 backdrop-blur-md shadow-[0_8px_30px_rgba(0,0,0,0.08)] overflow-hidden z-20 ${
              hasConversation ? 'bottom-full mb-2' : 'top-full mt-2'
            }`}
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
                <Search className="w-4 h-4 text-neutral-400 shrink-0" strokeWidth={2} />
                {term}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </form>
  );

  return (
    <section
      ref={containerRef}
      className={`relative flex flex-col bg-white ${hasConversation ? 'h-screen' : 'min-h-screen'}`}
    >
      {/* 1. Cinematic Grain & Gradient Background */}
      <motion.div style={{ y: yBg }} className="absolute inset-0 z-0 pointer-events-none overflow-hidden">
        <div className="absolute inset-0 opacity-[0.05] mix-blend-overlay bg-[url('https://grainy-gradients.vercel.app/noise.svg')]" />
        <div className="absolute top-[-20%] left-[20%] w-[60vw] h-[60vw] bg-violet-900/[0.06] rounded-full blur-[120px] mix-blend-multiply" />
        <div className="absolute bottom-[-20%] right-[20%] w-[50vw] h-[50vw] bg-blue-900/[0.06] rounded-full blur-[120px] mix-blend-multiply" />
      </motion.div>

      {/* 2. Technical Grid Overlay */}
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#00000008_1px,transparent_1px),linear-gradient(to_bottom,#00000008_1px,transparent_1px)] bg-[size:4rem_4rem] [mask-image:radial-gradient(ellipse_80%_80%_at_50%_50%,#000_70%,transparent_100%)] pointer-events-none z-0" />

      {/* 3. Precision Geometric Rings */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-0 overflow-hidden">
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ duration: 60, repeat: Infinity, ease: 'linear' }}
          className="absolute w-[600px] h-[600px] md:w-[800px] md:h-[800px] rounded-full border border-black/10 border-dashed opacity-50"
        />
        <motion.div
          animate={{ rotate: -360 }}
          transition={{ duration: 80, repeat: Infinity, ease: 'linear' }}
          className="absolute w-[450px] h-[450px] md:w-[600px] md:h-[600px] rounded-full border border-black/10 opacity-40"
        >
          <div className="absolute top-1/2 left-0 -translate-x-1/2 -translate-y-1/2 w-2 h-2 bg-black rounded-full shadow-[0_0_15px_rgba(0,0,0,0.8)]" />
        </motion.div>
        <motion.div
          animate={{ rotate: 180 }}
          transition={{ duration: 100, repeat: Infinity, ease: 'linear' }}
          className="absolute w-[800px] h-[800px] md:w-[1100px] md:h-[1100px] rounded-full border border-black/5 border-dotted opacity-50"
        />
      </div>

      {!hasConversation ? (
        // 대화 시작 전: 기존 랜딩 히어로 그대로 (로고 + 태그라인 + 검색창 중앙 정렬)
        <motion.div
          style={{ y: yText, opacity: opacityText }}
          className="relative z-10 flex-1 flex flex-col items-center justify-center text-center px-6 pt-16 pb-32"
        >
          <div className="w-full max-w-6xl mx-auto flex flex-col items-center">
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.8, ease: 'easeOut' }}
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
              {composer}
            </motion.div>

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
                Redefining price comparison with clarity
                <br />
                and intelligent depth.
              </p>
              <div className="w-px h-16 bg-black/10 hidden md:block" />
              <p className="md:text-left flex-1 leading-relaxed">
                Based in Korea, Seoul
                <br />
                Working Globally
              </p>
            </motion.div>
          </div>
        </motion.div>
      ) : (
        // 대화 시작 후: ChatGPT/Claude처럼 위로 스레드가 쌓이고 입력창은 하단에 고정.
        // 답변은 LLM이 지어내는 게 아니라 다나와 실측 가격 파이프라인(useSearch)이 그대로 채운다.
        // 로고는 더 이상 스레드 중앙 칼럼 안에 있지 않고, 사이드바 레일(왼쪽 68px) 바로
        // 옆에 고정된 헤더로 옮겨서 ChatGPT류 앱들처럼 왼쪽 상단에 붙게 한다. 사이드바
        // 패널이 펼쳐지면(레일 68px + 패널 300px) 그만큼 더 오른쪽으로 따라간다 -
        // App.tsx의 본문 padding-left와 같은 두 값을 공유해야 해서 리터럴로 맞춰뒀다.
        <>
          <button
            type="button"
            onClick={handleReset}
            aria-label="처음 화면으로"
            className={`hidden md:block fixed top-6 z-50 text-3xl font-medium tracking-tighter transition-[left] duration-300 ease-out hover:opacity-80 ${
              sidebarOpen ? 'left-[296px]' : 'left-[84px]'
            }`}
            style={{ fontFamily: "'Times New Roman', Times, serif", color: 'rgb(64,117,38)' }}
          >
            αlpha Pick
          </button>

          <div className="relative z-10 flex flex-col flex-1 min-h-0">
            {/* 위쪽에 로고용 여백을 예약해두지 않는다(사용자 신고, 2026-08-15:
                "위에 배너 알파픽부터 위에 이어지는 부분 없애라") - 그 예약 공간이
                내용이 짧을 때도 항상 배너처럼 남아 있었다. 스크롤 컨테이너를 세로
                flex로 만들고 내용물에 mt-auto를 줘서, 내용이 뷰포트보다 짧으면
                아래(입력창 바로 위)에 붙고, 넘치면 원래대로 위에서부터 쌓여
                스크롤된다. */}
            <div className="flex-1 min-h-0 overflow-y-auto px-6 flex flex-col">
              <div className="max-w-3xl mx-auto w-full py-4 mt-auto">
                <div className="space-y-6">
                {turns.map((turn) => (
                  <div key={turn.id} className="space-y-3">
                    <div className="flex justify-end">
                      <div className="max-w-[80%] rounded-[18px_18px_4px_18px] bg-neutral-950 text-white px-4 py-2.5 text-sm md:text-base font-light text-left break-words">
                        {turn.displayQuery}
                      </div>
                    </div>
                    <div className="flex justify-start">
                      <div className="w-full">
                        {turn.status === 'loading' && (
                          <LoadingCard
                            message={
                              <>
                                <span className="font-medium text-neutral-950">"{turn.displayQuery}"</span> 의 다나와
                                실측 가격을 찾고 있습니다
                              </>
                            }
                            candidates={turn.partialCandidates}
                          />
                        )}
                        {turn.status === 'error' && (
                          <ErrorCard
                            message={turn.errorMessage}
                            onReset={() => retryTurn(turn.id)}
                            resetLabel="다시 시도"
                          />
                        )}
                        {turn.status === 'result' && turn.result && (
                          <SearchResults
                            result={turn.result}
                            onSelectBrand={(brand) => selectBrand(turn.id, brand)}
                            onConfirmFacets={(values) => selectFacets(turn.id, values)}
                          />
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <div ref={threadEndRef} />
            </div>
          </div>

            <div className="shrink-0 px-6 pt-3 pb-6 bg-gradient-to-t from-white via-white/95 to-transparent">
              <div className="max-w-3xl mx-auto w-full">{composer}</div>
            </div>
          </div>
        </>
      )}
    </section>
  );
};
