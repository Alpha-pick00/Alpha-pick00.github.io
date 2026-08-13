import { useRef } from 'react';
import { motion, useInView } from 'motion/react';
import { Search, Users, Scale, CheckCircle2 } from 'lucide-react';

const steps = [
  {
    icon: Search,
    title: '다나와 가격비교 검색',
    description: 'Tavily 검색 API로 다나와의 실제 판매 정보만 조회해, 존재하지 않는 상품이나 만료된 프로모션이 섞이지 않게 합니다.',
  },
  {
    icon: Users,
    title: '3개 모델이 각자 제안',
    description: 'ChatGPT · Gemini · DeepSeek가 같은 검색 결과를 보고 독립적으로 상품과 가격, 판매처, 선택 이유를 제안합니다.',
  },
  {
    icon: Scale,
    title: 'Claude가 근거를 심사',
    description: '네 번째 모델인 Claude는 세 제안과 각각의 근거만 보고, 어떤 제안이 실제로 신뢰할 만한지 비교합니다.',
  },
  {
    icon: CheckCircle2,
    title: '하나의 확실한 답',
    description: '최종 추천에는 상품명, 가격, 판매처와 함께 왜 이 답을 선택했는지 근거가 항상 따라붙습니다.',
  },
];

export const HowWeCurate = () => {
  const containerRef = useRef(null);
  const isInView = useInView(containerRef, { once: true, margin: '-100px' });

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
              하나의 모델에게 묻지 않습니다. 서로 다른 세 모델이 각자 조사해 제안하고,
              <span className="font-medium" style={{ color: '#4ADE80' }}> 네 번째 모델</span>이 그 근거만 보고 심사합니다.
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
            viewBox="0 0 1120 380"
            role="img"
            aria-label="검색어가 들어오면 백엔드가 Tavily를 통해 다나와를 검색하고, 그 결과를 ChatGPT, Gemini, DeepSeek 세 모델에게 동시에 전달한다. 세 모델은 각자 근거를 담아 상품을 제안하고, Claude가 그 근거를 비교 심사해 하나의 최종 추천으로 압축한다."
            className="w-full h-auto min-w-[880px]"
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

            {/* Query -> Tavily */}
            <line x1="166" y1="190" x2="222" y2="190" stroke="#c7c7c7" strokeWidth="1.4" markerEnd="url(#hwc-arrow)" />

            {/* Tavily */}
            <rect x="222" y="150" width="160" height="80" rx="12" fill="#ffffff" stroke="#e5e5e5" />
            <text x="302" y="184" textAnchor="middle" fontSize="13" fontWeight="600" fill="#0a0a0a" fontFamily="-apple-system, sans-serif">Tavily 검색</text>
            <text x="302" y="202" textAnchor="middle" fontSize="10.5" fill="#8a8a8a" fontFamily="-apple-system, sans-serif">다나와 한정</text>

            {/* Tavily -> 3 agents fan out */}
            <path d="M382,175 C 430,175 430,50 470,50" fill="none" stroke="#c7c7c7" strokeWidth="1.4" markerEnd="url(#hwc-arrow)" />
            <path d="M382,190 H470" fill="none" stroke="#c7c7c7" strokeWidth="1.4" markerEnd="url(#hwc-arrow)" />
            <path d="M382,205 C 430,205 430,330 470,330" fill="none" stroke="#c7c7c7" strokeWidth="1.4" markerEnd="url(#hwc-arrow)" />
            <text x="405" y="130" fontSize="10" fill="#a3a3a3" fontFamily="ui-monospace, monospace" letterSpacing="0.04em">동일한 검색 결과 전달</text>

            {/* Agent group frame */}
            <rect x="462" y="18" width="196" height="344" rx="14" fill="none" stroke="#e5e5e5" strokeDasharray="3 4" />
            <text x="478" y="38" fontSize="9.5" fill="#a3a3a3" fontFamily="ui-monospace, monospace" letterSpacing="0.06em">병렬 제안 · 독립 실행</text>

            {/* Agent boxes */}
            <rect x="478" y="50" width="164" height="60" rx="10" fill="#fafafa" stroke="#e5e5e5" />
            <text x="560" y="86" textAnchor="middle" fontSize="12.5" fontWeight="600" fill="#0a0a0a" fontFamily="-apple-system, sans-serif">ChatGPT</text>

            <rect x="478" y="160" width="164" height="60" rx="10" fill="#fafafa" stroke="#e5e5e5" />
            <text x="560" y="196" textAnchor="middle" fontSize="12.5" fontWeight="600" fill="#0a0a0a" fontFamily="-apple-system, sans-serif">Gemini</text>

            <rect x="478" y="270" width="164" height="60" rx="10" fill="#fafafa" stroke="#e5e5e5" />
            <text x="560" y="306" textAnchor="middle" fontSize="12.5" fontWeight="600" fill="#0a0a0a" fontFamily="-apple-system, sans-serif">DeepSeek</text>

            {/* Agents -> Claude converge */}
            <path d="M658,80 C 700,80 700,190 742,190" fill="none" stroke="#c7c7c7" strokeWidth="1.4" markerEnd="url(#hwc-arrow)" />
            <path d="M658,190 H742" fill="none" stroke="#c7c7c7" strokeWidth="1.4" markerEnd="url(#hwc-arrow)" />
            <path d="M658,300 C 700,300 700,190 742,190" fill="none" stroke="#c7c7c7" strokeWidth="1.4" markerEnd="url(#hwc-arrow)" />
            <text x="668" y="130" fontSize="10" fill="#a3a3a3" fontFamily="ui-monospace, monospace" letterSpacing="0.04em">근거와 함께 제안</text>

            {/* Claude judge */}
            <rect x="742" y="140" width="180" height="100" rx="14" fill="rgba(74,222,128,0.08)" stroke="#4ADE80" strokeWidth="1.6" />
            <text x="832" y="182" textAnchor="middle" fontSize="14" fontWeight="700" fill="#0a0a0a" fontFamily="-apple-system, sans-serif">Claude</text>
            <text x="832" y="200" textAnchor="middle" fontSize="10.5" fill="#166534" fontFamily="-apple-system, sans-serif">근거 비교 심사</text>

            {/* Claude -> Final */}
            <line x1="922" y1="190" x2="978" y2="190" stroke="#4ADE80" strokeWidth="1.6" markerEnd="url(#hwc-arrow-accent)" />

            {/* Final */}
            <rect x="978" y="140" width="126" height="100" rx="14" fill="#0a0a0a" />
            <text x="1041" y="180" textAnchor="middle" fontSize="13" fontWeight="600" fill="#ffffff" fontFamily="-apple-system, sans-serif">최종 추천</text>
            <text x="1041" y="198" textAnchor="middle" fontSize="9.5" fill="#c7c7c7" fontFamily="-apple-system, sans-serif">상품 · 가격</text>
            <text x="1041" y="212" textAnchor="middle" fontSize="9.5" fill="#c7c7c7" fontFamily="-apple-system, sans-serif">판매처 · 근거</text>
          </svg>
        </motion.div>

        {/* Steps legend */}
        <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-x-8 gap-y-16 border-t border-black/5 pt-16">
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
