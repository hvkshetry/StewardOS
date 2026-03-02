import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as sleep } from 'node:timers/promises';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, '../../../');

const PAYLOAD_PATH = process.env.INGESTION_PAYLOAD_PATH || path.resolve(__dirname, '../output/ingestion_payload.json');
const OUTPUT_PATH = process.env.INGESTION_RESULT_PATH || path.resolve(__dirname, '../output/actual_remote_reconcile_result.json');
const MCP_SERVER_CWD = process.env.ACTUAL_MCP_SERVER_CWD || path.join(REPO_ROOT, 'servers/actual-mcp');
const MCP_SERVER_ENTRY = process.env.ACTUAL_MCP_SERVER_ENTRY || path.join(REPO_ROOT, 'servers/actual-mcp/build/index.js');
const REQUIRED_SYNC_ID = process.env.ACTUAL_BUDGET_SYNC_ID || '';
const CANONICAL_BUDGET_NAME = process.env.ACTUAL_TARGET_BUDGET_NAME || 'Household Budget';
const CHUNK_SIZE = Number(process.env.INGESTION_CHUNK_SIZE || 100);
const MAX_RETRIES = Number(process.env.INGESTION_MAX_RETRIES || 5);

function isTransientError(errLike) {
  const msg = String(errLike?.message ?? errLike ?? '').toLowerCase();
  const code = String(errLike?.code ?? '').toLowerCase();
  return (
    ['timeout', 'timed_out', 'network_error', 'internal_error', 'service_unavailable', 'rate_limit'].includes(code) ||
    msg.includes('timeout') ||
    msg.includes('timed out') ||
    msg.includes('network-failure') ||
    msg.includes('econnreset') ||
    msg.includes('socket hang up') ||
    msg.includes('temporar') ||
    msg.includes('unavailable') ||
    msg.includes('429')
  );
}

function parseEnvelope(result) {
  const text = result?.content?.find((c) => c.type === 'text')?.text;
  if (!text) {
    throw new Error('Missing text response from MCP tool call');
  }
  const parsed = JSON.parse(text);
  if (!parsed || typeof parsed !== 'object' || !('ok' in parsed)) {
    throw new Error(`Malformed tool envelope: ${text.slice(0, 400)}`);
  }
  return parsed;
}

async function callTool(client, name, args) {
  const raw = await client.callTool({ name, arguments: args });
  return parseEnvelope(raw);
}

async function callToolWithRetry(client, name, args, label) {
  let lastErr = null;
  for (let attempt = 1; attempt <= MAX_RETRIES; attempt += 1) {
    try {
      const envelope = await callTool(client, name, args);
      if (envelope.ok === true) {
        return envelope;
      }
      const toolErr = envelope.error || { code: 'unknown_error', message: `Unknown failure in ${label}` };
      if (!isTransientError(toolErr) || attempt === MAX_RETRIES) {
        throw new Error(`${label} failed (${toolErr.code ?? 'error'}): ${toolErr.message ?? 'unknown'}`);
      }
    } catch (err) {
      lastErr = err;
      if (!isTransientError(err) || attempt === MAX_RETRIES) {
        throw err;
      }
    }
    await sleep(300 * 2 ** (attempt - 1));
  }
  throw lastErr ?? new Error(`${label} failed after retries`);
}

function chunksOf(arr, size) {
  const out = [];
  for (let i = 0; i < arr.length; i += size) {
    out.push(arr.slice(i, i + size));
  }
  return out;
}

function findDuplicateAccountNames(accounts) {
  const counts = new Map();
  for (const row of accounts || []) {
    const name = String(row?.name || '');
    if (!name) continue;
    counts.set(name, (counts.get(name) || 0) + 1);
  }
  return [...counts.entries()].filter(([, n]) => n > 1).map(([name]) => name);
}

function buildAccountTargets(actualPayload, existingAccounts) {
  if (!actualPayload?.account_ids_by_key || typeof actualPayload.account_ids_by_key !== 'object') {
    throw new Error('Payload missing actual.account_ids_by_key mapping.');
  }

  const dupes = findDuplicateAccountNames(existingAccounts);
  if (dupes.length > 0) {
    throw new Error(`Duplicate account names detected in target budget: ${dupes.join(', ')}`);
  }

  const byId = new Map((existingAccounts || []).map((a) => [String(a.id), a]));
  const targets = new Map();

  for (const [accountKey, accountName] of Object.entries(actualPayload.accounts || {})) {
    const accountId = String(actualPayload.account_ids_by_key?.[accountKey] || '');
    if (!accountId) {
      throw new Error(`Missing account id for account key ${accountKey} in payload.actual.account_ids_by_key`);
    }
    const account = byId.get(accountId);
    if (!account) {
      throw new Error(`Configured account id ${accountId} for ${accountKey} not found in budget accounts.`);
    }
    if (String(account.name) !== String(accountName)) {
      throw new Error(
        `Account name mismatch for ${accountKey}: payload='${accountName}' actual='${String(account.name)}' id=${accountId}`
      );
    }
    targets.set(accountKey, { account_id: accountId, account_name: String(accountName) });
  }

  return targets;
}

function pickBudgetBySyncId(budgets) {
  if (!REQUIRED_SYNC_ID) {
    throw new Error('ACTUAL_BUDGET_SYNC_ID is required for remote reconcile.');
  }

  const localBudgets = (budgets || []).filter((b) => b && typeof b.id === 'string');
  if (localBudgets.length === 0) {
    throw new Error('No local budget id was returned by list_budgets.');
  }

  const match = localBudgets.find(
    (b) => b.id === REQUIRED_SYNC_ID || b.groupId === REQUIRED_SYNC_ID || b.cloudFileId === REQUIRED_SYNC_ID
  );
  if (!match) {
    const known = localBudgets.map((b) => ({ id: b.id, groupId: b.groupId, cloudFileId: b.cloudFileId, name: b.name }));
    throw new Error(
      `Canonical budget sync id ${REQUIRED_SYNC_ID} (${CANONICAL_BUDGET_NAME}) not found in list_budgets. known=${JSON.stringify(known)}`
    );
  }
  return match;
}

async function main() {
  const payload = JSON.parse(await fs.readFile(PAYLOAD_PATH, 'utf8'));
  if (
    !payload?.actual?.accounts ||
    !payload?.actual?.account_ids_by_key ||
    !payload?.actual?.category_groups ||
    !payload?.actual?.transactions_by_account_key
  ) {
    throw new Error('Payload missing expected actual.* keys including account_ids_by_key');
  }

  const transport = new StdioClientTransport({
    command: 'node',
    args: [MCP_SERVER_ENTRY],
    cwd: MCP_SERVER_CWD,
    env: {
      ACTUAL_PASSWORD: process.env.ACTUAL_PASSWORD || '',
      ACTUAL_BUDGET_SYNC_ID: process.env.ACTUAL_BUDGET_SYNC_ID || '',
      ACTUAL_DATA_DIR: process.env.ACTUAL_DATA_DIR || '/tmp/actual-remote-reconcile',
      ACTUAL_SERVER_URL: process.env.ACTUAL_SERVER_URL || '',
      PATH: process.env.PATH || '',
      HOME: process.env.HOME || '/tmp',
      LANG: process.env.LANG || 'C.UTF-8',
    },
    stderr: 'pipe',
  });
  if (transport.stderr) {
    transport.stderr.on('data', () => {});
  }

  const client = new Client({ name: 'actual-remote-reconcile', version: '1.0.0' }, { capabilities: {} });

  const summary = {
    ok: false,
    as_of: new Date().toISOString(),
    payload_path: PAYLOAD_PATH,
    output_path: OUTPUT_PATH,
    budget: null,
    categories: {
      groups_created: 0,
      categories_created: 0,
      total_categories: 0,
    },
    accounts: {
      created: 0,
      by_key: {},
    },
    import_missing: {
      chunk_size: CHUNK_SIZE,
      missing_total: 0,
      imported_total: 0,
      added_total: 0,
      updated_total: 0,
      skipped_total: 0,
      errors_total: 0,
      per_account: {},
    },
    retag: {
      checked_total: 0,
      updated_total: 0,
      mismatches_remaining: 0,
      per_account: {},
    },
    verification: {
      counts_actual: {},
      counts_expected: {},
      totals: {
        actual: 0,
        expected: 0,
      },
    },
    sync: {
      attempted: false,
      ok: false,
    },
    warnings: [],
    errors: [],
  };

  try {
    await client.connect(transport);

    const budgetsEnv = await callToolWithRetry(client, 'system', { operation: 'list_budgets' }, 'system.list_budgets');
    const budget = pickBudgetBySyncId(Array.isArray(budgetsEnv.data) ? budgetsEnv.data : []);
    summary.budget = budget;

    await callToolWithRetry(client, 'system', { operation: 'load_budget', budget_id: budget.id }, 'system.load_budget');

    const bindingEnv = await callToolWithRetry(
      client,
      'system',
      { operation: 'verify_remote_binding' },
      'system.verify_remote_binding'
    );
    const binding = bindingEnv?.data || {};
    if (binding.source_mode !== 'remote') {
      throw new Error(`Expected remote source_mode, got ${String(binding.source_mode)}`);
    }
    if (String(binding.selected_budget_group_id || '') !== REQUIRED_SYNC_ID) {
      throw new Error(
        `Loaded budget does not match ACTUAL_BUDGET_SYNC_ID. expected=${REQUIRED_SYNC_ID} actual=${String(binding.selected_budget_group_id || '')}`
      );
    }

    const groupsEnv = await callToolWithRetry(client, 'category', { operation: 'groups_list' }, 'category.groups_list');
    const groupByName = new Map((Array.isArray(groupsEnv.data) ? groupsEnv.data : []).map((g) => [String(g.name), g]));

    for (const groupSpec of payload.actual.category_groups) {
      let group = groupByName.get(String(groupSpec.name));
      if (!group) {
        const created = await callToolWithRetry(
          client,
          'category',
          { operation: 'group_create', data: { name: groupSpec.name, is_income: groupSpec.is_income === true } },
          `category.group_create(${groupSpec.name})`
        );
        summary.categories.groups_created += 1;
        group = { id: created.data.group_id, name: groupSpec.name, categories: [] };
        groupByName.set(String(groupSpec.name), group);
      }

      const existingNames = new Set((group.categories || []).map((c) => String(c.name)));
      for (const categoryName of groupSpec.categories || []) {
        if (existingNames.has(String(categoryName))) continue;
        await callToolWithRetry(
          client,
          'category',
          { operation: 'create', data: { name: categoryName, group_id: group.id } },
          `category.create(${categoryName})`
        );
        summary.categories.categories_created += 1;
        existingNames.add(String(categoryName));
      }
    }

    const categoriesEnv = await callToolWithRetry(client, 'category', { operation: 'list' }, 'category.list');
    const categories = Array.isArray(categoriesEnv.data) ? categoriesEnv.data : [];
    const categoryIdByName = new Map();
    for (const c of categories) {
      if (c && typeof c.name === 'string' && typeof c.id === 'string' && !categoryIdByName.has(c.name)) {
        categoryIdByName.set(c.name, c.id);
      }
    }
    summary.categories.total_categories = categories.length;

    const uncategorizedId = categoryIdByName.get('Uncategorized Review');
    if (!uncategorizedId) {
      throw new Error('Missing required fallback category: Uncategorized Review');
    }

    const accountsEnv = await callToolWithRetry(client, 'account', { operation: 'list' }, 'account.list');
    const existingAccounts = Array.isArray(accountsEnv.data) ? accountsEnv.data : [];
    const accountTargetsByKey = buildAccountTargets(payload.actual, existingAccounts);
    summary.accounts.by_key = Object.fromEntries(accountTargetsByKey.entries());

    const expectedByAccount = {};
    for (const [accountKey, txs] of Object.entries(payload.actual.transactions_by_account_key)) {
      const map = new Map();
      for (const tx of txs) {
        map.set(String(tx.imported_id), tx);
      }
      expectedByAccount[accountKey] = map;
    }

    let anyWrites = false;

    for (const [accountKey, target] of accountTargetsByKey.entries()) {
      const accountName = target.account_name;
      const accountId = target.account_id;

      const txListEnv = await callToolWithRetry(
        client,
        'transaction',
        {
          operation: 'list',
          account_id: accountId,
          start_date: '2000-01-01',
          end_date: '2100-12-31',
        },
        `transaction.list(${accountName})`
      );
      const existingRows = Array.isArray(txListEnv.data) ? txListEnv.data : [];

      const expectedMap = expectedByAccount[accountKey];
      const existingByImportedId = new Map();
      for (const row of existingRows) {
        if (row?.imported_id) {
          existingByImportedId.set(String(row.imported_id), row);
        }
      }

      const missingTx = [];
      for (const [importedId, tx] of expectedMap.entries()) {
        if (!existingByImportedId.has(importedId)) {
          missingTx.push(tx);
        }
      }

      summary.import_missing.per_account[accountKey] = {
        account_name: accountName,
        account_id: accountId,
        missing: missingTx.length,
        imported: 0,
        added: 0,
        updated: 0,
        skipped: 0,
        errors: 0,
        chunks: 0,
      };

      summary.import_missing.missing_total += missingTx.length;

      for (const chunk of chunksOf(missingTx, CHUNK_SIZE)) {
        const mapped = chunk.map((tx) => ({
          date: tx.date,
          amount: tx.amount,
          payee_name: tx.payee_name || undefined,
          imported_payee: tx.imported_payee || undefined,
          category: categoryIdByName.get(tx.category_name) || uncategorizedId,
          notes: tx.notes || undefined,
          imported_id: tx.imported_id,
          cleared: tx.cleared,
        }));

        const importEnv = await callToolWithRetry(
          client,
          'transaction',
          {
            operation: 'import',
            account_id: accountId,
            transactions: mapped,
            default_cleared: true,
            dry_run: false,
          },
          `transaction.import(${accountName})`
        );

        const result = importEnv.data?.result || {};
        const importedCount = Number(importEnv.data?.imported_count ?? mapped.length);
        const added = Array.isArray(result.added) ? result.added.length : 0;
        const updated = Array.isArray(result.updated) ? result.updated.length : 0;
        const errors = Array.isArray(result.errors) ? result.errors.length : 0;
        const skipped = Math.max(importedCount - added - updated - errors, 0);

        summary.import_missing.imported_total += importedCount;
        summary.import_missing.added_total += added;
        summary.import_missing.updated_total += updated;
        summary.import_missing.errors_total += errors;
        summary.import_missing.skipped_total += skipped;

        summary.import_missing.per_account[accountKey].imported += importedCount;
        summary.import_missing.per_account[accountKey].added += added;
        summary.import_missing.per_account[accountKey].updated += updated;
        summary.import_missing.per_account[accountKey].errors += errors;
        summary.import_missing.per_account[accountKey].skipped += skipped;
        summary.import_missing.per_account[accountKey].chunks += 1;

        if (importedCount > 0) {
          anyWrites = true;
        }
      }

      const refreshedEnv = await callToolWithRetry(
        client,
        'transaction',
        {
          operation: 'list',
          account_id: accountId,
          start_date: '2000-01-01',
          end_date: '2100-12-31',
        },
        `transaction.list.refreshed(${accountName})`
      );
      const refreshedRows = Array.isArray(refreshedEnv.data) ? refreshedEnv.data : [];

      summary.retag.per_account[accountKey] = {
        account_name: accountName,
        account_id: accountId,
        checked: refreshedRows.length,
        updated: 0,
      };
      summary.retag.checked_total += refreshedRows.length;

      for (const row of refreshedRows) {
        const importedId = row?.imported_id;
        if (!importedId) continue;
        const expectedTx = expectedMap.get(String(importedId));
        if (!expectedTx) continue;

        const expectedCategoryId = categoryIdByName.get(expectedTx.category_name) || uncategorizedId;
        const currentCategoryId = typeof row.category === 'string' ? row.category : row.category?.id;
        if (currentCategoryId === expectedCategoryId) continue;

        await callToolWithRetry(
          client,
          'transaction',
          {
            operation: 'update',
            transaction_id: row.id,
            data: { category: expectedCategoryId },
          },
          `transaction.update(${row.id})`
        );

        summary.retag.updated_total += 1;
        summary.retag.per_account[accountKey].updated += 1;
        anyWrites = true;
      }
    }

    if (anyWrites) {
      summary.sync.attempted = true;
      await callToolWithRetry(client, 'system', { operation: 'sync' }, 'system.sync');
      summary.sync.ok = true;
    }

    for (const [accountKey, target] of accountTargetsByKey.entries()) {
      const accountName = target.account_name;
      const accountId = target.account_id;

      const verifyEnv = await callToolWithRetry(
        client,
        'transaction',
        {
          operation: 'list',
          account_id: accountId,
          start_date: '2000-01-01',
          end_date: '2100-12-31',
        },
        `transaction.list.verify(${accountName})`
      );
      const rows = Array.isArray(verifyEnv.data) ? verifyEnv.data : [];
      const expectedCount = payload.actual.transactions_by_account_key[accountKey]?.length || 0;

      summary.verification.counts_actual[accountKey] = rows.length;
      summary.verification.counts_expected[accountKey] = expectedCount;
      summary.verification.totals.actual += rows.length;
      summary.verification.totals.expected += expectedCount;

      const expectedMap = expectedByAccount[accountKey];
      for (const row of rows) {
        const importedId = row?.imported_id;
        if (!importedId) continue;
        const expectedTx = expectedMap.get(String(importedId));
        if (!expectedTx) continue;
        const expectedCategoryId = categoryIdByName.get(expectedTx.category_name) || uncategorizedId;
        const currentCategoryId = typeof row.category === 'string' ? row.category : row.category?.id;
        if (currentCategoryId !== expectedCategoryId) {
          summary.retag.mismatches_remaining += 1;
        }
      }
    }

    if (summary.verification.totals.actual !== summary.verification.totals.expected) {
      summary.warnings.push('Final transaction totals differ from payload totals.');
    }
    if (summary.retag.mismatches_remaining > 0) {
      summary.warnings.push(`Category mismatches remaining: ${summary.retag.mismatches_remaining}`);
    }

    summary.ok = summary.import_missing.errors_total === 0 && summary.retag.mismatches_remaining === 0;
    summary.as_of = new Date().toISOString();

    await fs.writeFile(OUTPUT_PATH, JSON.stringify(summary, null, 2), 'utf8');
    console.log(JSON.stringify(summary, null, 2));
  } catch (err) {
    summary.ok = false;
    summary.errors.push(err instanceof Error ? err.message : String(err));
    summary.as_of = new Date().toISOString();
    await fs.writeFile(OUTPUT_PATH, JSON.stringify(summary, null, 2), 'utf8');
    console.log(JSON.stringify(summary, null, 2));
    process.exitCode = 1;
  } finally {
    await client.close().catch(() => {});
    await transport.close().catch(() => {});
  }
}

await main();
