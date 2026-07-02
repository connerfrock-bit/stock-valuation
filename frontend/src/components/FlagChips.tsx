import { C, MONO, hexA, DISTRESS_RE } from '../theme';

export function FlagChip({ flag }: { flag: string }) {
  const distress = DISTRESS_RE.test(flag);
  const col = distress ? C.red : C.amber;
  return (
    <span style={{
      fontSize: 9, fontWeight: 600, color: col,
      background: hexA(col, distress ? 0.12 : 0.13),
      border: `1px solid ${hexA(col, 0.3)}`,
      borderRadius: 3, padding: '1px 5px', whiteSpace: 'nowrap',
    }}>
      {flag}
    </span>
  );
}

/** Table cell variant — truncates to `max` chips + "+N". */
export function FlagChips({ flags, max = 2 }: { flags: string[]; max?: number }) {
  if (!flags.length) {
    return <span style={{ color: C.dim, fontFamily: MONO }}>—</span>;
  }
  const shown = flags.slice(0, max);
  return (
    <span style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }}>
      {shown.map(f => (
        <FlagChip key={f} flag={f.length > 16 ? f.slice(0, 15) + '…' : f} />
      ))}
      {flags.length > max && (
        <span style={{ fontSize: 9, color: C.dim }}>+{flags.length - max}</span>
      )}
    </span>
  );
}
