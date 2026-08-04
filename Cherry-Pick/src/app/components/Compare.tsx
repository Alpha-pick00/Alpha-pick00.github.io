import React, { useState } from 'react';
import { motion } from 'motion/react';
import { Search, Loader2, ExternalLink } from 'lucide-react';

interface Product {
  id: string;
  title: string;
  link: string;
  image: string;
  price: number;
  mallName: string;
  brand: string | null;
  category: string;
}

export const Compare = () => {
  const [query, setQuery] = useState('');
  const [items, setItems] = useState<Product[]>([]);
  const [status, setStatus] = useState<'idle' | 'loading' | 'error' | 'done'>('idle');
  const [error, setError] = useState('');

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) return;

    setStatus('loading');
    setError('');

    try {
      const res = await fetch(`/api/search?query=${encodeURIComponent(trimmed)}`);
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || 'Search failed');
      }
      setItems(data.items);
      setStatus('done');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong');
      setStatus('error');
    }
  };

  return (
    <div className="bg-white min-h-screen text-neutral-950 pt-32 px-6 pb-32">
      <div className="container mx-auto max-w-5xl">
        <span className="text-xs font-mono uppercase tracking-widest text-neutral-500 block mb-4">Compare</span>
        <h1 className="text-5xl md:text-7xl font-medium tracking-tighter leading-[0.95] mb-12">
          Find the <span style={{ color: '#EC4899' }}>lowest price</span>.
        </h1>

        <form onSubmit={handleSearch} className="flex gap-3 mb-16">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="상품명을 검색하세요 (예: 에어팟 프로)"
            className="flex-1 bg-transparent border-b border-black/20 py-4 text-xl font-light focus:outline-none focus:border-black transition-colors placeholder:text-neutral-400"
          />
          <button
            type="submit"
            disabled={status === 'loading'}
            className="shrink-0 w-14 h-14 rounded-full bg-neutral-950 text-white flex items-center justify-center hover:scale-105 transition-transform disabled:opacity-50"
          >
            {status === 'loading' ? <Loader2 className="w-5 h-5 animate-spin" /> : <Search className="w-5 h-5" />}
          </button>
        </form>

        {status === 'error' && <p className="text-neutral-500 mb-12">{error}</p>}

        {status === 'done' && items.length === 0 && (
          <p className="text-neutral-500 mb-12">검색 결과가 없습니다.</p>
        )}

        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8">
          {items.map((item) => (
            <motion.a
              key={item.id}
              href={item.link}
              target="_blank"
              rel="noopener noreferrer"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="group border border-black/10 rounded-sm overflow-hidden hover:border-black/30 transition-colors"
            >
              <div className="aspect-square bg-neutral-100 overflow-hidden">
                <img
                  src={item.image}
                  alt={item.title}
                  className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
                />
              </div>
              <div className="p-4">
                <p className="text-sm font-light line-clamp-2 mb-2">{item.title}</p>
                <div className="flex items-center justify-between">
                  <span className="text-lg font-medium">{item.price.toLocaleString('ko-KR')}원</span>
                  <span className="text-xs text-neutral-500 flex items-center gap-1">
                    {item.mallName}
                    <ExternalLink className="w-3 h-3" />
                  </span>
                </div>
              </div>
            </motion.a>
          ))}
        </div>
      </div>
    </div>
  );
};
