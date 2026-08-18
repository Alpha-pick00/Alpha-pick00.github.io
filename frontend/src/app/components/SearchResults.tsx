import { useEffect, useRef, useState } from 'react';
import { motion } from 'motion/react';
import { AlertTriangle, ArrowUpRight, Check, RotateCcw, Search, Sparkles, Truck } from 'lucide-react';
import type {
  ClarifyFacet as ClarifyFacetType,
  DecideResult,
  DecideStage,
  BrandOption,
  Proposal,
} from '../lib/api';
import { askClarifyQuestion } from '../lib/api';

const fadeUp = {
  initial: { opacity: 0, y: 16 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.5, ease: [0.16, 1, 0.3, 1] as const },
};

// agent="gpt" 슬롯은 내부 식별자만 그대로고 실제 모델은 Qwen이다(2026-08-15,
// "GPT 토큰이 더 이상 없어서 Qwen 성능 제일 좋은 걸로 바꿔줘" - 백엔드
// agents/gpt.py 참고). 사용자에게 보이는 이름만 여기서 바꾼다. "gemini" 슬롯은
// 2026-08-18("Gemini 이제 안쓰니까 이름 제대로 바꿔서 코드 반영해") 식별자
// 자체를 "groq"로 리네임했다(agents/groq.py 참고) - 표시 이름도 함께 바꿨다.
const AGENT_LABEL: Record<string, string> = {
  gpt: 'Qwen',
  groq: 'Groq',
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

const STAGE_LABEL: Record<DecideStage, string> = {
  refining: '질의를 다듬고 있습니다',
  searching: '다나와에서 검색하고 있습니다',
  proposing: 'Qwen · Groq · DeepSeek가 후보를 찾고 있습니다',
  challenging: 'DeepSeek가 근거를 검증하고 있습니다',
  judging: 'Claude가 근거를 비교해 최종 추천을 고르고 있습니다',
};

const ProposedByChips = ({ proposedBy }: { proposedBy: string[] | null | undefined }) =>
  proposedBy && proposedBy.length > 0 ? (
    <span className="text-[10px] font-mono uppercase tracking-widest text-neutral-400">
      {proposedBy.map((a) => AGENT_LABEL[a] || a).join(' · ')}
    </span>
  ) : null;

const VerifiedBadge = ({ verified }: { verified: boolean | null | undefined }) => {
  if (verified === true) {
    return (
      <div className="shrink-0 w-5 h-5 rounded-full bg-[#4ADE80]/15 flex items-center justify-center">
        <Check className="w-3 h-3 text-[#166534]" strokeWidth={3} />
      </div>
    );
  }
  if (verified === false) {
    return (
      <div className="shrink-0 w-5 h-5 rounded-full bg-amber-500/15 flex items-center justify-center">
        <AlertTriangle className="w-3 h-3 text-amber-700" strokeWidth={2.5} />
      </div>
    );
  }
  return <div className="shrink-0 w-5 h-5 rounded-full bg-black/5" />;
};

const CandidateProgressRow = ({ proposal }: { proposal: Proposal }) => (
  <div className="flex items-start gap-3 py-2.5 border-b border-black/5 last:border-b-0">
    <VerifiedBadge verified={proposal.verified} />
    <div className="min-w-0 flex-1">
      <div className="flex items-center gap-2">
        <p className="min-w-0 flex-1 text-sm font-light text-neutral-600 truncate">
          {proposal.error ? proposal.error : `${proposal.product_name} · ${proposal.price || '가격 미확인'}`}
        </p>
        <ProposedByChips proposedBy={proposal.proposed_by} />
      </div>
      {proposal.challenge_note && (
        <p className="mt-0.5 text-xs font-light text-neutral-400 truncate">{proposal.challenge_note}</p>
      )}
    </div>
  </div>
);

// AI 오케스트레이션(adk_pipeline: 정제→검색→제안→검증→심사) 진행 상태를 턴 안에서
// 보여준다 - Hero.tsx가 turn.streamingStage/streamingProposals(SearchContext.runTurn이
// decideStream 이벤트로 채운다)를 이 컴포넌트에 그대로 넘긴다.
export const StreamingCard = ({ stage, proposals }: { stage: DecideStage; proposals: Proposal[] }) => (
  <Card>
    <div className="flex flex-col items-center text-center py-2 gap-6">
      <motion.div
        animate={{ rotate: 360 }}
        transition={{ duration: 1.2, repeat: Infinity, ease: 'linear' }}
        className="w-8 h-8 rounded-full border-2 border-black/10 border-t-[#4ADE80]"
      />
      <p className="text-sm font-light text-neutral-500">{STAGE_LABEL[stage]}</p>

      {proposals.length > 0 && (
        <div className="w-full text-left">
          {proposals.map((p, i) => (
            <CandidateProgressRow key={p.url ?? i} proposal={p} />
          ))}
        </div>
      )}
    </div>
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

const OptionButton = ({ value, onClick }: { value: string; onClick: () => void }) => (
  <button
    onClick={onClick}
    className="px-4 py-2 rounded-full border border-black/10 text-sm font-light hover:bg-neutral-950 hover:text-white hover:border-neutral-950 transition-all"
  >
    {value}
  </button>
);

export type ClarifyStep = 'brand' | 'product' | 'volume' | 'quantity';

const CLARIFY_STEP_ORDER: ClarifyStep[] = ['brand', 'product', 'volume', 'quantity'];

// 고정 축(제품/용량/개수 - 브랜드는 아래에서 다나와 브랜드 최저가 단축 경로로
// 따로 렌더된다) 하나를 실제 상담원처럼 자연스러운 질문 한 문장으로 물어보고
// 버튼으로 답을 받는다. 채팅으로도 답할 수 있게 별도 입력창을 카드마다
// 두었었는데, 화면 하단에 이미 검색창(GradientChatInput)이 있어 중복이라
// 없앴다(사용자 요청, 2026-08-15) - 답은 버튼으로만 받는다.
const FixedAxisClarifyCard = ({
  query,
  options,
  onSelectOption,
}: {
  query: string;
  options: string[];
  onSelectOption: (value: string) => void;
}) => {
  const [question, setQuestion] = useState<string | null>(null);
  const askedKeyRef = useRef<string | null>(null);

  useEffect(() => {
    const key = options.join('|');
    if (askedKeyRef.current === key) return;
    askedKeyRef.current = key;
    setQuestion(null);
    askClarifyQuestion(query, options).then(setQuestion);
  }, [query, options.join('|')]);

  return (
    <div>
      {question && (
        <div className="mb-3 inline-block max-w-[85%] rounded-[14px_14px_14px_4px] bg-black/[0.04] px-4 py-2.5 text-sm font-light text-neutral-700">
          {question}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {options.map((value) => (
          <OptionButton key={value} value={value} onClick={() => onSelectOption(value)} />
        ))}
      </div>
    </div>
  );
};

interface Props {
  result: DecideResult;
  // 사용자 페르소나(2026-08-15) - 이번 세션에서 이미 고른 {facet 라벨: 값}.
  // 옵션 순서 자체는 백엔드가 이미 반영해 보내주므로, 여기서는 일치하는
  // 버튼에 "선호" 표시만 붙이는 시각적 용도로 쓴다.
  sessionPreferences?: Record<string, string>;
  onSelectBrand: (brand: string) => void;
  // (사용자 페르소나, 2026-08-15) label -> 선택값 맵을 그대로 넘긴다 - 값
  // 배열만 받으면 SearchContext가 어느 facet 라벨에서 이 값을 골랐는지 몰라
  // 계정/세션 페르소나에 기록할 수 없다.
  onConfirmFacets: (selected: Record<string, string>) => void;
  onSelectClarifyOption: (step: Exclude<ClarifyStep, 'brand'>, value: string) => void;
}

export const SearchResults = ({
  result,
  sessionPreferences = {},
  onSelectBrand,
  onConfirmFacets,
  onSelectClarifyOption,
}: Props) => {
  // AI 상세검색: facet마다 하나씩 고른다. 예전엔 화면에 떠 있는 기준을 전부
  // 골라야만 검색이 실행됐는데(2026-08-13: "상세검색에서 고를때마다 검색하는걸로
  // 바꿧어 다시 다 고르면 검색되는걸로 바꿔"), 사용자가 원하는 값이 목록에
  // 없거나 모든 기준을 다 정하고 싶지 않을 수도 있어서(2026-08-14: "일부분만
  // 선택해도 넘어갈 수 있게") 지금은 "검색하기" 버튼을 눌러야 그 시점까지 고른
  // 값(일부만 골랐어도 그대로)으로 진행한다. facets는 mode==='clarify'일 때만
  // 존재하지만 Hooks는 조건부로 못 부르니 다른 모드에서는 빈 배열로 둔다.
  const [selectedFacets, setSelectedFacets] = useState<Record<string, string>>({});
  const [facetQuery, setFacetQuery] = useState<Record<string, string>>({});
  const facets = result.mode === 'clarify' ? result.options.facets : [];

  if (result.mode === 'clarify') {
    const { brands, products, volumes, quantities } = result.options;
    const hasAnyOptions =
      brands.length > 0 || facets.length > 0 || products.length > 0 || volumes.length > 0 || quantities.length > 0;

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

    // 고정 축(제품/용량/개수) 중 이번 라운드에 물어볼 하나만 고른다 - 한 번에
    // 다 보여주면 서로 다른 축이 뒤섞여 어떤 조합을 고르는 건지 애매해진다.
    // 옵션이 2개 이상인("진짜 애매한") 축을 우선하고, 전부 1개뿐이면(폴백) 그중
    // 아무거나로 진행할 수 있게 열어준다. 브랜드는 다나와 브랜드 최저가 단축
    // 경로(onSelectBrand)로 이미 별도 렌더되므로 이 로테이션에서 제외한다.
    // facets(AI 상세검색)와는 서로 다른 clarify 소스(check_clarify_facets/
    // run_clarify)라 겹치지 않고 그대로 병행 노출된다.
    const fixedOptionsByStep: Partial<Record<ClarifyStep, string[]>> = {
      product: products,
      volume: volumes,
      quantity: quantities,
    };
    const fixedSteps = CLARIFY_STEP_ORDER.filter((s): s is Exclude<ClarifyStep, 'brand'> => s !== 'brand');
    const step =
      fixedSteps.find((s) => (fixedOptionsByStep[s]?.length ?? 0) > 1) ??
      fixedSteps.find((s) => (fixedOptionsByStep[s]?.length ?? 0) > 0) ??
      null;
    const stepOptions = step ? fixedOptionsByStep[step] ?? [] : [];

    return (
      <Card>
        <span className="text-xs font-mono uppercase tracking-widest text-neutral-400 block mb-4">
          {hasAnyOptions ? 'AI 상세검색 · 조건을 선택하거나 채팅으로 답해주세요' : '조건을 좁힐 수 없었어요'}
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
                    // 사용자 페르소나(2026-08-15) - 이번 세션에서 이 라벨에 이미
                    // 골랐던 값이면 별 표시로 "평소 선택"임을 알려준다. 옵션
                    // 순서 자체(맨 앞으로 당기기)는 백엔드가 이미 반영했으니
                    // 여기서는 순수 시각적 확인 표시.
                    const isPersonaPick = !isSelected && sessionPreferences[facet.label] === option;
                    return (
                      <button
                        key={option}
                        onClick={() => toggleFacetOption(facet.label, option)}
                        className={`inline-flex items-center gap-1.5 px-4 py-2 rounded-full border text-sm font-light transition-all ${
                          isSelected
                            ? 'bg-neutral-950 text-white border-neutral-950'
                            : isPersonaPick
                            ? 'border-[#4ADE80]/50 bg-[#4ADE80]/10 hover:bg-neutral-950 hover:text-white hover:border-neutral-950'
                            : 'border-black/10 hover:bg-neutral-950 hover:text-white hover:border-neutral-950'
                        }`}
                      >
                        {isPersonaPick && <Sparkles className="w-3 h-3 text-[#166534]" strokeWidth={2.5} />}
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
        {facets.length > 0 && (
          <div className="mb-4 last:mb-0 flex justify-end">
            <button
              onClick={() => onConfirmFacets(selectedFacets)}
              disabled={Object.keys(selectedFacets).length === 0}
              className="px-5 py-2.5 rounded-full bg-[#4ADE80] text-neutral-950 text-sm font-medium disabled:opacity-30 disabled:cursor-not-allowed hover:bg-[#3EBD6E] transition-all"
            >
              검색하기
            </button>
          </div>
        )}
        {step && (
          <div className="mb-4 last:mb-0">
            <FixedAxisClarifyCard
              query={result.query}
              options={stepOptions}
              onSelectOption={(value) => onSelectClarifyOption(step, value)}
            />
          </div>
        )}
      </Card>
    );
  }

  if (result.mode === 'brand_price') {
    if (result.error || !result.option) {
      return <ErrorCard message={result.error || '해당 브랜드 상품을 찾지 못했습니다.'} />;
    }
    return (
      <Card>
        <span className="text-xs font-mono uppercase tracking-widest text-neutral-400 block mb-4">
          {result.brand} 최저가
        </span>
        <BrandOptionRow option={result.option} />
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
      </Card>
    );
  }

  // mode === 'single'
  const { decision, proposals } = result;
  const winningProposal = proposals.find((p) => p.url === decision.url);
  const winningProposers = winningProposal?.proposed_by?.length
    ? winningProposal.proposed_by
    : [decision.chosen_agent];
  const headerLabel =
    winningProposers.length > 1
      ? `${winningProposers.map((a) => AGENT_LABEL[a] || a).join(' · ')} 공동 제안 채택`
      : `${AGENT_LABEL[winningProposers[0]] || winningProposers[0]} 제안 채택`;

  return (
    <Card>
      <span className="text-xs font-mono uppercase tracking-widest text-neutral-400 block mb-4">
        최종 추천 · {headerLabel}
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

      <div className="pt-4 border-t border-black/5 grid grid-cols-1 sm:grid-cols-2 gap-3">
        {proposals.map((p, i) => (
          <div key={p.url ?? i} className="flex items-start gap-2 text-xs">
            <VerifiedBadge verified={p.verified} />
            <div className="min-w-0">
              <ProposedByChips proposedBy={p.proposed_by} />
              <p className="mt-1 font-light text-neutral-600 truncate">
                {p.error ? p.error : `${p.product_name} · ${p.price || '가격 미확인'}`}
              </p>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
};
