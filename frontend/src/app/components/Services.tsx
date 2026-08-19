import { useRef } from 'react';
import { motion } from 'motion/react';
import { Bot, ScanLine, ShoppingBag, BadgeCheck } from 'lucide-react';

const services = [
  {
    icon: Bot,
    title: "멀티에이전트 토론",
    description: "ChatGPT, Groq, DeepSeek가 각자 상품을 조사해 제안하고, Groq가 그 근거를 심사해 하나의 답으로 압축합니다."
  },
  {
    icon: ScanLine,
    title: "이미지로 바로 검색",
    description: "상품 사진 한 장만 올리면 OCR과 AI가 상품명을 읽어내 곧바로 가격 비교를 시작합니다."
  },
  {
    icon: ShoppingBag,
    title: "검증된 15개 리테일러",
    description: "쿠팡, 네이버쇼핑, G마켓 등 실제 판매 중인 국내 쇼핑몰만 골라 비교합니다."
  },
  {
    icon: BadgeCheck,
    title: "근거 있는 추천",
    description: "가격만 나열하지 않습니다. 왜 이 상품을 골랐는지, 이유까지 함께 보여드립니다."
  }
];

export const Services = () => {
  const containerRef = useRef(null);

  return (
    <section ref={containerRef} id="services" className="py-32 px-6 bg-white relative overflow-hidden">
       {/* Dynamic Background */}
       <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(0,0,0,0.03),transparent_50%)] pointer-events-none" />
       <motion.div
         animate={{ rotate: 360 }}
         transition={{ duration: 60, repeat: Infinity, ease: "linear" }}
         className="absolute -top-[20%] -right-[10%] w-[800px] h-[800px] border border-black/5 rounded-full pointer-events-none opacity-50 dashed-border"
         style={{ borderStyle: 'dashed' }}
       />
       <motion.div
         animate={{ rotate: -360 }}
         transition={{ duration: 80, repeat: Infinity, ease: "linear" }}
         className="absolute top-[20%] right-[10%] w-[600px] h-[600px] border border-black/5 rounded-full pointer-events-none opacity-30"
       />

      <div className="container mx-auto relative z-10">
        
        {/* Section Header */}
        <div className="mb-32 grid md:grid-cols-2 gap-16 items-end">
          <div>
            <div className="flex items-center gap-6 mb-8">
               <div className="flex items-baseline gap-3">
                  <span className="font-serif italic text-lg text-neutral-950">03</span>
                  <span className="text-xs font-mono uppercase tracking-[0.3em] text-neutral-600">/ Capabilities</span>
               </div>
               <div className="h-px w-32 bg-gradient-to-r from-black/30 to-transparent" />
            </div>
            <motion.h2 
              initial={{ opacity: 0, y: 50 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.8 }}
              className="text-6xl md:text-9xl font-medium tracking-tighter leading-none"
            >
              Curation <br />
              <span className="italic font-serif" style={{ color: '#4ADE80' }}>Solutions</span>
            </motion.h2>
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
              대화형 <span className="font-medium" style={{ color: '#4ADE80' }}>AI</span>와 실시간 가격 비교를 결합해, 진짜 믿을 수 있는 결정을 만들어 드립니다.
            </p>
          </motion.div>
        </div>

        {/* Services Grid */}
        <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-x-8 gap-y-24 group/list">
          {services.map((service, index) => (
            <motion.div
               key={index}
               initial={{ opacity: 0, y: 50 }}
               whileInView={{ opacity: 1, y: 0 }}
               viewport={{ once: true }}
               transition={{ delay: index * 0.1, duration: 0.8 }}
               className={`
                 relative 
                 ${index % 2 === 1 ? 'lg:mt-32' : ''} 
                 transition-all duration-500 ease-out
                 hover:!opacity-100 group-hover/list:opacity-20
               `}
            >
               {/* Editorial Decorative Corners */}
               <div className="absolute -top-6 -left-6 w-3 h-3 border-t border-l border-black/20 transition-all duration-500 group-hover:w-[calc(100%+3rem)] group-hover:h-[calc(100%+3rem)] group-hover:border-black/10 pointer-events-none" />
               <div className="absolute -bottom-6 -right-6 w-3 h-3 border-b border-r border-black/20 transition-all duration-500 group-hover:w-[calc(100%+3rem)] group-hover:h-[calc(100%+3rem)] group-hover:border-black/10 pointer-events-none" />
               
               <ServiceCard service={service} index={index} />
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
};

const ServiceCard = ({ service, index }: { service: any, index: number }) => {
  return (
    <motion.div
      initial={{ opacity: 0, y: 30 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true }}
      transition={{ delay: index * 0.1, duration: 0.5 }}
      whileHover={{ y: -10 }}
      className="group p-8 rounded-2xl bg-black/5 border border-black/5 hover:border-black/20 hover:bg-black/10 transition-all duration-500 backdrop-blur-sm"
    >
      <div className="mb-8 w-12 h-12 rounded-full bg-black/5 flex items-center justify-center group-hover:bg-neutral-950 group-hover:text-white transition-colors duration-500">
        <service.icon className="w-6 h-6" />
      </div>

      <h3 className="text-xl font-medium mb-4 tracking-tight">{service.title}</h3>
      <p className="text-neutral-600 font-light leading-relaxed group-hover:text-neutral-700 transition-colors">
        {service.description}
      </p>
    </motion.div>
  );
};
