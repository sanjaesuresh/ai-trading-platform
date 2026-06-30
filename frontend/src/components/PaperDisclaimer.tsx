// The strongest disclaimer treatment in the app: paper trading runs a strategy
// forward against a broker and feels "live", so every paper surface states
// plainly that it is simulated, uses Alpaca's PAPER endpoint, trades no real
// money, and is not financial advice or a promise of returns.
export function PaperDisclaimer() {
  return (
    <div
      role="note"
      aria-label="Paper trading disclaimer"
      className="bg-amber-950/40 border border-amber-900/50 rounded p-4"
    >
      <p className="text-sm text-amber-200/90 font-medium">
        Simulated paper trading — no real money.
      </p>
      <p className="text-xs text-amber-300/70 mt-1 leading-relaxed">
        Orders are placed against Alpaca&apos;s <strong>paper</strong> endpoint
        only; the live (real-money) endpoint is unreachable by design. Results are
        simulated, are <strong>not financial advice</strong>, and do not imply real
        or future returns. A strategy that looks good here will most likely still
        fail to beat a simple baseline net of costs.
      </p>
    </div>
  )
}
