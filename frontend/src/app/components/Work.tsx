import { motion } from 'motion/react';
import { Link } from 'react-router-dom';
import { projects } from '../data/projects'; // Import data

export const Work = () => {
  return (
    <div className="bg-white min-h-screen text-neutral-950 pt-32 px-6">
      <div className="container mx-auto">
        <div className="flex justify-between items-end mb-24">
           <div>
             <Link to="/" className="text-xs font-mono uppercase tracking-widest text-neutral-500 hover:text-neutral-950 transition-colors mb-8 block">
               ← Back to Home
             </Link>
             <h1 className="text-6xl md:text-9xl font-medium tracking-tighter leading-[0.9]">
               What we Curate
             </h1>
           </div>
        </div>

        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8 gap-y-16 pb-32">
          {projects.map((project, index) => (
            <motion.div 
              key={project.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.1 }}
              className="group"
            >
              <div className="relative overflow-hidden aspect-[3/4] mb-6 bg-neutral-100 rounded-sm">
                 <img
                   src={project.image}
                   alt={project.title}
                   className="object-cover w-full h-full opacity-80 group-hover:scale-105 group-hover:opacity-100 transition-all duration-700"
                 />
                 <div className="absolute inset-0 bg-black/20 group-hover:bg-transparent transition-colors" />
              </div>
              <div className="border-t border-black/10 pt-4">
                 <h3 className="text-xl font-medium tracking-tight mb-1">{project.title}</h3>
                 <p className="text-xs font-mono uppercase tracking-widest text-neutral-500">{project.category}</p>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  );
};
