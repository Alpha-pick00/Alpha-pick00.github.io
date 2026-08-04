import React, { useRef } from 'react';
import { motion, useScroll, useTransform, useInView } from 'motion/react';
import weCraftImage from '../../assets/about/we-craft.jpg';

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
          <div className="relative z-10">
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
                  In a world full of tabs, we choose the one answer. Every platform, every price, every promotion — screaming for your attention across a dozen open windows. We build an experience that ends the noise, not adds to it.
                </p>
                <p>
                  Our philosophy is simple: the best comparison is the one you never have to make yourself. We don't show you more data. We show you less — only what matters, distilled into a single, confident recommendation.
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
                  We believe utility and trust are not separate features, but the same idea. A price means nothing without the reason behind it. So every answer we give comes with its evidence — visible, explainable, yours to verify.
                </p>
                <p className="text-black/80">
                  We build for the shopper who values their time as much as their money. Not another app to check. The one that checks everything, so you don't have to.
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
                   <h4 className="text-4xl font-light text-neutral-950">5<span className="text-neutral-400 text-lg">+</span></h4>
                   <p className="text-xs uppercase tracking-widest text-neutral-500">Platforms Compared</p>
                 </div>
                 <div className="space-y-2">
                   <h4 className="text-4xl font-light text-neutral-950">100K</h4>
                   <p className="text-xs uppercase tracking-widest text-neutral-500">Target Users by Year 3</p>
                 </div>
               </div>

               {/* Client List - Trust Factor */}
               <div>
                 <span className="text-xs font-mono uppercase tracking-widest text-neutral-400 block mb-6">Compare across</span>
                 <div className="flex flex-wrap gap-x-12 gap-y-4 text-neutral-600 font-medium text-lg">
                   {[
                     { name: '쿠팡', url: 'https://www.coupang.com' },
                     { name: '네이버쇼핑', url: 'https://shopping.naver.com' },
                     { name: '컬리', url: 'https://www.kurly.com' },
                     { name: 'SSG', url: 'https://www.ssg.com' },
                     { name: 'G마켓', url: 'https://www.gmarket.co.kr' },
                   ].map((client, i) => (
                     <motion.a
                       key={client.name}
                       href={client.url}
                       target="_blank"
                       rel="noopener noreferrer"
                       initial={{ opacity: 0 }}
                       whileInView={{ opacity: 1 }}
                       transition={{ delay: 0.5 + (i * 0.1) }}
                       className="hover:text-neutral-950 transition-colors cursor-pointer"
                     >
                       {client.name}
                     </motion.a>
                   ))}
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
      </div>
    </section>
  );
};
