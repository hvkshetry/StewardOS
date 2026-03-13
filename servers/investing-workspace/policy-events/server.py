"""
Policy Events MCP Server - Simplified LLM-Driven Architecture
Provides unfiltered government data for LLM analysis.
"""
import logging
from typing import List, Dict, Any
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field

# Import our simple bulk clients
from congress_bulk import CongressBulkClient
from govinfo_bulk import GovInfoBulkClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP("policy-events-service")

@mcp.tool()
async def get_recent_bills(
    days_back: int = Field(30, description="Number of days to look back"),
    limit: int = Field(200, description="Maximum number of results to return")
) -> List[Dict[str, Any]]:
    """
    Get all recent congressional bills without filtering.
    Returns minimal metadata for LLM to analyze and identify relevant ones.

    Returns:
    - bill_id: Bill identifier (e.g., "HR-1234")
    - title: Bill title
    - sponsor: Bill sponsor name
    - latest_action: Most recent action taken
    - action_date: Date of latest action
    - url: Link to bill on Congress.gov
    """
    try:
        async with CongressBulkClient() as congress_client:
            bills = await congress_client.get_recent_bills(days_back, limit)
            logger.info(f"Returning {len(bills)} bills to LLM for analysis")
            return bills
    except ValueError as e:
        raise ToolError(str(e))


@mcp.tool()
async def get_federal_rules(
    days_back: int = Field(30, description="Days to look back"),
    days_ahead: int = Field(30, description="Days to look ahead"),
    limit: int = Field(200, description="Maximum number of results")
) -> List[Dict[str, Any]]:
    """
    Get all Federal Register documents in date range without filtering.
    Returns minimal metadata for LLM to analyze and identify relevant ones.

    Returns:
    - document_number: Federal Register document number
    - title: Document title
    - agency: Issuing agency
    - rule_type: Type (Proposed Rule, Final Rule, Notice, etc.)
    - publication_date: Date published
    - fr_url: Link to document on FederalRegister.gov
    """
    try:
        async with GovInfoBulkClient() as govinfo_client:
            rules = await govinfo_client.get_federal_rules(days_back, days_ahead, limit)
            logger.info(f"Returning {len(rules)} Federal Register documents to LLM for analysis")
            return rules
    except ValueError as e:
        raise ToolError(str(e))


@mcp.tool()
async def get_upcoming_hearings(
    days_ahead: int = Field(30, description="Days to look ahead"),
    limit: int = Field(100, description="Maximum number of results")
) -> List[Dict[str, Any]]:
    """
    Get all congressional hearings without filtering.
    Returns minimal metadata for LLM to analyze and identify relevant ones.

    Returns:
    - event_id: Hearing event ID
    - chamber: House or Senate
    - title: Hearing title
    - committee: Committee name
    - date: Hearing date
    - url: Link to hearing on Congress.gov
    """
    try:
        async with CongressBulkClient() as congress_client:
            hearings = await congress_client.get_upcoming_hearings(days_ahead, limit)
            logger.info(f"Returning {len(hearings)} hearings to LLM for analysis")
            return hearings
    except ValueError as e:
        raise ToolError(str(e))


@mcp.tool()
async def get_bill_details(
    bill_ids: List[str] = Field(..., description="List of bill IDs to get details for (e.g., ['HR-1234', 'S-567'])")
) -> List[Dict[str, Any]]:
    """
    Get full details for specific bills identified by the LLM.
    Use this after analyzing results from get_recent_bills.

    Returns detailed information including:
    - Full title and summary
    - Sponsor and cosponsors
    - Committee assignments
    - Recent actions
    - Text versions available
    - Direct link to Congress.gov
    """
    try:
        async with CongressBulkClient() as congress_client:
            details = await congress_client.get_bill_details(bill_ids)
            logger.info(f"Retrieved details for {len(details)} bills")
            return details
    except ValueError as e:
        raise ToolError(str(e))


@mcp.tool()
async def get_rule_details(
    document_numbers: List[str] = Field(..., description="List of Federal Register document numbers")
) -> List[Dict[str, Any]]:
    """
    Get full details for specific Federal Register documents identified by the LLM.
    Use this after analyzing results from get_federal_rules.

    Returns detailed information including:
    - Full title and summary
    - Agency and rule type
    - Effective date (for final rules)
    - Comment deadline (for proposed rules)
    - Individual documents (granules) in the package
    - Links to PDF and text versions
    """
    try:
        async with GovInfoBulkClient() as govinfo_client:
            details = await govinfo_client.get_rule_details(document_numbers)
            logger.info(f"Retrieved details for {len(details)} Federal Register documents")
            return details
    except ValueError as e:
        raise ToolError(str(e))


@mcp.tool()
async def get_hearing_details(
    event_ids: List[str] = Field(..., description="List of hearing event IDs")
) -> List[Dict[str, Any]]:
    """
    Get full details for specific hearings identified by the LLM.
    Use this after analyzing results from get_upcoming_hearings.

    Returns detailed information including:
    - Full title and type
    - Committee information
    - Complete witness list
    - Available documents
    - Direct link to Congress.gov
    """
    try:
        async with CongressBulkClient() as congress_client:
            details = await congress_client.get_hearing_details(event_ids)
            logger.info(f"Retrieved details for {len(details)} hearings")
            return details
    except ValueError as e:
        raise ToolError(str(e))


if __name__ == "__main__":
    # Run the MCP server
    mcp.run()
