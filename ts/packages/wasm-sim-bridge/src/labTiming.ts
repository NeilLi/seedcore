/** Soft real-time pacing only. Physics time advances by integer ticks. */
export class FixedTickClock {
  readonly total: number;
  private last: number;
  constructor(readonly hz: 500|1000, readonly seconds: number, readonly start: number) {
    if(![500,1000].includes(hz)||!Number.isInteger(seconds)||seconds<2||seconds>30||!Number.isFinite(start)) throw new Error('Invalid fixed clock');
    this.total=hz*seconds;this.last=start;
  }
  due(now: number, tick: number): number {
    if(!Number.isFinite(now)||now<this.last||!Number.isInteger(tick)||tick<0||tick>this.total) throw new Error('Invalid clock/tick');
    if(now-this.last>250 || now-this.start-tick*1000/this.hz>250) throw new Error('Simulation pacing stalled beyond 250 ms; restart required');
    this.last=now;
    return Math.min(8,Math.max(0,Math.min(this.total,Math.floor((now-this.start)*this.hz/1000))-tick));
  }
}
export function percentile(values: readonly number[], p: number): number | null {
  if(!values.length) return null;
  const sorted=[...values].sort((a,b)=>a-b); return sorted[Math.min(sorted.length-1,Math.floor(p*(sorted.length-1)))];
}
