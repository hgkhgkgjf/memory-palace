import React from 'react';
import { motion } from 'framer-motion';

const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';

const getPrefersReducedMotion = () => {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false;
  }
  return window.matchMedia(REDUCED_MOTION_QUERY).matches;
};

const FluidBackground = ({ reducedEffects = false }) => {
  const [prefersReducedMotion, setPrefersReducedMotion] = React.useState(getPrefersReducedMotion);

  React.useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return undefined;
    }

    const mediaQuery = window.matchMedia(REDUCED_MOTION_QUERY);
    const handleChange = (event) => {
      setPrefersReducedMotion(event.matches);
    };

    setPrefersReducedMotion(mediaQuery.matches);
    if (typeof mediaQuery.addEventListener === 'function') {
      mediaQuery.addEventListener('change', handleChange);
      return () => mediaQuery.removeEventListener('change', handleChange);
    }

    if (typeof mediaQuery.addListener === 'function') {
      mediaQuery.addListener(handleChange);
      return () => mediaQuery.removeListener(handleChange);
    }

    return undefined;
  }, []);

  const shouldReduce = reducedEffects || prefersReducedMotion;
  if (shouldReduce) {
    return (
      <div
        className="fixed inset-0 -z-10 overflow-hidden bg-[#fdfbf7]"
        data-testid="fluid-background-static"
      >
        <div className="absolute inset-0 bg-gradient-to-br from-[#fdfbf7] via-[#f7f2ea] to-[#efe5d6] opacity-90" />
        <div className="absolute inset-x-[-8%] top-[-10%] h-[32vh] rounded-[50%] bg-[#d4af37]/6 blur-[24px]" />
        <div className="absolute bottom-[8%] right-[8%] h-[20rem] w-[20rem] rounded-full bg-[#e6dccf]/40 blur-[20px]" />
        <div
          className="absolute inset-0 opacity-[0.02]"
          style={{
            backgroundImage:
              'linear-gradient(#d4af37 1px, transparent 1px), linear-gradient(90deg, #d4af37 1px, transparent 1px)',
            backgroundSize: '44px 44px',
          }}
        />
      </div>
    );
  }

  return (
    <div className="fixed inset-0 -z-10 overflow-hidden bg-[#fdfbf7]" data-testid="fluid-background-animated">
      {/* Base Gradient Layer - Static for performance */}
      <div className="absolute inset-0 bg-gradient-to-br from-[#fdfbf7] via-[#f7f2ea] to-[#efe5d6] opacity-80" />

      {/* Animated Blobs - Optimized: Reduced count and complexity */}
      <motion.div
        className="absolute -top-[10%] -left-[10%] w-[40vw] h-[40vw] rounded-full bg-[#d4af37]/10 blur-[80px]"
        animate={{
          x: [0, 50, 0],
          y: [0, 30, 0],
          scale: [1, 1.1, 1],
        }}
        transition={{
          duration: 25, // Slower for less CPU usage
          repeat: Infinity,
          ease: "easeInOut"
        }}
        style={{ willChange: "transform" }} // Hardware acceleration hint
      />

      <motion.div
        className="absolute top-[30%] right-[10%] w-[35vw] h-[35vw] rounded-full bg-[#e6dccf]/30 blur-[60px]"
        animate={{
          x: [0, -40, 0],
          y: [0, 50, 0],
          scale: [1, 1.05, 1],
        }}
        transition={{
          duration: 30,
          repeat: Infinity,
          ease: "easeInOut",
          delay: 2
        }}
        style={{ willChange: "transform" }}
      />

       {/* Subtle Grid Overlay - Static */}
       <div
        className="absolute inset-0 opacity-[0.03]"
        style={{
            backgroundImage: `linear-gradient(#d4af37 1px, transparent 1px), linear-gradient(90deg, #d4af37 1px, transparent 1px)`,
            backgroundSize: '40px 40px'
        }}
       />
    </div>
  );
};

export default FluidBackground;
