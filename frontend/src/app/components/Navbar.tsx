import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Menu, X } from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';
import { useSearch } from '../context/SearchContext';

export const Navbar = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const location = useLocation();
  const { status } = useSearch();
  // 검색/대화가 한 번이라도 시작되면(idle이 아니면) 네비게이션 링크를 치운다 —
  // 결과 화면에 집중하도록. 리셋하면 status가 다시 idle로 돌아가 자동으로 복원된다.
  const conversationStarted = status !== 'idle';

  useEffect(() => {
    const handleScroll = () => {
      setScrolled(window.scrollY > 50);
    };
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  // Close mobile menu on route change
  useEffect(() => {
    setIsOpen(false);
  }, [location]);

  const navItems = [
    { name: 'Work', to: '/work' },
    { name: 'About', to: '/#about' },
    { name: 'Services', to: '/#services' },
    { name: 'Contact', to: 'mailto:parkminsung45@icloud.com' }
  ];

  return (
    <motion.nav
      initial={{ y: -100 }}
      animate={{ y: 0 }}
      className={`fixed w-full z-50 transition-all duration-300 ${
        scrolled ? 'bg-transparent py-4 border-b border-black/5' : 'py-8 bg-transparent'
      }`}
    >
      <div className="container mx-auto px-6 flex justify-end items-center">
        {!conversationStarted && (
          <>
            {/* Desktop Menu */}
            <div className="hidden md:flex gap-8">
              {navItems.map((item, i) => (
                <motion.div
                  key={item.name}
                  initial={{ opacity: 0, y: -20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.5, delay: i * 0.1 }}
                >
                  {item.to.startsWith('mailto:') ? (
                    <a
                      href={item.to}
                      className="text-sm uppercase tracking-widest hover:text-black/70 transition-colors relative group"
                    >
                      {item.name}
                      <span className="absolute -bottom-1 left-0 w-0 h-px bg-black transition-all group-hover:w-full" />
                    </a>
                  ) : (
                    <Link
                      to={item.to}
                      className="text-sm uppercase tracking-widest hover:text-black/70 transition-colors relative group"
                    >
                      {item.name}
                      <span className="absolute -bottom-1 left-0 w-0 h-px bg-black transition-all group-hover:w-full" />
                    </Link>
                  )}
                </motion.div>
              ))}
            </div>

            {/* Mobile Toggle */}
            <button
              onClick={() => setIsOpen(!isOpen)}
              className="md:hidden z-50 text-neutral-950"
            >
              {isOpen ? <X /> : <Menu />}
            </button>
          </>
        )}

        {/* Mobile Menu */}
        <AnimatePresence>
          {isOpen && !conversationStarted && (
            <motion.div
              initial={{ opacity: 0, x: '100%' }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: '100%' }}
              transition={{ type: "tween", duration: 0.4 }}
              className="fixed inset-0 bg-white flex flex-col items-center justify-center gap-12 md:hidden"
            >
              {navItems.map((item) =>
                item.to.startsWith('mailto:') ? (
                  <a
                    key={item.name}
                    href={item.to}
                    className="text-4xl font-medium tracking-tight hover:text-neutral-500 transition-colors"
                  >
                    {item.name}
                  </a>
                ) : (
                  <Link
                    key={item.name}
                    to={item.to}
                    className="text-4xl font-medium tracking-tight hover:text-neutral-500 transition-colors"
                  >
                    {item.name}
                  </Link>
                )
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.nav>
  );
};
