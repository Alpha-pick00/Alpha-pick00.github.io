import { motion } from 'motion/react';
import { AlertTriangle, ArrowUpRight, Check, RotateCcw, Truck } from 'lucide-react';
import type { DecideResult, DecideStage, BrandOption, Proposal } from '../lib/api';
import { matchClarifyOption } from '../lib/api';
import GradientChatInput, { type ChatMessage } from './ui/gradient-chat-input';

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

export const LoadingCard = ({
  message,
  caption = '최대 1분 소요',
}: {
  message: React.ReactNode;
  caption?: string;
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
  </Card>
);

const STAGE_LABEL: Record<DecideStage, string> = {
  refining: '질의를 다듬고 있습니다',
  searching: '15개 쇼핑몰에서 검색하고 있습니다',
  proposing: 'ChatGPT · Gemini · DeepSeek가 후보를 찾고 있습니다',
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

export const ErrorCard = ({ message, onReset }: { message: string; onReset: () => void }) => (
  <Card>
    <div className="text-center py-4">
      <p className="text-sm font-light text-neutral-600">{message}</p>
      <ResetLink onReset={onReset} />
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

const CLARIFY_STEP_LABEL: Record<ClarifyStep, string> = {
  brand: '브랜드를 선택하면 좁혀드려요',
  product: '제품을 선택하면 좁혀드려요',
  volume: '용량을 선택하면 좁혀드려요',
  quantity: '개수를 선택하면 좁혀드려요',
};

interface Props {
  result: DecideResult;
  onSelectOption: (step: ClarifyStep, value: string) => void;
  onReset: () => void;
  resolvedSteps: Set<ClarifyStep>;
  messages: ChatMessage[];
  onMessagesChange: (updater: (prev: ChatMessage[]) => ChatMessage[]) => void;
  pushMessage: (text: string, sender: ChatMessage['sender']) => void;
}

export const SearchResults = ({
  result,
  onSelectOption,
  onReset,
  resolvedSteps,
  messages,
  onMessagesChange,
  pushMessage,
}: Props) => {
  if (result.mode === 'clarify') {
    const optionsByStep: Record<ClarifyStep, string[]> = {
      brand: result.options.brands,
      product: result.options.products,
      volume: result.options.volumes,
      quantity: result.options.quantities,
    };
    // 브랜드 → 제품 → 용량 → 개수 순으로, 아직 애매한 것만 물어본다 — 하나 고르면
    // 그 값이 검색어에 누적되고(SearchContext.runSearch가 query state를 갱신) 다시
    // 검색해서 이번엔 남은 기준만 애매하면 그것만 다시 보여준다. 한 번에 다 보여주지
    // 않는 이유: 브랜드를 안 정한 채 용량부터 고르면 다른 브랜드의 용량과 섞여
    // 의미가 없어진다.
    // resolvedSteps(사용자가 이 드릴다운에서 이미 답한 단계, Hero.tsx가 추적)에
    // 있는 단계는 백엔드가 이번 라운드에 뭘 내려주든 절대 다시 후보로 넣지
    // 않는다 — 백엔드의 "이미 답했는지" 판정은 질의 텍스트 매칭에 의존하는
        // 근사치라(LLM이 라운드마다 조금씩 다르게 추출할 수 있음) 같은 단계가
    // 반복 노출될 수 있는데, 이 목록은 프론트가 사용자의 실제 클릭으로 직접
    // 관리하므로 100% 확실하다.
    const candidateSteps = CLARIFY_STEP_ORDER.filter((s) => !resolvedSteps.has(s));
    // 실제로 2개 이상이라 "애매한" 기준만 먼저 물어본다(백엔드의 _is_ambiguous와
    // 같은 ">1" 기준) — 1개짜리 기준까지 매번 단계로 넣으면, 브랜드가 이미 하나로
    // 좁혀졌는데도 계속 "브랜드를 선택하세요"만 반복 노출돼 앞으로 못 나간다.
    // 그래도 애매한 게 하나도 없는데 이 화면까지 왔다면(기존 폴백 경로 — 브랜드
    // 하나만 겨우 찾은 경우 등) 그 값이라도 눌러서 진행할 수 있게 ">0"으로 대체한다.
    const step =
      candidateSteps.find((s) => optionsByStep[s].length > 1) ??
      candidateSteps.find((s) => optionsByStep[s].length > 0) ??
      null;
    const options = step ? optionsByStep[step] : [];

    if (!step || options.length === 0) {
      // 남은 단계가 없거나(전부 resolvedSteps에 있음) 옵션이 비었으면 더 물어볼 게
      // 없다는 뜻 — 이 화면에 왔다는 건 후보를 못 찾았다는 뜻이므로 에러로 안내한다.
      return <ErrorCard message="적절한 상품 후보를 찾지 못했습니다." onReset={onReset} />;
    }

    // 채팅으로 타이핑한 자유 텍스트도 받는다 — 버튼과 병행이라, 매칭에 실패해도
    // (LLM이 확신 못 하거나 API 호출 자체가 실패해도) 버튼이 항상 그대로 남아있어
    // 사용자가 막히지 않는다. messages는 Hero.tsx에서 내려주는 공유 스레드라
    // 최초 검색어부터 지금까지의 대화가 하나로 이어진다(말풍선 자체는 Hero의
    // ChatBubbleTrail이 그리므로 여기서는 showBubbles={false}로 입력창만 렌더).
    // key를 step에 묶는 건 입력창의 남은 텍스트만 다음 라운드에 안 넘어가게 하기 위함.
    // 답장 문구는 고정 템플릿이 아니라 매번 matchClarifyOption이 GPT로 새로
    // 생성한 문장이다 — 버튼을 클릭했을 때도 같은 API로 자연스러운 확인 답장을
    // 받는다(아래 onClick 참고).
    const handleChatSend = async (message: string): Promise<string> => {
      const { matched, reply } = await matchClarifyOption(message, options);
      if (matched) {
        onSelectOption(step, matched);
      }
      return reply;
    };

    return (
      <Card>
        <span className="text-xs font-mono uppercase tracking-widest text-neutral-400 block mb-4">
          {CLARIFY_STEP_LABEL[step]}
        </span>
        <div className="flex flex-wrap gap-2 mb-6">
          {options.map((value) => (
            <OptionButton
              key={value}
              value={value}
              onClick={() => {
                pushMessage(value, 'user');
                onSelectOption(step, value);
                matchClarifyOption(value, options).then(({ reply }) => pushMessage(reply, 'bot'));
              }}
            />
          ))}
        </div>
        <GradientChatInput
          key={step}
          placeholder="채팅으로 말씀하셔도 돼요"
          autoReply={null}
          onSend={handleChatSend}
          messages={messages}
          onMessagesChange={onMessagesChange}
          showBubbles={false}
        />
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
      <ResetLink onReset={onReset} />
    </Card>
  );
};
