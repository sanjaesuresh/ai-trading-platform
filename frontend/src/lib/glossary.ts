/**
 * Plain-English glossary for the jargon this platform throws at people. One
 * sentence each, written for someone who is not a quant. Where a rule of thumb
 * helps ("above 1 is decent"), it is included. This is the single source the
 * InfoTip markers read from, so a definition is written once and reused on every
 * page. Keep definitions honest and non-promotional — nothing here should imply
 * a strategy makes money.
 */
export interface GlossaryEntry {
  /** The human term, used in the tooltip heading and aria label. */
  term: string
  /** One plain-English sentence (or two). No code, no jargon-defining-jargon. */
  definition: string
}

export const GLOSSARY = {
  // --- core concepts ---
  backtest: {
    term: 'Backtest',
    definition:
      'Replaying a trading strategy on old price data to see how it would have done — including fees and slippage. It is a simulation, not a prediction.',
  },
  paper_trading: {
    term: 'Paper trading',
    definition:
      'Running a strategy forward in real time on a practice account with fake money, so you can watch it without risking anything.',
  },
  strategy: {
    term: 'Strategy',
    definition:
      'A fixed set of rules that decides when to buy and sell. The platform follows the rules exactly — there is no human judgment in the loop.',
  },
  fees: {
    term: 'Fees',
    definition:
      'The commission charged on every trade, in basis points (1 bp = 0.01%). Charged on both the buy and the sell.',
  },
  slippage: {
    term: 'Slippage',
    definition:
      'The gap between the price you expected and the price you actually got. Real trades rarely fill at the exact quoted price.',
  },
  // --- return / risk metrics ---
  total_return: {
    term: 'Total return',
    definition:
      'How much the account grew or shrank over the whole period, as a percentage, after costs.',
  },
  annualized_return: {
    term: 'Annualized return (CAGR)',
    definition:
      'The total return rescaled to a per-year rate, so periods of different lengths can be compared fairly.',
  },
  sharpe_ratio: {
    term: 'Sharpe ratio',
    definition:
      'Return earned per unit of overall ups-and-downs. Higher means a steadier ride for the same gain. Above 1 is generally considered decent.',
  },
  sortino_ratio: {
    term: 'Sortino ratio',
    definition:
      'Like the Sharpe ratio, but it only counts the downside wobble — it does not penalize a strategy for jumping up.',
  },
  max_drawdown: {
    term: 'Max drawdown',
    definition:
      'The worst peak-to-bottom drop the account suffered along the way. It tells you how painful the lowest point was.',
  },
  volatility: {
    term: 'Volatility',
    definition:
      'How much the value bounces around day to day. More volatility means a bumpier ride.',
  },
  win_rate: {
    term: 'Win rate',
    definition:
      'The share of completed trades that ended in profit. On its own it can mislead — a few big losses can sink a high win rate.',
  },
  profit_factor: {
    term: 'Profit factor',
    definition:
      'Total money made on winners divided by total lost on losers. Above 1 means winners outweighed losers overall.',
  },
  exposure: {
    term: 'Exposure',
    definition:
      'The share of time the strategy actually held a position, rather than sitting in cash.',
  },
  round_trip: {
    term: 'Round trip',
    definition:
      'One complete trade: a buy paired with the sell that closed it. Win/loss stats are measured per round trip, not per individual order.',
  },
  // --- sizing / risk controls ---
  vol_targeting: {
    term: 'Volatility targeting',
    definition:
      'Sizing each position so the portfolio aims for a steady level of risk — smaller bets when the market is wild, bigger when it is calm.',
  },
  stop_loss: {
    term: 'Stop loss',
    definition:
      'An automatic exit that sells if a position falls a set amount, to cap the loss on any single trade.',
  },
  take_profit: {
    term: 'Take profit',
    definition:
      'An automatic exit that sells once a position reaches a set gain target, closing the trade there rather than letting it run further.',
  },
  drawdown_kill: {
    term: 'Drawdown kill-switch',
    definition:
      'A safety limit: if the account falls past a set drawdown, everything is sold and trading halts.',
  },
  position_cap: {
    term: 'Position cap',
    definition:
      'The most of the account that may be put into a single holding at once.',
  },
  // --- evaluation rigor ---
  parameter_sweep: {
    term: 'Parameter sweep',
    definition:
      'Trying many settings for a strategy to see which did best. Tempting, but the more you try, the easier it is to get lucky by accident.',
  },
  walk_forward: {
    term: 'Walk-forward test',
    definition:
      'Tuning a strategy on an early stretch of history, then testing it on the next, unseen stretch — repeatedly. It mimics making decisions without knowing the future.',
  },
  out_of_sample: {
    term: 'Out-of-sample',
    definition:
      'Data the strategy was NOT tuned on. Results here are the honest test; results on tuned data always look better than reality.',
  },
  in_sample_gap: {
    term: 'In-sample vs out-of-sample gap',
    definition:
      'How much worse the strategy did on unseen data than on the data it was tuned on. A big gap is a warning sign of overfitting.',
  },
  overfitting: {
    term: 'Overfitting',
    definition:
      'When a strategy is tuned so tightly to past data that it memorized noise instead of a real pattern — so it falls apart on new data.',
  },
  baseline: {
    term: 'Baseline',
    definition:
      'The simple benchmark a strategy must beat (after costs) to be worth anything. Beating nothing is easy; beating the baseline is the bar.',
  },
  objective: {
    term: 'Objective',
    definition:
      'The single number an evaluation is trying to maximize — for example the Sharpe ratio — when it compares settings.',
  },
  deflated_sharpe: {
    term: 'Deflated Sharpe',
    definition:
      'A Sharpe ratio adjusted downward for how many strategies were tried, since testing many makes a good-looking one likely by chance.',
  },
  pbo: {
    term: 'Probability of backtest overfitting (PBO)',
    definition:
      'An estimate of how likely the best-looking setting is to be a fluke that underperforms out-of-sample. Lower is better.',
  },
  monte_carlo: {
    term: 'Monte-Carlo percentile',
    definition:
      'Where the real result lands against thousands of shuffled, luck-only runs. A high percentile means the result is hard to explain by luck alone.',
  },
  significance: {
    term: 'Statistical significance',
    definition:
      'Whether a result is strong enough that it probably is not just random chance, given how little data there is.',
  },
  verdict: {
    term: 'Verdict',
    definition:
      'The evaluation’s honest call: pass, fail, or inconclusive. With daily data and short histories, inconclusive is the expected, normal outcome.',
  },
  // --- ML ---
  calibration: {
    term: 'Calibration',
    definition:
      'Whether the model’s confidence is trustworthy — when it says "70% chance", does that happen about 70% of the time?',
  },
  deadband: {
    term: 'Deadband',
    definition:
      'A neutral zone around the decision threshold where the model stays out of the market rather than trade on a weak, uncertain signal.',
  },
  threshold: {
    term: 'Threshold',
    definition:
      'The confidence level the model must clear before it enters (or exits) a trade.',
  },
  horizon: {
    term: 'Horizon',
    definition:
      'How far ahead the model is trying to predict — for example, the direction of the next day’s move.',
  },
  feature_spec: {
    term: 'Feature spec',
    definition:
      'The exact list of inputs (and their version) the model is allowed to learn from. Pinning it prevents accidental future-peeking.',
  },
  // --- data / paper plumbing ---
  ingestion: {
    term: 'Ingestion',
    definition:
      'Fetching price history from a data provider and saving it, after quality checks, so strategies have something to run on.',
  },
  backfill: {
    term: 'Backfill',
    definition:
      'Pulling a long stretch of past history all at once, versus an incremental update that just adds the latest days.',
  },
  position: {
    term: 'Position',
    definition:
      'A holding the strategy currently owns — the symbol, how many shares, and what it is worth now.',
  },
  order: {
    term: 'Order',
    definition:
      'An instruction to buy or sell that has been submitted but may not have filled yet.',
  },
  fill: {
    term: 'Fill',
    definition:
      'An order that actually executed, at a specific price and quantity.',
  },
  reconciliation: {
    term: 'Reconciliation',
    definition:
      'A check that the platform’s view of the account matches the broker’s, so the two never silently drift apart.',
  },
  kill_switch: {
    term: 'Kill-switch',
    definition:
      'A manual stop that flattens positions and halts a deployment immediately, no questions asked.',
  },
  next_bar_open: {
    term: 'Next-bar-open fills',
    definition:
      'A signal from today’s close is filled at tomorrow’s opening price — never the same bar — so the test can’t cheat with information it would not have had.',
  },
} as const satisfies Record<string, GlossaryEntry>

export type GlossaryId = keyof typeof GLOSSARY
