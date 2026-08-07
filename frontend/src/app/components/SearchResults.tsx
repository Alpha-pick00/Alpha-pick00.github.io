import { motion } from 'motion/react';
import { ArrowUpRight, RotateCcw, Truck } from 'lucide-react';
import type { DecideResult, BrandOption } from '../lib/api';

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
    className="w-full max-w-4xl mx-auto rounded-3xl border border-black/10 bg-white/80 backdrop-blur-md shadow-[0_8px_30px_rgba(0,0,0,0.06)] p-8 md:p-10 text-left"
  >
    {children}
  </motion.div>
);

const ResetLink = ({ onReset }: { onReset: () => void }) => (
  <button
    type="button"
    onClick={onReset}
    className="mt-8 inline-flex items-center gap-2 text-xs font-mono uppercase tracking-widest text-neutral-400 hover:text-neutral-950 transition-colors"
  >
    <RotateCcw className="w-3.5 h-3.5" />
    다시 검색
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

export const LoadingCard = ({ query }: { query: string }) => (
  <Card>
    <div className="flex flex-col items-center text-center py-6 gap-4">
      <motion.div
        animate={{ rotate: 360 }}
        transition={{ duration: 1.2, repeat: Infinity, ease: 'linear' }}
        className="w-8 h-8 rounded-full border-2 border-black/10 border-t-[#4ADE80]"
      />
      <p className="text-sm font-light text-neutral-500">
        <span className="font-medium text-neutral-950">"{query}"</span> 에 대해 ChatGPT · Gemini ·
        DeepSeek가 후보를 찾고, Claude가 최종 비교하고 있습니다
      </p>
      <p className="text-xs font-mono uppercase tracking-widest text-neutral-400">최대 1분 소요</p>
    </div>
  </Card>
);

export const ErrorCard = ({ message, onReset }: { message: string; onReset: () => void }) => (
  <Card>
    <div className="text-center py-4">
      <p className="text-sm font-light text-neutral-600">{message}</p>
      <ResetLink onReset={onReset} />
    </div>
  </Card>
);

interface Props {
  result: DecideResult;
  onSelectBrand: (brand: string) => void;
  onReset: () => void;
}

export const SearchResults = ({ result, onSelectBrand, onReset }: Props) => {
  if (result.mode === 'clarify') {
    const { brands, volumes, quantities } = result.options;
    return (
      <Card>
        <span className="text-xs font-mono uppercase tracking-widest text-neutral-400 block mb-4">
          브랜드를 선택하면 최저가를 찾아드려요
        </span>
        <div className="flex flex-wrap gap-2">
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
        {(volumes.length > 0 || quantities.length > 0) && (
          <p className="mt-4 text-xs font-light text-neutral-400">
            {[...volumes, ...quantities].join(' · ')}
          </p>
        )}
        <ResetLink onReset={onReset} />
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
        <ResetLink onReset={onReset} />
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
        <ResetLink onReset={onReset} />
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
      <ResetLink onReset={onReset} />
    </Card>
  );
};
