import { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { ArrowUpRight, RotateCcw, Search, Truck } from 'lucide-react';
import type { ClarifyFacet as ClarifyFacetType, DanawaStreamCandidate, DecideResult, BrandOption } from '../lib/api';

const fadeUp = {
  initial: { opacity: 0, y: 16 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.5, ease: [0.16, 1, 0.3, 1] as const },
};

const AGENT_LABEL: Record<string, string> = {
  gpt: 'ChatGPT',
  gemini: 'Gemini',
  deepseek: 'DeepSeek',
};

const Card = ({ children }: { children: React.ReactNode }) => (
  <motion.div
    {...fadeUp}
    className="w-full rounded-3xl border border-black/10 bg-white/80 backdrop-blur-md shadow-[0_8px_30px_rgba(0,0,0,0.06)] p-6 md:p-8 text-left"
  >
    {children}
  </motion.div>
);

const ResetLink = ({ onReset, label = '다시 검색' }: { onReset: () => void; label?: string }) => (
  <button
    type="button"
    onClick={onReset}
    className="mt-6 inline-flex items-center gap-2 text-xs font-mono uppercase tracking-widest text-neutral-400 hover:text-neutral-950 transition-colors"
  >
    <RotateCcw className="w-3.5 h-3.5" />
    {label}
  </button>
);

const BrandOptionRow = ({ option }: { option: BrandOption }) => (
  <a
    href={option.url}
    target="_blank"
    rel="noopener noreferrer"
    className="group flex items-center justify-between gap-4 py-4 border-b border-black/5 last:border-b-0 hover:bg-black/[0.02] transition-colors -mx-2 px-2 rounded-lg"
  >
    <div className="min-w-0">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium text-neutral-950">{option.brand}</span>
        {option.delivery_note && (
          <span className="inline-flex items-center gap-1 text-[11px] text-neutral-500">
            <Truck className="w-3 h-3" />
            {option.delivery_note}
          </span>
        )}
      </div>
      <p className="text-sm font-light text-neutral-500 truncate">{option.product_name}</p>
    </div>
    <div className="shrink-0 flex items-center gap-2">
      <span className="text-base font-medium text-neutral-950 whitespace-nowrap">
        {option.price || '가격 미확인'}
      </span>
      <ArrowUpRight className="w-4 h-4 text-neutral-300 group-hover:text-neutral-950 transition-colors" />
    </div>
  </a>
);

const StreamCandidateRow = ({ candidate }: { candidate: DanawaStreamCandidate }) => (
  <motion.div
    {...fadeUp}
    className="flex items-center justify-between gap-4 py-3 border-b border-black/5 last:border-b-0"
  >
    <div className="min-w-0">
      <p className="text-sm font-light text-neutral-600 truncate">{candidate.product_name || '상품명 미확인'}</p>
      {candidate.retailer && <p className="text-xs font-light text-neutral-400">{candidate.retailer}</p>}
    </div>
    <span className="shrink-0 text-sm font-medium text-neutral-950 whitespace-nowrap">
      {candidate.price || '가격 확인 중'}
    </span>
  </motion.div>
);

export const LoadingCard = ({
  message,
  caption = '최대 1분 소요',
  candidates = [],
}: {
  message: React.ReactNode;
  caption?: string;
  candidates?: DanawaStreamCandidate[];
}) => (
  <Card>
    <div className="flex flex-col items-center text-center py-6 gap-4">
      <motion.div
        animate={{ rotate: 360 }}
        transition={{ duration: 1.2, repeat: Infinity, ease: 'linear' }}
        className="w-8 h-8 rounded-full border-2 border-black/10 border-t-[#4ADE80]"
      />
      <p className="text-sm font-light text-neutral-500">{message}</p>
      <p className="text-xs font-mono uppercase tracking-widest text-neutral-400">{caption}</p>
    </div>
    {candidates.length > 0 && (
      <div className="mt-2 pt-4 border-t border-black/5 text-left">
        {candidates.map((c, i) => (
          <StreamCandidateRow key={`${c.product_name}-${i}`} candidate={c} />
        ))}
      </div>
    )}
  </Card>
);

export const ErrorCard = ({
  message,
  onReset,
  resetLabel = '다시 검색',
}: {
  message: string;
  onReset?: () => void;
  resetLabel?: string;
}) => (
  <Card>
    <div className="text-center py-4">
      <p className="text-sm font-light text-neutral-600">{message}</p>
      {onReset && <ResetLink onReset={onReset} label={resetLabel} />}
    </div>
  </Card>
);

interface Props {
  result: DecideResult;
  onSelectBrand: (brand: string) => void;
  onConfirmFacets: (values: string[]) => void;
  onReset?: () => void;
}

export const SearchResults = ({ result, onSelectBrand, onConfirmFacets, onReset }: Props) => {
  // AI 상세검색: facet마다 하나씩 고르고, 화면에 떠 있는 기준을 전부 고른
  // 순간에만 검색이 실행된다(사용자 요청, 2026-08-13: "상세검색에서 고를때마다
  // 검색하는걸로 바꿧어 다시 다 고르면 검색되는걸로 바꿔" - 브랜드 하나만 눌러도
  // 바로 다음 턴으로 넘어가던 걸 되돌린 것). 선택 상태는 로컬로 들고 있다가,
  // 모든 facet이 채워지는 순간 useEffect가 자동으로 onConfirmFacets를 부른다
  // (버튼은 없다 - "검색하기 버튼 없어도 될거같아"). facets는 mode==='clarify'
  // 일 때만 존재하지만 Hooks는 조건부로 못 부르니 다른 모드에서는 빈 배열로 둔다.
  const [selectedFacets, setSelectedFacets] = useState<Record<string, string>>({});
  const [facetQuery, setFacetQuery] = useState<Record<string, string>>({});
  const facets = result.mode === 'clarify' ? result.options.facets : [];

  useEffect(() => {
    if (facets.length === 0 || !facets.every((f) => selectedFacets[f.label])) return;
    const values = facets.map((f) => selectedFacets[f.label]).filter((v): v is string => Boolean(v));
    onConfirmFacets(values);
    // facets/onConfirmFacets는 매 렌더 새 참조라 deps에 넣으면 무한 루프가 된다 -
    // "선택 상태가 바뀔 때"만 완주 여부를 재확인하면 충분하다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedFacets]);

  if (result.mode === 'clarify') {
    const { brands, volumes, quantities } = result.options;
    const hasAnyOptions = brands.length > 0 || facets.length > 0;

    // 지금까지 고른 값들(어느 facet이든 - 브랜드로 한정 안 됨)로 아직 안 고른
    // facet들의 보이는 옵션을 즉시 좁힌다(추가 요청 없이, 사용자 요청 2026-08-13:
    // "삼성전자를 누르면은 시리즈에 삼성전자에 관한것만" -> 2026-08-14: "시리즈에
    // 초코파이 바나나를 골랏다면 용량에 없는것들은 선택할수없게" - 브랜드 전용
    // 특수 케이스였던 걸 모든 facet 쌍으로 일반화했다). 여러 facet을 골랐으면
    // 각각의 options_by_selection을 교집합으로 겹쳐 좁힌다.
    const visibleOptionsFor = (facet: ClarifyFacetType, selected: Record<string, string>): string[] => {
      let options = facet.options;
      for (const [otherLabel, value] of Object.entries(selected)) {
        if (otherLabel === facet.label) continue;
        const filtered = facet.options_by_selection?.[value];
        if (filtered) {
          options = options.filter((o) => filtered.includes(o));
        }
      }
      return options;
    };

    const toggleFacetOption = (label: string, option: string) => {
      setSelectedFacets((prev) => {
        if (prev[label] === option) {
          const next = { ...prev };
          delete next[label];
          return next;
        }
        const next = { ...prev, [label]: option };
        // 이 선택으로 다른 facet의 보이는 옵션이 바뀌어 기존 선택이 더 이상
        // 유효한 값이 아니게 됐으면 지운다 - 안 그러면 서로 안 맞는 조합(예:
        // "초코파이 바나나" + "336g")이 그대로 남아있을 수 있다.
        for (const other of facets) {
          if (other.label === label) continue;
          const selectedForOther = next[other.label];
          if (!selectedForOther) continue;
          if (!visibleOptionsFor(other, next).includes(selectedForOther)) {
            delete next[other.label];
          }
        }
        return next;
      });
    };

    return (
      <Card>
        <span className="text-xs font-mono uppercase tracking-widest text-neutral-400 block mb-4">
          {hasAnyOptions ? 'AI 상세검색 · 조건을 모두 선택하면 검색해요' : '조건을 좁힐 수 없었어요'}
        </span>
        {brands.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-4 last:mb-0">
            {brands.map((brand) => (
              <button
                key={brand}
                onClick={() => onSelectBrand(brand)}
                className="px-4 py-2 rounded-full border border-black/10 text-sm font-light hover:bg-neutral-950 hover:text-white hover:border-neutral-950 transition-all"
              >
                {brand}
              </button>
            ))}
          </div>
        )}
        {facets.map((facet) => {
          const baseOptions = visibleOptionsFor(facet, selectedFacets);
          const query = facetQuery[facet.label] ?? '';
          const visibleOptions = query.trim()
            ? baseOptions.filter((o) => o.toLowerCase().includes(query.trim().toLowerCase()))
            : baseOptions;
          return (
            <div key={facet.label} className="mb-4 last:mb-0">
              <span className="text-xs font-light text-neutral-400 block mb-2">{facet.label}</span>
              {facet.options.length > 4 && (
                <div className="relative mb-2">
                  <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-300" />
                  <input
                    type="text"
                    value={query}
                    onChange={(e) => setFacetQuery((prev) => ({ ...prev, [facet.label]: e.target.value }))}
                    placeholder={`${facet.label} 찾기`}
                    className="w-full pl-8 pr-3 py-2 rounded-full border border-black/10 text-sm font-light outline-none focus:border-neutral-950 transition-colors"
                  />
                </div>
              )}
              <div className="flex flex-wrap gap-2">
                {visibleOptions.length > 0 ? (
                  visibleOptions.map((option) => {
                    const isSelected = selectedFacets[facet.label] === option;
                    return (
                      <button
                        key={option}
                        onClick={() => toggleFacetOption(facet.label, option)}
                        className={`px-4 py-2 rounded-full border text-sm font-light transition-all ${
                          isSelected
                            ? 'bg-neutral-950 text-white border-neutral-950'
                            : 'border-black/10 hover:bg-neutral-950 hover:text-white hover:border-neutral-950'
                        }`}
                      >
                        {option}
                      </button>
                    );
                  })
                ) : (
                  <span className="text-xs font-light text-neutral-400">일치하는 항목이 없어요</span>
                )}
              </div>
            </div>
          );
        })}
        {(volumes.length > 0 || quantities.length > 0) && (
          <p className="mt-2 text-xs font-light text-neutral-400">
            {[...volumes, ...quantities].join(' · ')}
          </p>
        )}
        {onReset && <ResetLink onReset={onReset} />}
      </Card>
    );
  }

  if (result.mode === 'brand_price') {
    if (result.error || !result.option) {
      return <ErrorCard message={result.error || '해당 브랜드 상품을 찾지 못했습니다.'} onReset={onReset} />;
    }
    return (
      <Card>
        <span className="text-xs font-mono uppercase tracking-widest text-neutral-400 block mb-4">
          {result.brand} 최저가
        </span>
        <BrandOptionRow option={result.option} />
        {onReset && <ResetLink onReset={onReset} />}
      </Card>
    );
  }

  if (result.mode === 'bulk') {
    const { decision, price_range } = result;
    return (
      <Card>
        <div className="flex items-baseline justify-between mb-2">
          <span className="text-xs font-mono uppercase tracking-widest text-neutral-400">
            브랜드별 최저가 {decision.options.length}개
          </span>
          {price_range && (
            <span className="text-xs font-light text-neutral-400">
              {price_range.min} ~ {price_range.max}
            </span>
          )}
        </div>
        <p className="text-sm font-light text-neutral-500 mb-4">{decision.reasoning}</p>
        <div>
          {decision.options.map((option) => (
            <BrandOptionRow key={option.brand} option={option} />
          ))}
        </div>
        {onReset && <ResetLink onReset={onReset} />}
      </Card>
    );
  }

  // mode === 'single'
  const { decision, proposals } = result;
  return (
    <Card>
      <span className="text-xs font-mono uppercase tracking-widest text-neutral-400 block mb-4">
        최종 추천 · {AGENT_LABEL[decision.chosen_agent] || decision.chosen_agent} 제안 채택
      </span>
      <a
        href={decision.url}
        target="_blank"
        rel="noopener noreferrer"
        className="group flex items-start justify-between gap-4 mb-3"
      >
        <div className="min-w-0">
          <p className="text-lg font-medium text-neutral-950">{decision.product_name}</p>
          <p className="text-sm font-light text-neutral-500">{decision.retailer}</p>
        </div>
        <div className="shrink-0 flex items-center gap-2">
          <span className="text-xl font-medium text-neutral-950 whitespace-nowrap">
            {decision.price || '가격 미확인'}
          </span>
          <ArrowUpRight className="w-5 h-5 text-neutral-300 group-hover:text-neutral-950 transition-colors" />
        </div>
      </a>
      <p className="text-sm font-light text-neutral-600 leading-relaxed mb-6">{decision.reasoning}</p>

      <div className="pt-4 border-t border-black/5 grid grid-cols-1 sm:grid-cols-3 gap-3">
        {proposals.map((p) => (
          <div key={p.agent} className="text-xs">
            <span className="font-mono uppercase tracking-widest text-neutral-400">
              {AGENT_LABEL[p.agent] || p.agent}
            </span>
            <p className="mt-1 font-light text-neutral-600 truncate">
              {p.error ? p.error : `${p.product_name} · ${p.price || '가격 미확인'}`}
            </p>
          </div>
        ))}
      </div>
      {onReset && <ResetLink onReset={onReset} />}
    </Card>
  );
};
