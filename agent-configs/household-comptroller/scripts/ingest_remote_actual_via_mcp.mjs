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
const OUTPUT_PATH = process.env.INGESTION_RESULT_PATH || path.resolve(__dirname, '../output/actual_remote_ingestion_result.json');
const MCP_SERVER_CWD = process.env.ACTUAL_MCP_SERVER_CWD || path.join(REPO_ROOT, 'servers/actual-mcp');
const MCP_SERVER_ENTRY = process.env.ACTUAL_MCP_SERVER_ENTRY || path.join(REPO_ROOT, 'servers/actual-mcp/build/index.js');

const REQUIRED_SYNC_ID = process.env.ACTUAL_BUDGET_SYNC_ID || '';
const CANONICAL_BUDGET_NAME = process.env.ACTUAL_TARGET_BUDGET_NAME || 'Household Budget';
const CHUNK_SIZE = Number(process.env.INGESTION_CHUNK_SIZE || 100);
const MAX_RETRIES = Number(process.env.INGESTION_MAX_RETRIES || 5);

function isTransientError(errLike) {
  const msg = String(errLike?.message ?? errLike ?? '').toLowerCase();
  const code = String(errLike?.code ?? '').toLowerCase();
  if (['timeout', 'timed_out', 'network_error', 'internal_error', 'service_unavailable', 'rate_limit'].includes(code)) {
    return true;
  }
  return (
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
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (err) {
    throw new Error(`Failed to parse tool response JSON: ${String(err)} :: ${text.slice(0, 400)}`);
  }
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
      if (envelope?.ok === true) {
        return envelope;
      }

      const toolErr = envelope?.error || { code: 'unknown_error', message: `Unknown failure in ${label}` };
      const transient = isTransientError(toolErr);
      if (!transient || attempt === MAX_RETRIES) {
        throw new Error(`${label} failed (${toolErr.code ?? 'error'}): ${toolErr.message ?? 'unknown'}`);
      }

      const backoffMs = 300 * 2 ** (attempt - 1);
      await sleep(backoffMs);
    } catch (err) {
      lastErr = err;
      const transient = isTransientError(err);
      if (!transient || attempt === MAX_RETRIES) {
        throw err;
      }
      const backoffMs = 300 * 2 ** (attempt - 1);
      await sleep(backoffMs);
    }
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

function selectBudgetBySyncId(budgets) {
  if (!REQUIRED_SYNC_ID) {
    throw new Error('ACTUAL_BUDGET_SYNC_ID is required for remote ingestion.');
  }

  const withId = (budgets || []).filter((b) => b && typeof b === 'object' && typeof b.id === 'string');
  if (withId.length === 0) {
    throw new Error('No budget records with a local id were returned.');
  }

  const byId = withId.find(
    (b) => b.id === REQUIRED_SYNC_ID || b.groupId === REQUIRED_SYNC_ID || b.cloudFileId === REQUIRED_SYNC_ID
  );

  if (!byId) {
    const known = withId.map((b) => ({ id: b.id, groupId: b.groupId, cloudFileId: b.cloudFileId, name: b.name }));
    throw new Error(
      `Canonical budget sync id ${REQUIRED_SYNC_ID} (${CANONICAL_BUDGET_NAME}) not found in list_budgets. known=${JSON.stringify(known)}`
    );
  }

  return byId;
}

function summarizeImportResult(importData, mappedLength) {
  const result = importData?.result ?? {};
  const importedCount = Number(importData?.imported_count ?? mappedLength);
  const addedCount = Array.isArray(result.added) ? result.added.length : 0;
  const updatedCount = Array.isArray(result.updated) ? result.updated.length : 0;
  const errorCount = Array.isArray(result.errors) ? result.errors.length : 0;
  const skippedCount = Math.max(importedCount - addedCount - updatedCount - errorCount, 0);

  return {
    imported_count: importedCount,
    added_count: addedCount,
    updated_count: updatedCount,
    skipped_count: skippedCount,
    error_count: errorCount,
  };
}

async function main() {
  const payloadRaw = await fs.readFile(PAYLOAD_PATH, 'utf8');
  const payload = JSON.parse(payloadRaw);

  if (
    !payload?.actual?.accounts ||
    !payload?.actual?.account_ids_by_key ||
    !payload?.actual?.category_groups ||
    !payload?.actual?.transactions_by_account_key
  ) {
    throw new Error('Payload is missing expected actual.* keys including account_ids_by_key.');
  }

  const transport = new StdioClientTransport({
    command: 'node',
    args: [MCP_SERVER_ENTRY],
    cwd: MCP_SERVER_CWD,
    env: {
      ACTUAL_PASSWORD: process.env.ACTUAL_PASSWORD || '',
      ACTUAL_BUDGET_SYNC_ID: process.env.ACTUAL_BUDGET_SYNC_ID || '',
      ACTUAL_DATA_DIR: process.env.ACTUAL_DATA_DIR || '/tmp/actual-remote-orchestrated',
      ACTUAL_SERVER_URL: process.env.ACTUAL_SERVER_URL || '',
      PATH: process.env.PATH || '',
      HOME: process.env.HOME || '/tmp',
      LANG: process.env.LANG || 'C.UTF-8',
    },
    stderr: 'pipe',
  });

  if (transport.stderr) {
    transport.stderr.on('data', () => {
      // Keep output quiet; failures are surfaced via envelopes.
    });
  }

  const client = new Client({ name: 'actual-remote-ingestion', version: '1.0.0' }, { capabilities: {} });

  const summary = {
    ok: false,
    as_of: new Date().toISOString(),
    payload_path: PAYLOAD_PATH,
    output_path: OUTPUT_PATH,
    remote: {
      server_url: process.env.ACTUAL_SERVER_URL || '',
      sync_id: process.env.ACTUAL_BUDGET_SYNC_ID || '',
      data_dir: process.env.ACTUAL_DATA_DIR || '/tmp/actual-remote-orchestrated',
    },
    budget: null,
    categories: {
      groups_created: 0,
      categories_created: 0,
      total_categories: 0,
    },
    accounts: {
      created: 0,
      total_accounts: 0,
      by_key: {},
    },
    import: {
      chunk_size: CHUNK_SIZE,
      attempted: 0,
      added: 0,
      updated: 0,
      skipped: 0,
      errors: 0,
      per_account: {},
    },
    retag: {
      checked: 0,
      updated: 0,
      skipped_no_imported_id: 0,
      missing_category_mapping: 0,
      per_account: {},
      mismatches_remaining: 0,
    },
    verification: {
      txn_counts_by_account: {},
      expected_counts_by_account: {},
      totals: {
        actual: 0,
        expected: 0,
      },
    },
    sync: {
      ok: false,
      attempts: 0,
    },
    warnings: [],
    errors: [],
  };

  try {
    await client.connect(transport);

    const budgetsEnv = await callToolWithRetry(client, 'system', { operation: 'list_budgets' }, 'system.list_budgets');
    const budgets = Array.isArray(budgetsEnv.data) ? budgetsEnv.data : [];
    const selectedBudget = selectBudgetBySyncId(budgets);
    summary.budget = selectedBudget;

    await callToolWithRetry(
      client,
      'system',
      { operation: 'load_budget', budget_id: selectedBudget.id },
      `system.load_budget(${selectedBudget.id})`
    );

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
    const groups = Array.isArray(groupsEnv.data) ? groupsEnv.data : [];
    const groupByName = new Map(groups.map((g) => [String(g.name), g]));

    for (const groupSpec of payload.actual.category_groups) {
      const groupName = String(groupSpec.name);
      let group = groupByName.get(groupName);

      if (!group) {
        const createGroupEnv = await callToolWithRetry(
          client,
          'category',
          {
            operation: 'group_create',
            data: { name: groupName, is_income: groupSpec.is_income === true },
          },
          `category.group_create(${groupName})`
        );
        summary.categories.groups_created += 1;
        group = {
          id: createGroupEnv?.data?.group_id,
          name: groupName,
          is_income: groupSpec.is_income === true,
          categories: [],
        };
        groupByName.set(groupName, group);
      }

      const existingCategoryNames = new Set((group.categories || []).map((c) => String(c.name)));
      for (const categoryNameRaw of groupSpec.categories || []) {
        const categoryName = String(categoryNameRaw);
        if (existingCategoryNames.has(categoryName)) {
          continue;
        }

        await callToolWithRetry(
          client,
          'category',
          {
            operation: 'create',
            data: {
              name: categoryName,
              group_id: group.id,
            },
          },
          `category.create(${categoryName})`
        );
        summary.categories.categories_created += 1;
        existingCategoryNames.add(categoryName);
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
      throw new Error('Required category "Uncategorized Review" is missing after ensure step.');
    }

    const accountsEnv = await callToolWithRetry(client, 'account', { operation: 'list' }, 'account.list');
    const existingAccounts = Array.isArray(accountsEnv.data) ? accountsEnv.data : [];
    const accountTargetsByKey = buildAccountTargets(payload.actual, existingAccounts);

    summary.accounts.total_accounts = existingAccounts.length;
    summary.accounts.by_key = Object.fromEntries(accountTargetsByKey.entries());

    const expectedCategoryByImportedId = new Map();

    for (const [accountKey, txs] of Object.entries(payload.actual.transactions_by_account_key)) {
      const target = accountTargetsByKey.get(accountKey);
      if (!target) {
        throw new Error(`No account target found for account key ${accountKey}`);
      }
      const accountName = target.account_name;
      const accountId = target.account_id;

      summary.import.per_account[accountKey] = {
        account_name: accountName,
        account_id: accountId,
        attempted: 0,
        added: 0,
        updated: 0,
        skipped: 0,
        errors: 0,
        chunks: 0,
      };

      for (const tx of txs) {
        expectedCategoryByImportedId.set(String(tx.imported_id), String(tx.category_name));
      }

      const txChunks = chunksOf(txs, CHUNK_SIZE);
      for (const txChunk of txChunks) {
        const mapped = txChunk.map((tx) => {
          const categoryId = categoryIdByName.get(tx.category_name) || uncategorizedId;
          const out = {
            date: tx.date,
            amount: tx.amount,
            payee_name: tx.payee_name,
            imported_payee: tx.imported_payee,
            category: categoryId,
            notes: tx.notes,
            imported_id: tx.imported_id,
            cleared: tx.cleared,
          };
          if (!out.payee_name) delete out.payee_name;
          if (!out.imported_payee) delete out.imported_payee;
          if (!out.notes) delete out.notes;
          return out;
        });

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

        const stats = summarizeImportResult(importEnv.data, mapped.length);
        summary.import.attempted += stats.imported_count;
        summary.import.added += stats.added_count;
        summary.import.updated += stats.updated_count;
        summary.import.skipped += stats.skipped_count;
        summary.import.errors += stats.error_count;

        summary.import.per_account[accountKey].attempted += stats.imported_count;
        summary.import.per_account[accountKey].added += stats.added_count;
        summary.import.per_account[accountKey].updated += stats.updated_count;
        summary.import.per_account[accountKey].skipped += stats.skipped_count;
        summary.import.per_account[accountKey].errors += stats.error_count;
        summary.import.per_account[accountKey].chunks += 1;
      }
    }

    const updateSyncEvery = 100;
    let updatesSinceLastSync = 0;

    for (const [accountKey, target] of accountTargetsByKey.entries()) {
      const accountName = target.account_name;
      const accountId = target.account_id;

      const listEnv = await callToolWithRetry(
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

      const rows = Array.isArray(listEnv.data) ? listEnv.data : [];
      summary.retag.per_account[accountKey] = {
        account_name: accountName,
        account_id: accountId,
        checked: 0,
        updated: 0,
      };

      for (const row of rows) {
        summary.retag.checked += 1;
        summary.retag.per_account[accountKey].checked += 1;

        const importedId = row?.imported_id;
        if (!importedId) {
          summary.retag.skipped_no_imported_id += 1;
          continue;
        }

        const expectedCategoryName = expectedCategoryByImportedId.get(String(importedId));
        if (!expectedCategoryName) {
          summary.retag.missing_category_mapping += 1;
          continue;
        }

        const expectedCategoryId = categoryIdByName.get(expectedCategoryName);
        if (!expectedCategoryId) {
          summary.retag.missing_category_mapping += 1;
          continue;
        }

        const currentCategoryId = typeof row.category === 'string' ? row.category : row.category?.id;
        if (currentCategoryId === expectedCategoryId) {
          continue;
        }

        await callToolWithRetry(
          client,
          'transaction',
          {
            operation: 'update',
            transaction_id: row.id,
            data: {
              category: expectedCategoryId,
            },
          },
          `transaction.update(${row.id})`
        );

        summary.retag.updated += 1;
        summary.retag.per_account[accountKey].updated += 1;
        updatesSinceLastSync += 1;

        if (updatesSinceLastSync >= updateSyncEvery) {
          summary.sync.attempts += 1;
          await callToolWithRetry(client, 'system', { operation: 'sync' }, 'system.sync(intermediate)');
          updatesSinceLastSync = 0;
          summary.sync.ok = true;
        }
      }

      summary.verification.txn_counts_by_account[accountKey] = {
        account_name: accountName,
        account_id: accountId,
        txn_count: rows.length,
      };
      summary.verification.expected_counts_by_account[accountKey] =
        payload.actual.transactions_by_account_key[accountKey]?.length || 0;
    }

    if (updatesSinceLastSync > 0 || summary.sync.attempts === 0) {
      summary.sync.attempts += 1;
      await callToolWithRetry(client, 'system', { operation: 'sync' }, 'system.sync(final)');
      summary.sync.ok = true;
    }

    const verificationList = [];
    for (const [accountKey, target] of accountTargetsByKey.entries()) {
      const accountName = target.account_name;
      const accountId = target.account_id;

      const listEnv = await callToolWithRetry(
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
      const rows = Array.isArray(listEnv.data) ? listEnv.data : [];
      verificationList.push([accountKey, rows]);
    }

    let mismatchesRemaining = 0;
    for (const [accountKey, rows] of verificationList) {
      const expectedCount = payload.actual.transactions_by_account_key[accountKey]?.length || 0;
      summary.verification.txn_counts_by_account[accountKey].txn_count = rows.length;
      summary.verification.expected_counts_by_account[accountKey] = expectedCount;
      summary.verification.totals.actual += rows.length;
      summary.verification.totals.expected += expectedCount;

      for (const row of rows) {
        const importedId = row?.imported_id;
        if (!importedId) continue;
        const expectedCategoryName = expectedCategoryByImportedId.get(String(importedId));
        if (!expectedCategoryName) continue;
        const expectedCategoryId = categoryIdByName.get(expectedCategoryName);
        if (!expectedCategoryId) continue;
        const currentCategoryId = typeof row.category === 'string' ? row.category : row.category?.id;
        if (currentCategoryId !== expectedCategoryId) {
          mismatchesRemaining += 1;
        }
      }
    }

    summary.retag.mismatches_remaining = mismatchesRemaining;

    if (summary.verification.totals.actual !== summary.verification.totals.expected) {
      summary.warnings.push('Total transaction count does not match payload expected count.');
    }
    if (mismatchesRemaining > 0) {
      summary.warnings.push(`Category mismatches remain: ${mismatchesRemaining}`);
    }

    summary.ok = summary.import.errors === 0 && mismatchesRemaining === 0;
    summary.as_of = new Date().toISOString();

    await fs.writeFile(OUTPUT_PATH, JSON.stringify(summary, null, 2), 'utf8');
    console.log(JSON.stringify(summary, null, 2));
  } catch (err) {
    summary.ok = false;
    summary.errors.push(err instanceof Error ? err.message : String(err));
    summary.as_of = new Date().toISOString();
    try {
      await fs.writeFile(OUTPUT_PATH, JSON.stringify(summary, null, 2), 'utf8');
    } catch {}
    console.log(JSON.stringify(summary, null, 2));
    process.exitCode = 1;
  } finally {
    await client.close().catch(() => {});
    await transport.close().catch(() => {});
  }
}

await main();
