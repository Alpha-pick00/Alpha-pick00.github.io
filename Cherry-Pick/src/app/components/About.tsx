import React, { useRef } from 'react';
import { motion, useScroll, useTransform, useInView } from 'motion/react';
import weCraftImage from '../../assets/about/we-craft.jpg';

import coupangLogo from '../../assets/about/logos/coupang.webp';
import naverLogo from '../../assets/about/logos/naver.svg';
import kurlyLogo from '../../assets/about/logos/kurly.jpg';
import ssgLogo from '../../assets/about/logos/ssg.webp';
import gmarketLogo from '../../assets/about/logos/gmarket.webp';
import cjonstyleLogo from '../../assets/about/logos/cjonstyle.webp';
import elevenstLogo from '../../assets/about/logos/11st.webp';
import gsshopLogo from '../../assets/about/logos/gsshop.png';
import hyundaihmallLogo from '../../assets/about/logos/hyundaihmall.webp';
import auctionLogo from '../../assets/about/logos/auction.webp';
import aliexpressLogo from '../../assets/about/logos/aliexpress.webp';
import daisoLogo from '../../assets/about/logos/daiso.webp';
import lotteimallLogo from '../../assets/about/logos/lotteimall.webp';
import interparkLogo from '../../assets/about/logos/interpark.jpg';
import danawaLogo from '../../assets/about/logos/danawa.webp';

const compareClients = [
  { name: '쿠팡', url: 'https://www.coupang.com', logo: coupangLogo },
  { name: '네이버쇼핑', url: 'https://shopping.naver.com', logo: naverLogo },
  { name: '컬리', url: 'https://www.kurly.com', logo: kurlyLogo },
  { name: 'SSG', url: 'https://www.ssg.com', logo: ssgLogo },
  { name: 'G마켓', url: 'https://www.gmarket.co.kr', logo: gmarketLogo },
  { name: 'CJ온스타일', url: 'https://www.cjonstyle.com', logo: cjonstyleLogo },
  { name: '11번가', url: 'https://www.11st.co.kr', logo: elevenstLogo },
  { name: 'GS SHOP', url: 'https://www.gsshop.com', logo: gsshopLogo },
  { name: '현대홈쇼핑', url: 'https://www.hyundaihmall.com', logo: hyundaihmallLogo },
  { name: '옥션', url: 'https://www.auction.co.kr', logo: auctionLogo },
  { name: '알리익스프레스', url: 'https://www.aliexpress.com', logo: aliexpressLogo },
  { name: '다이소', url: 'https://www.daisomall.co.kr', logo: daisoLogo },
  { name: '롯데홈쇼핑', url: 'https://www.lotteimall.com', logo: lotteimallLogo },
  { name: '인터파크', url: 'https://www.interpark.com', logo: interparkLogo },
  { name: '다나와', url: 'https://www.danawa.com', logo: danawaLogo },
];

export const About = () => {
  const containerRef = useRef(null);
  const isInView = useInView(containerRef, { once: true, margin: "-100px" });
  
  const { scrollYProgress } = useScroll({
    target: containerRef,
    offset: ["start end", "end start"]
  });

  const opacity = useTransform(scrollYProgress, [0, 0.3], [0, 1]);

  return (
    <section ref={containerRef} id="about" className="py-32 relative bg-white overflow-hidden">
      {/* Background Grid - Technical Texture */}
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#00000008_1px,transparent_1px),linear-gradient(to_bottom,#00000008_1px,transparent_1px)] bg-[size:4rem_4rem] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_50%,#000_70%,transparent_100%)] pointer-events-none" />

      <div className="container mx-auto px-6">
        
        {/* Section Header - Consistent Style */}
        <div className="flex items-center gap-6 mb-24">
           <div className="flex items-baseline gap-3">
              <span className="font-serif italic text-lg text-neutral-950">01</span>
              <span className="text-xs font-mono uppercase tracking-[0.3em] text-neutral-600">About <span style={{ color: '#EC4899' }}>Cherry</span>.Pick</span>
           </div>
           <div className="h-px w-32 bg-gradient-to-r from-black/30 to-transparent" />
        </div>

        <div className="grid lg:grid-cols-[1.2fr_0.8fr] gap-20 items-start">

          {/* Text Content */}
          <div className="relative z-10 min-w-0">
            <motion.h2 
              initial={{ opacity: 0, y: 100 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
              className="text-5xl md:text-8xl font-medium tracking-tighter mb-12 leading-[0.9]"
            >
              We craft <br />
              <span className="italic font-serif" style={{ color: '#EC4899' }}>smarter</span> choices.
            </motion.h2>

            <div className="grid md:grid-cols-2 gap-12 text-lg font-light text-neutral-600 leading-relaxed">
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: 0.2, duration: 0.8 }}
                className="space-y-6"
              >
                <p>
                  탭으로 가득한 세상에서, 우리는 단 하나의 답을 선택합니다. 수십 개의 창 너머로 당신의 시선을 붙잡으려는 모든 플랫폼, 모든 가격, 모든 프로모션. 우리는 소음을 더하는 대신, 소음을 끝내는 경험을 만듭니다.
                </p>
                <p>
                  우리의 철학은 단순합니다. 가장 좋은 비교는 당신이 직접 하지 않아도 되는 비교입니다. 우리는 더 많은 데이터를 보여주지 않습니다. 오직 중요한 것만 남겨, 하나의 확실한 추천으로 압축해 보여드립니다.
                </p>
              </motion.div>
              
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: 0.3, duration: 0.8 }}
                className="space-y-6"
              >
                <p>
                  우리는 효용과 신뢰가 별개의 기능이 아니라 같은 개념이라고 믿습니다. 이유 없는 가격은 아무 의미가 없습니다. 그래서 우리가 제시하는 모든 답에는 근거가 함께합니다.
                </p>
                <p className="text-black/80">
                  우리는 돈만큼이나 시간을 소중히 여기는 쇼퍼를 위해 만듭니다. 또 하나의 확인할 앱이 아니라, 모든 것을 대신 확인해주는 단 하나의 앱을 위해서요.
                </p>
              </motion.div>
            </div>

            {/* Stats & Trust */}
            <div className="mt-16 pt-16 border-t border-black/5">
               <div className="grid grid-cols-3 gap-8 mb-16">
                 <div className="space-y-2 border-r border-black/5">
                   <h4 className="text-4xl font-light text-neutral-950">2026</h4>
                   <p className="text-xs uppercase tracking-widest text-neutral-500">Launching</p>
                 </div>
                 <div className="space-y-2 border-r border-black/5">
                   <h4 className="text-4xl font-light text-neutral-950">15<span className="text-neutral-400 text-lg">+</span></h4>
                   <p className="text-xs uppercase tracking-widest text-neutral-500">Platforms Compared</p>
                 </div>
                 <div className="space-y-2">
                   <h4 className="text-4xl font-light text-neutral-950">100K</h4>
                   <p className="text-xs uppercase tracking-widest text-neutral-500">Target Users by Year 3</p>
                 </div>
               </div>
            </div>
          </div>

          {/* Image Area */}
          <motion.div 
            style={{ opacity }}
            className="relative lg:mt-24"
          >
            <div className="relative z-10">
               <motion.div 
                 whileHover={{ scale: 0.98 }}
                 transition={{ duration: 0.5 }}
                 className="aspect-[4/5] overflow-hidden grayscale hover:grayscale-0 transition-all duration-700 ease-in-out bg-neutral-100"
               >
                 <img
                   src={weCraftImage}
                   alt="Workspace"
                   className="w-full h-full object-cover opacity-80"
                 />
                 <div className="absolute inset-0 bg-gradient-to-t from-black/50 to-transparent" />
               </motion.div>
               
               {/* Decorative Ring */}
               <div className="absolute -bottom-12 -left-12 w-48 h-48 border border-black/10 rounded-full flex items-center justify-center backdrop-blur-sm hidden md:flex" style={{ animation: 'spin 15s linear infinite' }}>
                 <style dangerouslySetInnerHTML={{__html: `
                   @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
                 `}} />
                 <svg className="w-full h-full p-2" viewBox="0 0 100 100">
                   <path id="circlePath" d="M 50, 50 m -37, 0 a 37,37 0 1,1 74,0 a 37,37 0 1,1 -74,0" fill="transparent" />
                   <text className="fill-neutral-500 text-[10px] uppercase tracking-widest font-mono">
                     <textPath href="#circlePath">
                       - Price Comparison • AI Curation • Smart Shopping
                     </textPath>
                   </text>
                 </svg>
               </div>
            </div>
          </motion.div>

        </div>

        {/* Client List - Trust Factor (full section width) */}
        <div className="mt-20 pt-16 border-t border-black/5">
          <span className="text-base font-mono uppercase tracking-widest text-neutral-400 block mb-6">We Compare across</span>
          <style dangerouslySetInnerHTML={{__html: `
            @keyframes marquee { from { transform: translateX(0); } to { transform: translateX(-50%); } }
            .marquee-track:hover { animation-play-state: paused; }
          `}} />
          {[compareClients.slice(0, 8), compareClients.slice(8)].map((row, rowIndex) => (
            <div
              key={rowIndex}
              className="relative w-full overflow-hidden [mask-image:linear-gradient(to_right,transparent,black_8%,black_92%,transparent)] mb-6 last:mb-0"
            >
              <div
                className="marquee-track flex w-max items-center gap-10 whitespace-nowrap"
                style={{ animation: `marquee ${rowIndex === 0 ? 50 : 60}s linear infinite` }}
              >
                {[...row, ...row].map((client, i) => (
                  <a
                    key={`${client.name}-${i}`}
                    href={client.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={client.name}
                    className="shrink-0 flex items-center justify-center h-16 px-6 rounded-xl bg-neutral-100 grayscale opacity-70 hover:grayscale-0 hover:opacity-100 transition-all cursor-pointer"
                  >
                    <img src={client.logo} alt={client.name} className="h-6 md:h-7 w-auto max-w-[120px] object-contain" />
                  </a>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
};
