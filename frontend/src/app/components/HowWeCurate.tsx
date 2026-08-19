import { useRef } from 'react';
import { motion } from 'motion/react';
import { Sparkles, Search, Users, ShieldCheck, Scale, CheckCircle2 } from 'lucide-react';

// judge 슬롯은 2026-08-16부터 Claude가 아니라 Groq(openai/gpt-oss-120b)다(백엔드
// app/agents/judge.py 참고 - Anthropic엔 상시 무료 API 티어가 없다). 이 페이지는
// 그 뒤로도 한동안 "Claude가 심사"라고 안내하고 있었다(사용자 리포트, 2026-08-19:
// "claude 이제 사용안하는데 claude를 이용해 검증한다고 하잖아") - 실제로 안 쓰는
// 모델을 쓴다고 안내하면 안 되므로 여기서 바로잡는다.
const steps = [
  {
    icon: Sparkles,
    title: '질의 정제',
    description: 'Groq가 검색어의 애매한 표현을 먼저 다듬어, 이후 단계가 더 정확한 검색어로 시작하게 합니다.',
  },
  {
    icon: Search,
    title: '다나와 가격비교 검색',
    description: 'Tavily 검색 API로 다나와의 실제 판매 정보만 조회해, 존재하지 않는 상품이나 만료된 프로모션이 섞이지 않게 합니다.',
  },
  {
    icon: Users,
    title: '3개 모델이 각자 제안',
    description: 'Qwen · Groq · DeepSeek가 같은 검색 결과를 보고 독립적으로 상품과 가격, 판매처, 선택 이유를 제안합니다.',
  },
  {
    icon: ShieldCheck,
    title: 'DeepSeek가 교차 검증',
    description: '3개 제안을 다시 검토해, 근거가 부족하거나 검색 결과와 맞지 않는 후보를 미리 걸러냅니다.',
  },
  {
    icon: Scale,
    title: 'Groq가 근거를 심사',
    description: '검증을 통과한 제안과 그 근거만 보고, Groq가 어떤 제안이 실제로 신뢰할 만한지 비교합니다.',
  },
  {
    icon: CheckCircle2,
    title: '하나의 확실한 답',
    description: '최종 추천에는 상품명, 가격, 판매처와 함께 왜 이 답을 선택했는지 근거가 항상 따라붙습니다.',
  },
];

export const HowWeCurate = () => {
  const containerRef = useRef(null);

  return (
    <section ref={containerRef} id="how-we-curate" className="py-32 relative bg-white overflow-hidden">
      {/* Background Grid - Technical Texture, echoes About */}
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#00000008_1px,transparent_1px),linear-gradient(to_bottom,#00000008_1px,transparent_1px)] bg-[size:4rem_4rem] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_50%,#000_70%,transparent_100%)] pointer-events-none" />

      <div className="container mx-auto px-6 relative z-10">

        {/* Section Header */}
        <div className="mb-20 grid md:grid-cols-2 gap-16 items-end">
          <div>
            <div className="flex items-center gap-6 mb-8">
              <div className="flex items-baseline gap-3">
                <span className="font-serif italic text-lg text-neutral-950">04</span>
                <span className="text-xs font-mono uppercase tracking-[0.3em] text-neutral-600">The Process</span>
              </div>
              <div className="h-px w-32 bg-gradient-to-r from-black/30 to-transparent" />
            </div>
            <h2 className="text-5xl md:text-8xl font-medium tracking-tighter leading-[0.9]">
              How We <br />
              <span className="italic font-serif" style={{ color: '#4ADE80' }}>Curate</span>.
            </h2>
          </div>

          <motion.div
            initial={{ opacity: 0, x: 20 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            transition={{ delay: 0.2, duration: 0.8 }}
            className="md:pl-12 border-l border-black/10 relative"
          >
            <div className="absolute top-0 left-[-1px] h-12 w-[1px] bg-gradient-to-b from-black to-transparent" />
            <p className="text-xl md:text-2xl font-light text-neutral-700 leading-relaxed">
              하나의 모델에게 묻지 않습니다. 서로 다른 세 모델이 각자 조사해 제안하고, DeepSeek가 그 근거를
              먼저 검증한 뒤, <span className="font-medium" style={{ color: '#4ADE80' }}>Groq</span>가
              최종 심사합니다.
            </p>
          </motion.div>
        </div>

        {/* Diagram */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.8 }}
          className="rounded-2xl bg-black/[0.02] border border-black/5 p-6 md:p-10 mb-8 overflow-x-auto"
        >
          <svg
            viewBox="0 0 1460 380"
            role="img"
            aria-label="검색어가 들어오면 먼저 Groq가 질의를 다듬고, 백엔드가 Tavily를 통해 다나와를 검색한다. 그 결과를 Qwen, Groq, DeepSeek 세 모델에게 동시에 전달하면 세 모델은 각자 근거를 담아 상품을 제안한다. DeepSeek가 그 세 제안의 근거를 다시 검토해 교차 검증하고, Groq가 검증을 통과한 근거를 비교 심사해 하나의 최종 추천으로 압축한다."
            className="w-full h-auto min-w-[1180px]"
          >
            <defs>
              <marker id="hwc-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
                <path d="M0,0 L10,5 L0,10 z" fill="#a3a3a3" />
              </marker>
              <marker id="hwc-arrow-accent" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
                <path d="M0,0 L10,5 L0,10 z" fill="#4ADE80" />
              </marker>
            </defs>

            {/* Query */}
            <rect x="16" y="150" width="150" height="80" rx="12" fill="#ffffff" stroke="#e5e5e5" />
            <text x="91" y="184" textAnchor="middle" fontSize="13" fontWeight="600" fill="#0a0a0a" fontFamily="-apple-system, sans-serif">검색어 입력</text>
            <text x="91" y="202" textAnchor="middle" fontSize="10.5" fill="#8a8a8a" fontFamily="-apple-system, sans-serif">"무선 이어폰 10만원대"</text>

            {/* Query -> Refine */}
            <line x1="166" y1="190" x2="206" y2="190" stroke="#c7c7c7" strokeWidth="1.4" markerEnd="url(#hwc-arrow)" />

            {/* Refine (Groq) */}
            <rect x="206" y="150" width="150" height="80" rx="12" fill="#ffffff" stroke="#e5e5e5" />
            <text x="281" y="184" textAnchor="middle" fontSize="13" fontWeight="600" fill="#0a0a0a" fontFamily="-apple-system, sans-serif">질의 정제</text>
            <text x="281" y="202" textAnchor="middle" fontSize="10.5" fill="#8a8a8a" fontFamily="-apple-system, sans-serif">Groq</text>

            {/* Refine -> Tavily */}
            <line x1="356" y1="190" x2="396" y2="190" stroke="#c7c7c7" strokeWidth="1.4" markerEnd="url(#hwc-arrow)" />

            {/* Tavily */}
            <rect x="396" y="150" width="150" height="80" rx="12" fill="#ffffff" stroke="#e5e5e5" />
            <text x="471" y="184" textAnchor="middle" fontSize="13" fontWeight="600" fill="#0a0a0a" fontFamily="-apple-system, sans-serif">Tavily 검색</text>
            <text x="471" y="202" textAnchor="middle" fontSize="10.5" fill="#8a8a8a" fontFamily="-apple-system, sans-serif">다나와 한정</text>

            {/* Tavily -> 3 agents fan out */}
            <path d="M546,175 C 594,175 594,50 642,50" fill="none" stroke="#c7c7c7" strokeWidth="1.4" markerEnd="url(#hwc-arrow)" />
            <path d="M546,190 H642" fill="none" stroke="#c7c7c7" strokeWidth="1.4" markerEnd="url(#hwc-arrow)" />
            <path d="M546,205 C 594,205 594,330 642,330" fill="none" stroke="#c7c7c7" strokeWidth="1.4" markerEnd="url(#hwc-arrow)" />
            <text x="569" y="130" fontSize="10" fill="#a3a3a3" fontFamily="ui-monospace, monospace" letterSpacing="0.04em">동일한 검색 결과 전달</text>

            {/* Agent group frame */}
            <rect x="626" y="18" width="196" height="344" rx="14" fill="none" stroke="#e5e5e5" strokeDasharray="3 4" />
            <text x="642" y="38" fontSize="9.5" fill="#a3a3a3" fontFamily="ui-monospace, monospace" letterSpacing="0.06em">병렬 제안 · 독립 실행</text>

            {/* Agent boxes */}
            <rect x="642" y="50" width="164" height="60" rx="10" fill="#fafafa" stroke="#e5e5e5" />
            <text x="724" y="86" textAnchor="middle" fontSize="12.5" fontWeight="600" fill="#0a0a0a" fontFamily="-apple-system, sans-serif">Qwen</text>

            <rect x="642" y="160" width="164" height="60" rx="10" fill="#fafafa" stroke="#e5e5e5" />
            <text x="724" y="196" textAnchor="middle" fontSize="12.5" fontWeight="600" fill="#0a0a0a" fontFamily="-apple-system, sans-serif">Groq</text>

            <rect x="642" y="270" width="164" height="60" rx="10" fill="#fafafa" stroke="#e5e5e5" />
            <text x="724" y="306" textAnchor="middle" fontSize="12.5" fontWeight="600" fill="#0a0a0a" fontFamily="-apple-system, sans-serif">DeepSeek</text>

            {/* Agents -> DeepSeek cross-check converge */}
            <path d="M806,80 C 850,80 850,190 886,190" fill="none" stroke="#c7c7c7" strokeWidth="1.4" markerEnd="url(#hwc-arrow)" />
            <path d="M806,190 H886" fill="none" stroke="#c7c7c7" strokeWidth="1.4" markerEnd="url(#hwc-arrow)" />
            <path d="M806,300 C 850,300 850,190 886,190" fill="none" stroke="#c7c7c7" strokeWidth="1.4" markerEnd="url(#hwc-arrow)" />
            <text x="816" y="130" fontSize="10" fill="#a3a3a3" fontFamily="ui-monospace, monospace" letterSpacing="0.04em">근거와 함께 제안</text>

            {/* DeepSeek cross-check */}
            <rect x="886" y="150" width="150" height="80" rx="12" fill="#ffffff" stroke="#e5e5e5" />
            <text x="961" y="184" textAnchor="middle" fontSize="13" fontWeight="600" fill="#0a0a0a" fontFamily="-apple-system, sans-serif">교차 검증</text>
            <text x="961" y="202" textAnchor="middle" fontSize="10.5" fill="#8a8a8a" fontFamily="-apple-system, sans-serif">DeepSeek · 근거 재검토</text>

            {/* DeepSeek -> Groq(judge) */}
            <line x1="1036" y1="190" x2="1076" y2="190" stroke="#c7c7c7" strokeWidth="1.4" markerEnd="url(#hwc-arrow)" />

            {/* Groq judge */}
            <rect x="1076" y="140" width="170" height="100" rx="14" fill="rgba(74,222,128,0.08)" stroke="#4ADE80" strokeWidth="1.6" />
            <text x="1161" y="182" textAnchor="middle" fontSize="14" fontWeight="700" fill="#0a0a0a" fontFamily="-apple-system, sans-serif">Groq</text>
            <text x="1161" y="200" textAnchor="middle" fontSize="10.5" fill="#166534" fontFamily="-apple-system, sans-serif">근거 비교 심사</text>

            {/* Groq(judge) -> Final */}
            <line x1="1246" y1="190" x2="1302" y2="190" stroke="#4ADE80" strokeWidth="1.6" markerEnd="url(#hwc-arrow-accent)" />

            {/* Final */}
            <rect x="1302" y="140" width="126" height="100" rx="14" fill="#0a0a0a" />
            <text x="1365" y="180" textAnchor="middle" fontSize="13" fontWeight="600" fill="#ffffff" fontFamily="-apple-system, sans-serif">최종 추천</text>
            <text x="1365" y="198" textAnchor="middle" fontSize="9.5" fill="#c7c7c7" fontFamily="-apple-system, sans-serif">상품 · 가격</text>
            <text x="1365" y="212" textAnchor="middle" fontSize="9.5" fill="#c7c7c7" fontFamily="-apple-system, sans-serif">판매처 · 근거</text>
          </svg>
        </motion.div>

        {/* Steps legend */}
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-x-8 gap-y-16 border-t border-black/5 pt-16">
          {steps.map((step, index) => (
            <motion.div
              key={step.title}
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: index * 0.1, duration: 0.6 }}
            >
              <div className="flex items-baseline gap-3 mb-4">
                <span className="font-serif italic text-sm text-neutral-400">0{index + 1}</span>
                <div className="w-9 h-9 rounded-full bg-black/5 flex items-center justify-center">
                  <step.icon className="w-4 h-4 text-neutral-950" />
                </div>
              </div>
              <h3 className="text-lg font-medium tracking-tight mb-2">{step.title}</h3>
              <p className="text-sm font-light text-neutral-600 leading-relaxed">{step.description}</p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
};
