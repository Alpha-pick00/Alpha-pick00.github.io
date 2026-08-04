import React, { useRef } from 'react';
import { motion, useScroll, useTransform, useInView } from 'motion/react';
import weCraftImage from '../../assets/about/we-craft.jpg';

const compareClients = [
  { name: '쿠팡', url: 'https://www.coupang.com', logo: 'https://i.namu.wiki/i/rbr9t6DyPW0j_NIFboYnSstx08x-dokipUMHUr3pkvVYRd1ZfvdKI9XNo864YvyLL1hzCoOBopf6_W2lZjHt1ZqKzxtvxa3HvC1Rrr99y6DikZbjUOYKyX5FtoVsCYbIgBoczoyM6tQhu3U0PwzwZw.svg' },
  { name: '네이버쇼핑', url: 'https://shopping.naver.com', logo: 'https://i.namu.wiki/i/pHw8G52GZ-RuxDVw1tsP4GiW2TWvZJI85WcOE_Hg736PWDWpYJcoW26JTO33HrqrS4kxpxQ9o2StMdRMUDcvjw.svg' },
  { name: '컬리', url: 'https://www.kurly.com', logo: 'https://i.namu.wiki/i/5PMX-ZmnsfRYzjK0Fr2VHk3cUPdZTqlzayhIl1PO0ORebAfnRN0BNOoStbs0GsddTSvT2ZpMEi62Hhf5K4EruA.svg' },
  { name: 'SSG', url: 'https://www.ssg.com', logo: 'https://i.namu.wiki/i/a3iuuLWyAVxn4K1-59aebbalD4dQbpC-N6RDvusHd3gLVKYg9hXxLXjI3Up6X5khH0PTW6xxkDhyZDidCTKgQ3974rNNMVye2JHPhs9HXIjTZX6LInQWsZcG7g8EjUfh-atSVWuc3ATJnThKo7LoGQ.svg' },
  { name: 'G마켓', url: 'https://www.gmarket.co.kr', logo: 'https://i.namu.wiki/i/M5C3qV6mNdFqoImsyQedchEF9zqKXnjEyMrFVuH2trWAumJJGBZ-XYXZ4bDFb3ByCzlF3_4KNDt0EHG1_QAV4JWTfCsgDsMw1aZNwrfJSMgFyXnggbREJvpaxgYhNT4xGcl1HwHCCkI4ihWjg9MJqg.svg' },
  { name: 'CJ온스타일', url: 'https://www.cjonstyle.com', logo: 'https://i.namu.wiki/i/33QjyEsYBF6Z4m7gxgfWf78sfIYK-L_6hNrvTN3dkLB2WchI0eh14wMXVNCRQWt1x2I1k9htneY0-O0LCQAINKObAy2aWOKkogGJNLyvsFqrnYe6xgk4jt86osvIdwiFlvIaoBr1YrtVP1zeh8M7UA.svg' },
  { name: '11번가', url: 'https://www.11st.co.kr', logo: 'https://i.namu.wiki/i/xjI8zzER-eW_a0EaDNdIQowcJqo5LmMkCI3xM5BdXnXW4CH82tucBhUe7_VNpuB1TiTr9DXXCbCyQQ0oKgjfF3YZ1sB0q5GOh-6rPZ9CYSK3Wi5zktYp8cJrenq5y6KfXbVN-5H4bgovxbaoxOBcUA.svg' },
  { name: 'GS SHOP', url: 'https://www.gsshop.com', logo: 'https://i.namu.wiki/i/ktoWLID0PX1gvJzPyNnxwvfcNxZH3XloKF-2aduvMZHmWV7CSJYeRh0Tw7OyBWisAypSgmHCMSLT6NbTCu-veA.svg' },
  { name: '현대홈쇼핑', url: 'https://www.hyundaihmall.com', logo: 'https://i.namu.wiki/i/ZSlNntAWBo8YABzqMLs0sijw01635Lo1UEyzAEDjLNIg5r6oNGawUYtvcMSGlr_giRotENtp8kYnLNfVt7q-hwE0Tts3Cfrck5THHqwoblSgsMVcGK5eBLqqcPrIRFUpmEeJ9UPSkUb3QT-Q6y8kJA.svg' },
  { name: '옥션', url: 'https://www.auction.co.kr', logo: 'https://i.namu.wiki/i/tVHTCV3uuUdvhiS4JKLUfe2lNC1BWIlBVgGJDZFzoH_thwgTyICnEWvrnt-IwvDzqJ-upHPp5u73n42MjFszNvA2oaeAz9t-1UIhXM_Ago6a1ChoV5NxJ9EVJqVSaqykz1lTNVL3MXxIhAwg2i4c6A.svg' },
  { name: '알리익스프레스', url: 'https://www.aliexpress.com', logo: 'https://i.namu.wiki/i/4j7ygjONGgGfuRwRwFLu2d40qkb4TzqUNRpZBZxxGqojAtapBgTEttm46z0JDgPPeOxgkkEHOw0xYgjawZzEqap7snORvm3bwCVocugYASmRO5QAgd4U2n5i6GFrhXdq6VBnpnHOKQ9VLK2juHfJgA.svg' },
  { name: '다이소', url: 'https://www.daisomall.co.kr', logo: 'https://i.namu.wiki/i/9oJp29N9a7cpOqg2FH9oUBeW0MIvbTb7v5zFvqz2JnLRGTYlUAsHty-dE3u-U1uB373tgIYWT-DdrDtmYkTK9KcjeZUoFtIaSzQ1Vgro17f7xm7ztQtCd4vQt0x78d_RUq5qnMvj76H5PKBULQpkfg.svg' },
  { name: '롯데홈쇼핑', url: 'https://www.lotteimall.com', logo: 'https://i.namu.wiki/i/FR2bJvpuJ5hNArBUEMd_e_l60_cV5oZ2L6A1EnSiJ0yDHqbBnLpYCT9owlt7_CBtnzTyo-jxoBMDCqyHrb5pdNVgScOUvLY_O0B347YVjnNEmoReM3ssiCXVLWXGSrRd-65hnkeTld3IW_Rb_hcSxw.svg' },
  { name: '인터파크', url: 'https://www.interpark.com', logo: 'https://i.namu.wiki/i/8zvt-nlwv0pWp7WM9PTT9NwwzpzWZOPor3IcowiZngH6ztaUL52dGYiVER9Vb5PL7dR6nEKRBLfq94M5lgHHIQ.svg' },
  { name: '다나와', url: 'https://www.danawa.com', logo: 'https://i.namu.wiki/i/8dLph4WnSlmDa0JGXGbhKCkcCnOQQU7wWx68VrItCNtieDwliZG2WQAktTPLhElo24R2qYo5nmkJgzrMmwjeaIOwXR8t1RRDeNL82n_wu051mWNIfEQT5wGU-zhlsg_CPwjw25useujW2UOqt25QMw.svg' },
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
          <span className="text-base font-mono uppercase tracking-widest text-neutral-400 block mb-6">Compare across</span>
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
