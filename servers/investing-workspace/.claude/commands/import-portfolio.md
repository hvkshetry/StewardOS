---
description: Import and validate portfolio data from broker CSV files
allowed-tools: Read, mcp__portfolio-state-server__import_broker_csv, mcp__portfolio-state-server__get_portfolio_state, Write
---

Import my portfolio positions from broker CSV files and validate the import.

## Import Process

1. **Clear Existing State**
   - Confirm portfolio state server is ready
   - Note: Server starts empty on initialization

2. **Import Vanguard Positions**
   - Read CSV from `portfolio/vanguard.csv`
   - Import using `mcp__portfolio-state-server__import_broker_csv`:
     - `broker="vanguard"`
     - `account_id="vanguard_hersh"`
   - Confirm import successful

3. **Import UBS Positions**
   - Read CSV from `portfolio/ubs.csv`
   - Import using `mcp__portfolio-state-server__import_broker_csv`:
     - `broker="ubs"`
     - `account_id="ubs_hersh"`
   - Confirm import successful

4. **Verify Portfolio State**
   - Get complete portfolio using `mcp__portfolio-state-server__get_portfolio_state`
   - Verify acceptance criteria:
     - Total value > $1,000,000
     - Position count > 40
     - All positions have valid prices
     - Tax lots are properly loaded

5. **Generate Import Summary**
   - Create `import_summary.json` with:
     - Total portfolio value
     - Number of positions
     - Number of tax lots
     - Account breakdown (Vanguard vs UBS)
     - Any import warnings or errors

## Output

Save import summary to current session directory for audit trail.

Display summary to user showing successful import with key metrics.
