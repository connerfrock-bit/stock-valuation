import { hexA, sectorColor } from '../theme';

export function SectorTag({ sector, label, size = 9.5 }:
  { sector: string; label: string; size?: number }) {
  const col = sectorColor(sector);
  return (
    <span style={{
      fontSize: size, fontWeight: 600, letterSpacing: '.03em', color: col,
      background: hexA(col, 0.13), border: `1px solid ${hexA(col, 0.33)}`,
      borderRadius: 3, padding: '1px 5px', whiteSpace: 'nowrap',
    }}>
      {label}
    </span>
  );
}
