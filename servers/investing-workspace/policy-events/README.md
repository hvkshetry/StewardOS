# Policy Events MCP Server

A simplified Model Context Protocol (MCP) server that provides unfiltered access to U.S. government policy data for LLM analysis. This server follows a "sieve" approach where the LLM decides relevance rather than using pre-configured filters.

## Architecture

This server implements a two-stage pattern:
1. **Bulk Retrieval**: Tools return ALL data without filtering
2. **Detail Retrieval**: After LLM analysis, fetch full details for relevant items

### Key Design Principles
- **No Pre-filtering**: Returns all data to let the LLM decide relevance
- **Fail Loudly**: No mock data - investment decisions require real data
- **Simple & Direct**: Minimal code, maximum transparency
- **LLM-Driven**: The LLM performs all filtering and relevance decisions

## Available Tools

### Bulk Retrieval Tools (Stage 1)

#### `get_recent_bills`
Returns all recent congressional bills without filtering.
- **Parameters**:
  - `days_back`: Number of days to look back (default: 30)
  - `limit`: Maximum results to return (default: 200)
- **Returns**: Minimal metadata including bill_id, title, sponsor, latest_action, action_date, url

#### `get_federal_rules`
Returns all Federal Register documents in date range without filtering.
- **Parameters**:
  - `days_back`: Days to look back (default: 30)
  - `days_ahead`: Days to look ahead (default: 30)
  - `limit`: Maximum results (default: 200)
- **Returns**: Minimal metadata including document_number, title, agency, rule_type, publication_date, fr_url

#### `get_upcoming_hearings`
Returns all congressional hearings without filtering.
- **Parameters**:
  - `days_ahead`: Days to look ahead (default: 30)
  - `limit`: Maximum results (default: 100)
- **Returns**: Minimal metadata including event_id, chamber, title, committee, date, url

### Detail Retrieval Tools (Stage 2)

#### `get_bill_details`
Fetches full details for specific bills identified by the LLM.
- **Parameters**:
  - `bill_ids`: List of bill IDs (e.g., ['HR-1234', 'S-567'])
- **Returns**: Full details including summary, sponsors, committees, actions, text versions

#### `get_rule_details`
Fetches full details for specific Federal Register documents.
- **Parameters**:
  - `document_numbers`: List of Federal Register document numbers
- **Returns**: Full details including summary, effective dates, comment deadlines, PDF/text links

#### `get_hearing_details`
Fetches full details for specific hearings.
- **Parameters**:
  - `event_ids`: List of hearing event IDs
- **Returns**: Full details including witness lists, documents, committee information

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/policy-events-mcp-server.git
cd policy-events-mcp-server
```

2. Install dependencies:
```bash
pip install fastmcp httpx python-dotenv
```

3. Set up API keys in `.env`:
```bash
CONGRESS_API_KEY=your_congress_api_key
GOVINFO_API_KEY=your_govinfo_api_key
# Optional reliability tuning
POLICY_EVENTS_HTTP_TIMEOUT_SEC=30
POLICY_EVENTS_MAX_RETRIES=3
```

## Configuration

Add to your Claude Desktop or MCP client configuration:

```json
{
  "mcpServers": {
    "policy-events": {
      "command": "python",
      "args": ["path/to/policy-events-mcp-server/server.py"],
      "env": {
        "CONGRESS_API_KEY": "your_congress_api_key",
        "GOVINFO_API_KEY": "your_govinfo_api_key"
      }
    }
  }
}
```

## API Keys

- **Congress.gov API**: [Sign up here](https://api.congress.gov/sign-up/)
- **GovInfo API**: [Sign up here](https://www.govinfo.gov/api-signup)

## Usage Example

```python
# Stage 1: Get all recent bills (no filtering)
bills = await get_recent_bills(days_back=7, max_results=100)
# Returns 100 bills from last 7 days

# LLM analyzes bills and identifies relevant ones
relevant_bill_ids = ["HR-1234", "S-567"]  # LLM selected these

# Stage 2: Get full details for relevant bills
details = await get_bill_details(bill_ids=relevant_bill_ids)
# Returns complete information for analysis
```

## File Structure

```
policy-events-mcp-server/
├── server.py           # Main MCP server with 6 tools
├── congress_bulk.py    # Congress.gov API client (bills, hearings)
├── govinfo_bulk.py     # GovInfo API client (Federal Register)
└── README.md          # This file
```

## Design Rationale

Previous versions used aggressive pre-filtering that rejected ~90% of data before the LLM could analyze it. This prevented the system from identifying potentially relevant policy developments.

The new "sieve" approach:
1. Retrieves ALL data within date ranges
2. Lets the LLM analyze and identify relevant items
3. Fetches detailed information only for LLM-selected items

This ensures no relevant policy developments are missed due to rigid pre-filtering.

## Requirements

- Python 3.10+
- fastmcp
- httpx
- Valid API keys for Congress.gov and GovInfo

## License

MIT

## Support

For issues or questions, please open an issue on GitHub.
