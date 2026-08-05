import React, { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { ArrowUpRight, X, Send } from 'lucide-react';

export const Footer = () => {
  const [isFormOpen, setIsFormOpen] = useState(false);

  return (
    <>
      <footer className="relative bg-white py-32 px-6 overflow-hidden border-t border-black/5">
        <div className="container mx-auto">
          <div className="grid md:grid-cols-[1.5fr_1fr] gap-20 mb-32">
            
            <div>
              <motion.h2 
                initial={{ opacity: 0, y: 50 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                className="text-6xl md:text-9xl font-medium tracking-tighter leading-[0.9] mb-16"
              >
                Let's <br />
                <span style={{ color: '#4ADE80' }}>Étiquette</span>
              </motion.h2>
              
              <div className="flex flex-col gap-10">
                 <button 
                   onClick={() => setIsFormOpen(true)}
                   className="group flex items-center gap-6 text-left transition-all"
                 >
                   <div className="w-20 h-20 rounded-full bg-neutral-950 text-white flex items-center justify-center group-hover:scale-105 group-hover:bg-neutral-800 transition-all duration-500">
                     <ArrowUpRight className="w-8 h-8 group-hover:rotate-45 transition-transform duration-500" />
                   </div>
                   <div>
                     <span className="block text-4xl font-light tracking-tighter text-neutral-950 group-hover:translate-x-2 transition-transform duration-300">Start a <span style={{ color: '#4ADE80' }}>Étiquette</span></span>
                     <span className="block text-sm font-mono uppercase tracking-widest text-neutral-500 mt-1 group-hover:text-neutral-600 transition-colors">We are currently available</span>
                   </div>
                 </button>
              </div>
            </div>

            <div className="flex flex-col justify-end gap-12">
              <div>
                <h4 className="font-mono text-xs uppercase tracking-widest text-neutral-500 mb-6">Sitemap</h4>
                <ul className="space-y-4">
                  {['Home', 'Work', 'About', 'Contact'].map((link) => (
                    <li key={link}>
                      <a href={`#${link.toLowerCase()}`} className="text-lg font-light text-neutral-600 hover:text-neutral-950 transition-colors">
                        {link}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            </div>

          </div>

          <div className="flex flex-col md:flex-row justify-between items-center pt-12 border-t border-black/5 gap-6">
            <p className="font-mono text-xs uppercase tracking-widest text-neutral-400">
              © 2026 <span style={{ color: '#4ADE80' }}>Étiquette</span>.
            </p>
            <p className="font-mono text-xs uppercase tracking-widest text-neutral-400">
              All rights reserved.
            </p>
          </div>
        </div>
      </footer>

      <ContactModal isOpen={isFormOpen} onClose={() => setIsFormOpen(false)} />
    </>
  );
};

const ContactModal = ({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) => {
  const [formState, setFormState] = useState<'idle' | 'submitting' | 'success'>('idle');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setFormState('submitting');
    setTimeout(() => {
      setFormState('success');
      setTimeout(() => {
        onClose();
        setFormState('idle');
      }, 2000);
    }, 1500);
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-white/80 backdrop-blur-md z-[100]"
          />
          
          <motion.div
            initial={{ opacity: 0, x: "100%" }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: "100%" }}
            transition={{ type: "spring", damping: 30, stiffness: 300 }}
            className="fixed inset-y-0 right-0 z-[101] w-full md:w-[600px] bg-neutral-100 border-l border-black/10 shadow-2xl p-8 md:p-12 overflow-y-auto"
          >
            <button
              onClick={onClose}
              className="absolute top-8 right-8 p-2 text-neutral-500 hover:text-neutral-950 transition-colors z-10"
            >
              <X className="w-6 h-6" />
            </button>

            {formState === 'success' ? (
              <div className="h-full flex flex-col items-center justify-center text-center">
                <motion.div
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  className="w-20 h-20 bg-neutral-950 rounded-full flex items-center justify-center mb-6"
                >
                  <Send className="w-8 h-8 text-white" />
                </motion.div>
                <h3 className="text-3xl font-medium mb-2">Message Sent</h3>
                <p className="text-neutral-600 font-light">We'll be in touch shortly.</p>
              </div>
            ) : (
              <div className="mt-12">
                <span className="text-xs font-mono uppercase tracking-widest text-neutral-500 mb-6 block">04 / Contact</span>
                <h3 className="text-4xl md:text-5xl font-medium tracking-tighter mb-2">
                  Start <br />
                  <span style={{ color: '#4ADE80' }}>Étiquette</span>
                </h3>
                <p className="text-neutral-600 font-light mb-12">
                  Tell us about your vision. We'll help you build it.
                </p>

                <form onSubmit={handleSubmit} className="space-y-12">
                  <div className="space-y-8">
                    <div className="group relative">
                      <input 
                        required 
                        type="text" 
                        placeholder="Your Name"
                        className="w-full bg-transparent border-b border-black/10 py-4 text-xl font-light focus:outline-none focus:border-black transition-colors placeholder:text-neutral-300"
                      />
                    </div>
                    
                    <div className="group relative">
                      <input 
                        required 
                        type="email" 
                        placeholder="Email Address"
                        className="w-full bg-transparent border-b border-black/10 py-4 text-xl font-light focus:outline-none focus:border-black transition-colors placeholder:text-neutral-300"
                      />
                    </div>

                    <div className="group relative">
                      <textarea 
                        required 
                        placeholder="Project Details..."
                        rows={4}
                        className="w-full bg-transparent border-b border-black/10 py-4 text-xl font-light focus:outline-none focus:border-black transition-colors resize-none placeholder:text-neutral-300"
                      />
                    </div>
                  </div>

                  <div className="space-y-4">
                     <label className="text-xs font-mono uppercase tracking-widest text-neutral-500">Budget Range</label>
                     <div className="flex flex-wrap gap-3">
                        {['< 10k', '10k - 50k', '50k - 100k', '> 100k'].map(range => (
                          <button type="button" key={range} className="px-4 py-2 rounded-full border border-black/10 text-sm font-light hover:bg-neutral-950 hover:text-white transition-all">
                            {range}
                          </button>
                        ))}
                     </div>
                  </div>

                  <button 
                    type="submit"
                    disabled={formState === 'submitting'}
                    className="w-full bg-neutral-950 text-white text-lg font-medium py-4 rounded-full hover:scale-[1.02] active:scale-[0.98] transition-all flex items-center justify-center gap-2 disabled:opacity-50"
                  >
                    {formState === 'submitting' ? 'Sending...' : 'Send Message'}
                  </button>
                </form>
              </div>
            )}
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
};
