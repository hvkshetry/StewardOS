import fs from "fs";
import path from "path";
import os from "os";
import api from "@actual-app/api";

const PAYLOAD_PATH = "/tmp/ingestion_payload.json";
const RESULT_PATH = "/tmp/actual_ingest_result.json";

function selectBudgetBySyncId(budgets, syncId) {
  if (!syncId || !syncId.trim()) {
    throw new Error("ACTUAL_BUDGET_SYNC_ID is required.");
  }
  const target = syncId.trim();
  const match = (budgets || []).find((b) => b && (b.id === target || b.groupId === target || b.cloudFileId === target));
  if (!match) {
    const known = (budgets || []).map((b) => ({ id: b?.id, groupId: b?.groupId, cloudFileId: b?.cloudFileId, name: b?.name }));
    throw new Error(`Budget sync id ${target} not found. known=${JSON.stringify(known)}`);
  }
  return { id: target, source: "sync_id" };
}

function byName(items) {
  const map = new Map();
  for (const item of items || []) {
    if (item && typeof item.name === "string") {
      map.set(item.name, item);
    }
  }
  return map;
}


function findDuplicateAccountNames(accounts) {
  const counts = new Map();
  for (const row of accounts || []) {
    const name = String(row?.name || "");
    if (!name) continue;
    counts.set(name, (counts.get(name) || 0) + 1);
  }
  return [...counts.entries()].filter(([, n]) => n > 1).map(([name]) => name);
}

function buildAccountTargets(actualPayload, existingAccounts) {
  if (!actualPayload?.account_ids_by_key || typeof actualPayload.account_ids_by_key !== "object") {
    throw new Error("Payload missing actual.account_ids_by_key mapping.");
  }

  const dupes = findDuplicateAccountNames(existingAccounts);
  if (dupes.length > 0) {
    throw new Error(`Duplicate account names detected in target budget: ${dupes.join(", ")}`);
  }

  const byId = new Map((existingAccounts || []).map((a) => [String(a.id), a]));
  const targets = new Map();

  for (const [accountKey, accountName] of Object.entries(actualPayload.accounts || {})) {
    const accountId = String(actualPayload.account_ids_by_key?.[accountKey] || "");
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

function chunk(arr, size) {
  const out = [];
  for (let i = 0; i < arr.length; i += size) {
    out.push(arr.slice(i, i + size));
  }
  return out;
}

async function ensureCategories(groupSpecs) {
  const groups = await api.getCategoryGroups();
  const groupsByName = byName(groups);
  const groupIdByName = new Map();

  for (const spec of groupSpecs) {
    if (groupsByName.has(spec.name)) {
      groupIdByName.set(spec.name, groupsByName.get(spec.name).id);
      continue;
    }
    const groupId = await api.createCategoryGroup({
      name: spec.name,
      is_income: spec.is_income ? true : false,
      hidden: false,
    });
    groupIdByName.set(spec.name, groupId);
  }

  const categories = await api.getCategories();
  const categoryByName = byName(categories);
  const categoryIdByName = new Map();
  for (const c of categories) {
    categoryIdByName.set(c.name, c.id);
  }

  for (const spec of groupSpecs) {
    const groupId = groupIdByName.get(spec.name);
    for (const categoryName of spec.categories) {
      if (categoryByName.has(categoryName)) {
        categoryIdByName.set(categoryName, categoryByName.get(categoryName).id);
        continue;
      }
      const categoryId = await api.createCategory({
        name: categoryName,
        group_id: groupId,
        is_income: spec.is_income ? true : false,
        hidden: false,
      });
      categoryIdByName.set(categoryName, categoryId);
    }
  }

  return categoryIdByName;
}

async function run() {
  const payload = JSON.parse(fs.readFileSync(PAYLOAD_PATH, "utf8"));
  const actual = payload.actual;
  if (!actual || !actual.accounts || !actual.account_ids_by_key || !actual.transactions_by_account_key) {
    throw new Error("Payload missing required actual.* fields including account_ids_by_key.");
  }

  const dataDir = process.env.ACTUAL_DATA_DIR || path.resolve(os.homedir(), ".actual");
  const serverURL = process.env.ACTUAL_SERVER_URL || "";
  const password = process.env.ACTUAL_PASSWORD || "";
  const syncId = process.env.ACTUAL_BUDGET_SYNC_ID || "";

  if (!serverURL) {
    throw new Error("ACTUAL_SERVER_URL is required. Local-only mode is not supported.");
  }
  if (!syncId) {
    throw new Error("ACTUAL_BUDGET_SYNC_ID is required in remote mode.");
  }

  if (!fs.existsSync(dataDir)) {
    fs.mkdirSync(dataDir, { recursive: true });
  }

  await api.init({ dataDir, serverURL, password });

  const budgets = await api.getBudgets();
  const selected = selectBudgetBySyncId(budgets, syncId);
  await api.downloadBudget(selected.id);

  const existingAccounts = await api.getAccounts();
  const accountTargetsByKey = buildAccountTargets(actual, existingAccounts);
  const categoryIdByName = await ensureCategories(actual.category_groups);

  const uncategorizedId = categoryIdByName.get("Uncategorized Review");
  if (!uncategorizedId) {
    throw new Error("Missing required category: Uncategorized Review");
  }

  const txByAccountKey = actual.transactions_by_account_key || {};
  const importSummary = {};
  const batchSize = 150;

  for (const [accountKey, txs] of Object.entries(txByAccountKey)) {
    const target = accountTargetsByKey.get(accountKey);
    if (!target) {
      throw new Error(`Unknown account key in payload: ${accountKey}`);
    }
    const accountName = target.account_name;
    const accountId = target.account_id;

    const prepared = txs.map((tx) => {
      const categoryId = categoryIdByName.get(tx.category_name) || uncategorizedId;
      return {
        account: accountId,
        date: tx.date,
        amount: tx.amount,
        payee_name: tx.payee_name,
        imported_payee: tx.imported_payee,
        category: categoryId,
        notes: tx.notes,
        imported_id: tx.imported_id,
        cleared: true,
      };
    });

    const chunks = chunk(prepared, batchSize);
    const chunkResults = [];
    for (const txChunk of chunks) {
      const result = await api.importTransactions(accountId, txChunk, {
        defaultCleared: true,
        dryRun: false,
      });
      chunkResults.push(result);
    }

    importSummary[accountKey] = {
      account_name: accountName,
      account_id: accountId,
      rows_payload: prepared.length,
      chunks: chunks.length,
      results: chunkResults,
    };
  }

  const postAccounts = await api.getAccounts();
  const result = {
    ok: true,
    generated_at: new Date().toISOString(),
    budget_selected: selected,
    account_count: postAccounts.length,
    category_count: (await api.getCategories()).length,
    import_summary: importSummary,
  };

  fs.writeFileSync(RESULT_PATH, JSON.stringify(result, null, 2), "utf8");
  console.log(JSON.stringify(result, null, 2));
  await api.shutdown();
}

run().catch(async (err) => {
  console.error("Actual ingestion failed:", err?.stack || err);
  try {
    await api.shutdown();
  } catch (_) {}
  process.exitCode = 1;
});
