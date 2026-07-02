import { createContext, useContext, useState, useCallback } from 'react';
import type { ReactNode } from 'react';
import { C, MONO } from '../theme';

export interface TipLine { label: string; val: string; color?: string }
export interface TipData { x: number; y: number; title: string; lines: TipLine[]; foot?: string }

interface TipApi {
  tip: TipData | null;
  setTip: (t: TipData) => void;
  moveTip: (x: number, y: number) => void;
  clearTip: () => void;
}

const TipCtx = createContext<TipApi>({
  tip: null, setTip: () => {}, moveTip: () => {}, clearTip: () => {},
});

export const useTip = () => useContext(TipCtx);

export function TipProvider({ children }: { children: ReactNode }) {
  const [tip, setTipState] = useState<TipData | null>(null);
  const setTip = useCallback((t: TipData) => setTipState(t), []);
  const moveTip = useCallback(
    (x: number, y: number) => setTipState(t => (t ? { ...t, x, y } : t)), []);
  const clearTip = useCallback(() => setTipState(null), []);
  return (
    <TipCtx.Provider value={{ tip, setTip, moveTip, clearTip }}>
      {children}
      {tip && <FloatingTip tip={tip} />}
    </TipCtx.Provider>
  );
}

function FloatingTip({ tip }: { tip: TipData }) {
  const w = typeof window !== 'undefined' ? window.innerWidth : 1200;
  return (
    <div style={{
      position: 'fixed', left: Math.min(tip.x + 16, w - 260), top: tip.y + 16,
      background: C.chrome, border: `1px solid ${C.borderHi}`, borderRadius: 9,
      padding: '10px 13px', pointerEvents: 'none', zIndex: 9999,
      boxShadow: '0 14px 40px rgba(0,0,0,0.6)', minWidth: 160,
    }}>
      <div style={{ fontFamily: MONO, fontWeight: 700, fontSize: 12, marginBottom: 6, color: '#fff' }}>
        {tip.title}
      </div>
      {tip.lines.map((ln, i) => (
        <div key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: 18, fontSize: 11, lineHeight: 1.7 }}>
          <span style={{ color: C.mid }}>{ln.label}</span>
          <span style={{ fontFamily: MONO, fontWeight: 600, color: ln.color ?? '#fff' }}>{ln.val}</span>
        </div>
      ))}
      {tip.foot && (
        <div style={{ fontSize: 10, color: C.dim3, marginTop: 6, maxWidth: 220, lineHeight: 1.45 }}>
          {tip.foot}
        </div>
      )}
    </div>
  );
}
