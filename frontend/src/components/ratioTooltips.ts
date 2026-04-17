export const RATIO_TOOLTIPS: Record<string, string> = {
  "P/E":
    "Price-to-Earnings. Share price divided by EPS. Lower = cheaper vs earnings; undefined when the company is loss-making.",
  "P/B":
    "Price-to-Book. Market cap divided by shareholders' equity. Tells you what you're paying per $1 of book value; asset-heavy businesses are more meaningful here.",
  "EV/EBITDA":
    "Enterprise Value over EBITDA. Capital-structure-neutral valuation; useful when P/E is distorted by leverage or non-cash items.",
  "P/FCF":
    "Price-to-Free-Cash-Flow. Cash-basis valuation. Better than P/E for capital-intensive or working-capital-heavy businesses.",
  "P/Sales":
    "Market cap divided by revenue. Used when earnings are volatile or negative; highly sensitive to gross-margin profile.",
  "Gross Margin":
    "Revenue minus cost of goods sold, as % of revenue. Measures pricing power and product economics before operating overhead.",
  "Op. Margin":
    "Operating income as % of revenue. Profitability after operating costs but before interest and tax — the core business's efficiency.",
  "Net Margin":
    "Net income as % of revenue. The bottom-line cut after every expense; influenced by leverage and one-time items.",
  "EBITDA Margin":
    "EBITDA as % of revenue. Strips out depreciation and amortization to compare operating profitability across differing capex profiles.",
  "FCF Margin":
    "GAAP free cash flow as % of revenue. Includes SBC add-back, so inflated for stock-heavy compensation.",
  "FCF Margin ex-SBC":
    "Free cash flow after subtracting stock-based comp, as % of revenue. Strips out the non-cash add-back to show cash truly available to shareholders.",
  "SBC / Revenue":
    "Stock-based compensation as % of revenue. Above ~5% indicates material shareholder dilution is financing payroll.",
  "ROE":
    "Return on Equity. Net income divided by shareholders' equity — how efficiently equity capital compounds.",
  "ROA":
    "Return on Assets. Net income divided by total assets. Signals capital efficiency regardless of funding mix.",
  "ROIC":
    "Return on Invested Capital. NOPAT over (equity + debt − cash). Must clear cost of capital to create value.",
  "Debt / Equity":
    "Total debt divided by equity. Leverage gauge; higher means more financial risk in a downturn.",
  "Debt+Leases / Equity":
    "D/E with operating lease liabilities added back in. Truer leverage picture for lease-heavy businesses (retail, airlines).",
  "Cash / Debt":
    "Cash and equivalents divided by total debt. Liquidity cushion — >1 means cash alone covers debt.",
  "Interest Coverage":
    "Operating income divided by interest paid. How many times over the company can service its debt from operations.",
  "OCF / NI":
    "Operating cash flow divided by net income. Persistently below 1 can signal earnings quality issues.",
  "Revenue Growth":
    "Year-over-year change in revenue. Primary top-line growth gauge.",
  "EPS Growth":
    "Year-over-year change in diluted EPS. Can be inflated by buybacks even when net income is flat.",
  "FCF Growth":
    "Year-over-year change in free cash flow. A cleaner growth signal than EPS for cash-generative businesses.",
  "Net Dilution / Revenue":
    "SBC minus buybacks, as % of revenue. Positive = shareholders being net-diluted; negative = company is out-repurchasing comp.",
};

export function tooltipFor(label: string): string | undefined {
  return RATIO_TOOLTIPS[label];
}
