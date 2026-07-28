import React, { useEffect, useRef, useState } from "react";
import { Alert, FlatList, RefreshControl, Text, View, StyleSheet } from "react-native";
import {
  BILLING_READONLY_MSG,
  billingMe,
  decideBatch,
  decideRecord,
  idemKeyFor,
  isBillingReadOnly,
  makeIdempotencyKey,
  onResumeRefresh,
  pendingRecords,
  pendingSettlementCount,
  type MoneyRecord,
} from "../api";
import { NoteModal } from "../components/NoteModal";
import { Btn, Chip, Row, Screen, Sub, TopBar } from "../components/ui";
import { formatMoney, formatWhen } from "../format";
import { colors } from "../theme";

export function ApproveScreen({
  busy,
  setBusy,
  onBack,
  onRecord,
  onAccount,
}: {
  busy: boolean;
  setBusy: (v: boolean) => void;
  onBack: () => void;
  onRecord: (id: number) => void;
  onAccount?: () => void;
}) {
  const [rows, setRows] = useState<MoneyRecord[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [rejectId, setRejectId] = useState<number | null>(null);
  const [rejectAllOpen, setRejectAllOpen] = useState(false);
  const [purpose, setPurpose] = useState("");
  const [kind, setKind] = useState<"" | "expense" | "fuel" | "income">("");
  const [settlementPending, setSettlementPending] = useState(0);
  const reloadGen = useRef(0);
  const approveBatchIdemRef = useRef<string | null>(null);
  const approveBatchSlotRef = useRef<string | null>(null);
  const rejectBatchIdemRef = useRef<string | null>(null);
  const rejectBatchSlotRef = useRef<string | null>(null);
  const decideIdemRef = useRef<string | null>(null);
  const decideSlotRef = useRef<string | null>(null);
  const PAGE = 40;
  const [billingReadonly, setBillingReadonly] = useState(false);

  const reload = async () => {
    const gen = ++reloadGen.current;
    setLoading(true);
    try {
      setLoadError("");
      const list = await pendingRecords({
        purpose: purpose || undefined,
        kind: kind || undefined,
        limit: PAGE,
        offset: 0,
      });
      if (gen !== reloadGen.current) return;
      setRows(list);
      setHasMore(list.length >= PAGE);
      try {
        const settle = await pendingSettlementCount();
        if (gen !== reloadGen.current) return;
        setSettlementPending(settle.count);
      } catch {
        /* keep previous */
      }
    } catch (e) {
      if (gen !== reloadGen.current) return;
      setRows([]);
      setHasMore(false);
      setLoadError(e instanceof Error ? e.message : "Failed");
    } finally {
      if (gen === reloadGen.current) setLoading(false);
    }
  };

  const loadMore = async () => {
    if (loadingMore || !hasMore || loading) return;
    const gen = reloadGen.current;
    setLoadingMore(true);
    try {
      const more = await pendingRecords({
        purpose: purpose || undefined,
        kind: kind || undefined,
        limit: PAGE,
        offset: rows.length,
      });
      if (gen !== reloadGen.current) return;
      setRows((prev) => [...prev, ...more]);
      setHasMore(more.length >= PAGE);
    } catch (e) {
      if (gen !== reloadGen.current) return;
      Alert.alert("Fos", e instanceof Error ? e.message : "Load more failed");
    } finally {
      setLoadingMore(false);
    }
  };

  useEffect(() => {
    approveBatchIdemRef.current = null;
    approveBatchSlotRef.current = null;
    rejectBatchIdemRef.current = null;
    rejectBatchSlotRef.current = null;
    void reload();
  }, [purpose, kind]);

  useEffect(() => {
    void billingMe()
      .then((b) => setBillingReadonly(isBillingReadOnly(b.billing_status)))
      .catch(() => {});
  }, []);

  useEffect(() => onResumeRefresh(() => {
    void reload();
    void billingMe()
      .then((b) => setBillingReadonly(isBillingReadOnly(b.billing_status)))
      .catch(() => {});
  }), []);

  const runDecide = async (id: number, approve: boolean, note = "") => {
    if (busy || billingReadonly) return;
    if (approve) {
      const row = rows.find((r) => r.id === id);
      if (row?.created_by_active === false) {
        Alert.alert("Fos", "Cannot approve — teammate is inactive. Reject instead.");
        return;
      }
      if (row?.is_in_closed_cycle) {
        Alert.alert(
          "Fos",
          `This belongs to a settled period${
            row.settlement_cutoff_at ? ` (cutoff ${formatWhen(row.settlement_cutoff_at)})` : ""
          }. Approving will not change the current balance. Continue?`,
          [
            { text: "Cancel", style: "cancel" },
            {
              text: "Approve anyway",
              onPress: () => void doDecide(id, true, note, true),
            },
          ],
        );
        return;
      }
      Alert.alert("Fos", "Approve this record?", [
        { text: "Cancel", style: "cancel" },
        { text: "Approve", onPress: () => void doDecide(id, true, note, false) },
      ]);
      return;
    }
    await doDecide(id, approve, note);
  };

  const doDecide = async (id: number, approve: boolean, note = "", allowClosedCycle = false) => {
    if (busy || billingReadonly) {
      if (billingReadonly) Alert.alert("Fos", BILLING_READONLY_MSG);
      return;
    }
    const noteKey = note.replace(/\s+/g, " ").trim();
    const key = idemKeyFor(
      decideIdemRef,
      decideSlotRef,
      "decide",
      `${id}:${approve ? "a" : "r"}:${noteKey}`,
    );
    setBusy(true);
    try {
      await decideRecord(id, approve, note, { idempotencyKey: key, allowClosedCycle });
      decideIdemRef.current = null;
      decideSlotRef.current = null;
      await reload();
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  const approveAll = async () => {
    if (busy || billingReadonly || !rows.length) return;
    const closed = rows.filter((r) => r.is_in_closed_cycle);
    const go = async () => {
      if (busy || billingReadonly) {
        if (billingReadonly) Alert.alert("Fos", BILLING_READONLY_MSG);
        return;
      }
      setBusy(true);
      try {
        const slot = `a:${rows.map((r) => r.id).join(",")}`;
        if (approveBatchSlotRef.current !== slot) {
          approveBatchSlotRef.current = slot;
          approveBatchIdemRef.current = null;
        }
        if (!approveBatchIdemRef.current) {
          approveBatchIdemRef.current = makeIdempotencyKey("dbatch-a");
        }
        const res = await decideBatch(
          rows.map((r) => r.id),
          true,
          "",
          {
            idempotencyKey: approveBatchIdemRef.current,
            allowClosedCycle: closed.length > 0,
          },
        );
        approveBatchIdemRef.current = null;
        approveBatchSlotRef.current = null;
        if (res.skipped > 0) {
          const cash = res.skipped_insufficient_cash || 0;
          const inactive = res.skipped_inactive || 0;
          const closedSkip = res.skipped_closed_cycle || 0;
          const other = res.skipped - cash - inactive - closedSkip;
          const parts = [`Approved ${res.decided.length}`];
          if (cash > 0) parts.push(`skipped ${cash} (insufficient cash)`);
          if (inactive > 0) parts.push(`skipped ${inactive} (inactive teammate)`);
          if (closedSkip > 0) parts.push(`skipped ${closedSkip} (settled period)`);
          if (other > 0) parts.push(`skipped ${other} (already decided or missing)`);
          Alert.alert("Fos", parts.join("; "));
        }
        await reload();
      } catch (e) {
        Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
      } finally {
        setBusy(false);
      }
    };
    if (closed.length > 0) {
      Alert.alert(
        "Fos",
        `${closed.length} of ${rows.length} belong to a settled period and will not change current balances. Approve all anyway?`,
        [
          { text: "Cancel", style: "cancel" },
          { text: "Approve all", onPress: () => void go() },
        ],
      );
      return;
    }
    Alert.alert("Fos", `Approve all ${rows.length} pending record(s)?`, [
      { text: "Cancel", style: "cancel" },
      { text: "Approve all", onPress: () => void go() },
    ]);
  };

  const rejectAll = async (note: string) => {
    if (busy || billingReadonly || !rows.length) return;
    setBusy(true);
    try {
      const noteKey = (note || "batch reject").replace(/\s+/g, " ").trim();
      const key = idemKeyFor(
        rejectBatchIdemRef,
        rejectBatchSlotRef,
        "dbatch-r",
        `r:${rows.map((r) => r.id).join(",")}:${noteKey}`,
      );
      const res = await decideBatch(
        rows.map((r) => r.id),
        false,
        note || "batch reject",
        { idempotencyKey: key },
      );
      rejectBatchIdemRef.current = null;
      rejectBatchSlotRef.current = null;
      if (res.skipped > 0) {
        const cash = res.skipped_insufficient_cash || 0;
        const inactive = res.skipped_inactive || 0;
        const closedSkip = res.skipped_closed_cycle || 0;
        const other = res.skipped - cash - inactive - closedSkip;
        const parts = [`Rejected ${res.decided.length}`];
        if (cash > 0) parts.push(`skipped ${cash} (insufficient cash)`);
        if (inactive > 0) parts.push(`skipped ${inactive} (inactive teammate)`);
        if (closedSkip > 0) parts.push(`skipped ${closedSkip} (settled period)`);
        if (other > 0) parts.push(`skipped ${other} (already decided or missing)`);
        Alert.alert("Fos", parts.join("; "));
      }
      await reload();
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Text style={styles.title}>Approvals</Text>
      <Sub>
        Pending records{rows.length ? ` · showing ${rows.length}${hasMore ? "+" : ""}` : ""}
      </Sub>
      {billingReadonly ? <Sub>{BILLING_READONLY_MSG}</Sub> : null}
      {settlementPending > 0 && (
        <Btn
          title={`Settlement requests (${settlementPending})`}
          variant="secondary"
          onPress={() => {
            if (onAccount) onAccount();
            else Alert.alert("Fos", "Open Account to review settlement requests");
          }}
        />
      )}
      <View style={styles.kinds}>
        {(["", "expense", "fuel", "income"] as const).map((k) => (
          <Chip key={k || "any"} label={k || "any"} on={kind === k} onPress={() => setKind(k)} />
        ))}
      </View>
      <View style={styles.kinds}>
        {(["", "Rental", "Lesson", "Office", "Other"] as const).map((p) => (
          <Chip
            key={p || "any-p"}
            label={p || "any purpose"}
            on={purpose === p}
            onPress={() => setPurpose(p)}
          />
        ))}
      </View>
      {(!!purpose || !!kind) && (
        <Btn
          title="Clear filters"
          variant="ghost"
          onPress={() => {
            setPurpose("");
            setKind("");
          }}
        />
      )}
      {rows.length > 0 && (
        <Row>
          <Btn
            title={busy ? "…" : `Approve all (${rows.length})`}
            onPress={approveAll}
            disabled={busy || billingReadonly}
          />
          <Btn
            title="Reject all"
            variant="danger"
            onPress={() => setRejectAllOpen(true)}
            disabled={busy || billingReadonly}
          />
        </Row>
      )}
      <FlatList
        data={rows}
        keyExtractor={(item) => String(item.id)}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            tintColor={colors.accent}
            onRefresh={async () => {
              setRefreshing(true);
              await reload();
              setRefreshing(false);
            }}
          />
        }
        ListEmptyComponent={
          <Sub>
            {loading
              ? "Loading…"
              : loadError
                ? `Could not load — ${loadError}`
                : "No pending records"}
          </Sub>
        }
        ListFooterComponent={
          hasMore ? (
            <Btn
              title={loadingMore ? "…" : "Load more"}
              variant="ghost"
              disabled={loadingMore}
              onPress={() => void loadMore()}
            />
          ) : null
        }
        renderItem={({ item }) => (
          <View style={styles.row}>
            <Text style={styles.rowTitle} onPress={() => onRecord(item.id)}>
              {item.kind} · {formatMoney(item.amount, item.currency)}
            </Text>
            <Text style={styles.rowMeta}>
              {item.created_by_name || "—"} · {item.category || item.comment || "—"}
              {item.purpose ? ` · ${item.purpose}` : ""}
              {item.payment_source === "my_pocket"
                ? " · my pocket"
                : item.payment_source === "cash_on_hand"
                  ? " · cash"
                  : ""}
              {item.created_by_active === false ? " · Inactive teammate" : ""}
            </Text>
            <Text style={styles.rowMeta}>{formatWhen(item.created_at)}</Text>
            {!!item.is_in_closed_cycle && (
              <Text style={styles.warn}>
                Settled period
                {item.settlement_cutoff_at
                  ? ` · cutoff ${formatWhen(item.settlement_cutoff_at)}`
                  : ""}{" "}
                — will not change current balance
              </Text>
            )}
            <Row>
              <Btn
                title={item.created_by_active === false ? "Inactive" : "Approve"}
                disabled={busy || billingReadonly || item.created_by_active === false}
                onPress={() => runDecide(item.id, true)}
              />
              <Btn
                title="Reject"
                variant="danger"
                disabled={busy || billingReadonly}
                onPress={() => setRejectId(item.id)}
              />
            </Row>
          </View>
        )}
      />
      <NoteModal
        visible={rejectId != null}
        title="Reject record"
        required
        maxLength={2000}
        onCancel={() => setRejectId(null)}
        onSubmit={async (note) => {
          const id = rejectId;
          setRejectId(null);
          if (id != null) await runDecide(id, false, note);
        }}
      />
      <NoteModal
        visible={rejectAllOpen}
        title="Reject all pending"
        required
        maxLength={2000}
        onCancel={() => setRejectAllOpen(false)}
        onSubmit={async (note) => {
          setRejectAllOpen(false);
          await rejectAll(note);
        }}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { color: colors.text, fontSize: 26, fontWeight: "700", marginVertical: 8 },
  kinds: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
  row: { backgroundColor: colors.card, borderRadius: 12, padding: 12, marginBottom: 8 },
  rowTitle: { color: colors.text, fontWeight: "600", textTransform: "capitalize" },
  rowMeta: { color: colors.muted, marginTop: 4 },
  warn: { color: colors.warning, marginTop: 6, fontSize: 13 },
});
