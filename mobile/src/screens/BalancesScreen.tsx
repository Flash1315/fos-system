import React, { useEffect, useRef, useState } from "react";
import { Alert, FlatList, RefreshControl, Text, StyleSheet, View } from "react-native";
import {
  BILLING_READONLY_MSG,
  billingMe,
  createAdjustment,
  createPayout,
  idemKeyFor,
  isBillingReadOnly,
  listAdjustments,
  makeIdempotencyKey,
  myOrg,
  onResumeRefresh,
  teamBalances,
  voidAdjustment,
  type BalanceAdjustment,
  type TeamBalance,
} from "../api";
import { NoteModal } from "../components/NoteModal";
import { Btn, Chip, Field, Label, Screen, Sub, TopBar } from "../components/ui";
import { formatMoney, formatWhen, parseFiniteSignedMoney } from "../format";
import { colors } from "../theme";

export function BalancesScreen({
  busy,
  setBusy,
  onBack,
}: {
  busy?: boolean;
  setBusy?: (v: boolean) => void;
  onBack: () => void;
}) {
  const [rows, setRows] = useState<TeamBalance[]>([]);
  const [billingReadonly, setBillingReadonly] = useState(false);
  const [adjustments, setAdjustments] = useState<BalanceAdjustment[]>([]);
  const [currency, setCurrency] = useState("IDR");
  const [refreshing, setRefreshing] = useState(false);
  const [localBusy, setLocalBusy] = useState(false);
  const isBusy = busy ?? localBusy;
  const markBusy = setBusy ?? setLocalBusy;
  const [voidId, setVoidId] = useState<number | null>(null);
  const [adjFilter, setAdjFilter] = useState<"active" | "voided" | "all">("active");
  const [adjUserFilter, setAdjUserFilter] = useState<number | null>(null);
  const [adjTrackFilter, setAdjTrackFilter] = useState<"" | "cash_on_hand" | "spendings">("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [adjLoadError, setAdjLoadError] = useState("");
  const [adjHasMore, setAdjHasMore] = useState(false);
  const [loadingMoreAdj, setLoadingMoreAdj] = useState(false);
  const reloadGen = useRef(0);
  const payoutIdemRef = useRef<string | null>(null);
  const payoutSlotRef = useRef<string | null>(null);
  const adjustIdemRef = useRef<string | null>(null);
  const voidAdjIdemRef = useRef<string | null>(null);
  const voidAdjSlotRef = useRef<number | null>(null);
  const PAGE = 40;

  const [userId, setUserId] = useState<number | null>(null);
  const [track, setTrack] = useState<"cash_on_hand" | "spendings">("spendings");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");

  const adjParams = () => {
    const voided =
      adjFilter === "voided" ? true : adjFilter === "active" ? false : undefined;
    return {
      voided,
      user_id: adjUserFilter ?? undefined,
      track: adjTrackFilter || undefined,
      limit: PAGE,
    };
  };

  const reload = async () => {
    const gen = ++reloadGen.current;
    setLoading(true);
    try {
      setLoadError("");
      setAdjLoadError("");
      const [balRes, orgRes, adjRes] = await Promise.allSettled([
        teamBalances(),
        myOrg(),
        listAdjustments({ ...adjParams(), offset: 0 }),
      ]);
      if (gen !== reloadGen.current) return;
      const paneErrors: string[] = [];
      if (balRes.status === "fulfilled") {
        setRows(balRes.value);
        if (userId == null && balRes.value[0]) setUserId(balRes.value[0].user_id);
      } else {
        paneErrors.push(
          balRes.reason instanceof Error ? balRes.reason.message : "Balances failed",
        );
      }
      if (orgRes.status === "fulfilled") {
        setCurrency(orgRes.value.currency);
      } else {
        paneErrors.push(
          orgRes.reason instanceof Error ? orgRes.reason.message : "Company failed",
        );
      }
      if (adjRes.status === "fulfilled") {
        setAdjustments(adjRes.value);
        setAdjHasMore(adjRes.value.length >= PAGE);
      } else {
        // Retain previous adjustments pane on a transient list failure.
        setAdjLoadError(
          adjRes.reason instanceof Error ? adjRes.reason.message : "Adjustments failed",
        );
      }
      if (paneErrors.length) setLoadError(paneErrors.join(" · "));
    } finally {
      if (gen === reloadGen.current) setLoading(false);
    }
  };

  const loadMoreAdj = async () => {
    if (loadingMoreAdj || !adjHasMore || loading) return;
    const gen = reloadGen.current;
    setLoadingMoreAdj(true);
    try {
      const more = await listAdjustments({ ...adjParams(), offset: adjustments.length });
      if (gen !== reloadGen.current) return;
      setAdjustments((prev) => [...prev, ...more]);
      setAdjHasMore(more.length >= PAGE);
    } catch (e) {
      if (gen !== reloadGen.current) return;
      setLoadError(e instanceof Error ? e.message : "Load more failed");
    } finally {
      setLoadingMoreAdj(false);
    }
  };

  React.useEffect(() => {
    void reload();
  }, [adjFilter, adjUserFilter, adjTrackFilter]);

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

  React.useEffect(() => {
    adjustIdemRef.current = null;
  }, [userId, track, amount, note]);

  const settle = async (
    item: TeamBalance,
    kind: "expense_payout" | "income_handover",
  ) => {
    if (isBusy || billingReadonly) return;
    const value =
      kind === "expense_payout"
        ? item.available_spendings ?? item.spendings
        : item.available_cash ?? item.cash_on_hand;
    if (value <= 0) {
      Alert.alert(
        "Fos",
        kind === "expense_payout"
          ? "Nothing available (check reserved requests)"
          : "No available cash (check reserved requests)",
      );
      return;
    }
    const label =
      kind === "expense_payout"
        ? `Pay ${item.full_name} expense reimbursement ${formatMoney(value, currency)}?`
        : `Take cash handover ${formatMoney(value, currency)} from ${item.full_name}?`;
    const slot = `${item.user_id}:${kind}`;
    Alert.alert("Fos", label, [
      {
        text: "Cancel",
        style: "cancel",
        onPress: () => {
          if (payoutSlotRef.current === slot) {
            payoutIdemRef.current = null;
          }
        },
      },
      {
        text: "Settle",
        onPress: async () => {
          if (isBusy || billingReadonly) {
            if (billingReadonly) Alert.alert("Fos", BILLING_READONLY_MSG);
            return;
          }
          try {
            const b = await billingMe();
            const frozen = isBillingReadOnly(b.billing_status);
            setBillingReadonly(frozen);
            if (frozen) {
              Alert.alert("Fos", BILLING_READONLY_MSG);
              return;
            }
          } catch { /* API 403 if frozen */ }
          if (payoutSlotRef.current !== slot) {
            payoutSlotRef.current = slot;
            payoutIdemRef.current = null;
          }
          if (!payoutIdemRef.current) {
            payoutIdemRef.current = makeIdempotencyKey(
              kind === "expense_payout" ? "pay" : "cash",
            );
          }
          const settleKey = payoutIdemRef.current;
          markBusy(true);
          try {
            const list = await teamBalances();
            const fresh = list.find((b) => b.user_id === item.user_id);
            const available =
              kind === "expense_payout"
                ? fresh?.available_spendings ?? fresh?.spendings ?? 0
                : fresh?.available_cash ?? fresh?.cash_on_hand ?? 0;
            if (available + 1e-6 < value) {
              setRows(list);
              payoutIdemRef.current = null;
              Alert.alert(
                "Fos",
                `Only ${formatMoney(available, currency)} available now — refresh and retry`,
              );
              return;
            }
            await createPayout(
              {
                user_id: item.user_id,
                kind,
                amount: Math.min(value, available),
                payment_method: "cash",
                note:
                  kind === "expense_payout"
                    ? "quick pay from balances"
                    : "quick take from balances",
              },
              { idempotencyKey: settleKey },
            );
            payoutIdemRef.current = null;
            payoutSlotRef.current = null;
            await reload();
          } catch (e) {
            Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
          } finally {
            markBusy(false);
          }
        },
      },
    ]);
  };

  const postAdjustment = async () => {
    if (isBusy || billingReadonly) return;
    const value = parseFiniteSignedMoney(amount);
    if (!userId || value == null || !note.trim()) {
      Alert.alert("Fos", "Pick teammate, signed amount, and note");
      return;
    }
    const who = rows.find((r) => r.user_id === userId)?.full_name || "teammate";
    Alert.alert(
      "Fos",
      `Post ${track} adjustment ${formatMoney(value, currency)} for ${who}?`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Post",
          onPress: async () => {
            if (isBusy || billingReadonly) {
              if (billingReadonly) Alert.alert("Fos", BILLING_READONLY_MSG);
              return;
            }
            try {
              const b = await billingMe();
              const frozen = isBillingReadOnly(b.billing_status);
              setBillingReadonly(frozen);
              if (frozen) {
                Alert.alert("Fos", BILLING_READONLY_MSG);
                return;
              }
            } catch { /* API 403 if frozen */ }
            markBusy(true);
            try {
              if (!adjustIdemRef.current) adjustIdemRef.current = makeIdempotencyKey("adj");
              await createAdjustment(
                {
                  user_id: userId,
                  track,
                  amount: value,
                  note: note.trim(),
                },
                { idempotencyKey: adjustIdemRef.current },
              );
              adjustIdemRef.current = null;
              setAmount("");
              setNote("");
              await reload();
            } catch (e) {
              Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
            } finally {
              markBusy(false);
            }
          },
        },
      ],
    );
  };

  const emptyAdj =
    adjFilter === "voided"
      ? "No voided adjustments"
      : adjFilter === "active"
        ? "No active adjustments"
        : "No adjustments yet";
  const emptyAdjLabel =
    adjUserFilter != null || adjTrackFilter
      ? `${emptyAdj} for this filter`
      : emptyAdj;

  return (
    <Screen>
      <TopBar onBack={onBack} onCancel={onBack} />
      <FlatList
        data={rows}
        keyExtractor={(item) => String(item.user_id)}
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
        ListHeaderComponent={
          <View>
            <Text style={styles.title}>Team balances</Text>
      {billingReadonly ? <Sub>{BILLING_READONLY_MSG}</Sub> : null}
            <Sub>
              Spendings = my pocket owed. Cash = held cash on hand. Opening/corrections change the
              track without hitting P&L. Settled-period adjustments stay locked until that payout is
              voided.
            </Sub>
            <Label>Opening / correction</Label>
            <View style={styles.chips}>
              {rows.map((m) => (
                <Chip
                  key={m.user_id}
                  label={m.full_name}
                  on={userId === m.user_id}
                  onPress={() => setUserId(m.user_id)}
                />
              ))}
            </View>
            <View style={styles.chips}>
              <Chip
                label="Spendings"
                on={track === "spendings"}
                onPress={() => setTrack("spendings")}
              />
              <Chip
                label="Cash on hand"
                on={track === "cash_on_hand"}
                onPress={() => setTrack("cash_on_hand")}
              />
            </View>
            <Label>Signed amount (+ increases track)</Label>
            <Field
              keyboardType="numbers-and-punctuation"
              value={amount}
              onChangeText={setAmount}
              placeholder="e.g. 100000 or -5000"
              maxLength={24}
            />
            <Label>Note</Label>
            <Field value={note} onChangeText={setNote} placeholder="Opening balance / correction" maxLength={2000} />
            <Btn title={isBusy ? "…" : "Post adjustment"} onPress={postAdjustment} disabled={isBusy || billingReadonly} />
            <Label>Adjustments</Label>
            {adjLoadError ? <Sub>Adjustments refresh failed — {adjLoadError}</Sub> : null}
            <View style={styles.chips}>
              <Chip label="Active" on={adjFilter === "active"} onPress={() => setAdjFilter("active")} />
              <Chip label="Voided" on={adjFilter === "voided"} onPress={() => setAdjFilter("voided")} />
              <Chip label="All" on={adjFilter === "all"} onPress={() => setAdjFilter("all")} />
            </View>
            <View style={styles.chips}>
              <Chip
                label="Anyone"
                on={adjUserFilter == null}
                onPress={() => setAdjUserFilter(null)}
              />
              {rows.map((m) => (
                <Chip
                  key={`adj-${m.user_id}`}
                  label={m.full_name.split(" ")[0] || m.full_name}
                  on={adjUserFilter === m.user_id}
                  onPress={() => setAdjUserFilter(m.user_id)}
                />
              ))}
            </View>
            <View style={styles.chips}>
              <Chip
                label="Any track"
                on={adjTrackFilter === ""}
                onPress={() => setAdjTrackFilter("")}
              />
              <Chip
                label="Spendings"
                on={adjTrackFilter === "spendings"}
                onPress={() => setAdjTrackFilter("spendings")}
              />
              <Chip
                label="Cash"
                on={adjTrackFilter === "cash_on_hand"}
                onPress={() => setAdjTrackFilter("cash_on_hand")}
              />
            </View>
            {(adjFilter !== "active" || adjUserFilter != null || !!adjTrackFilter) && (
              <Btn
                title="Clear filters"
                variant="ghost"
                onPress={() => {
                  setAdjFilter("active");
                  setAdjUserFilter(null);
                  setAdjTrackFilter("");
                }}
              />
            )}
            {adjustments.length === 0 ? (
              <Sub>{emptyAdjLabel}</Sub>
            ) : (
              adjustments.map((a) => (
                <View key={a.id} style={styles.adjRow}>
                  <Text style={styles.adj}>
                    {a.user_name} · {a.track} · {formatMoney(a.amount, currency)}
                    {a.is_voided ? " · voided" : ""} — {a.note}
                    {!a.is_voided && !a.can_void
                      ? ` · ${a.void_blocked_reason || "locked"}`
                      : ""}
                  </Text>
                  {!!a.can_void && (
                    <Btn
                      title="Void"
                      variant="ghost"
                      disabled={isBusy || billingReadonly}
                      onPress={() => setVoidId(a.id)}
                    />
                  )}
                </View>
              ))
            )}
            {adjHasMore ? (
              <Btn
                title={loadingMoreAdj ? "…" : "Load more adjustments"}
                variant="ghost"
                disabled={loadingMoreAdj}
                onPress={() => void loadMoreAdj()}
              />
            ) : null}
            <Label>Settle</Label>
            <Sub>Tap to settle one teammate (uses available, not reserved).</Sub>
          </View>
        }
        ListEmptyComponent={
          <Sub>
            {loading
              ? "Loading..."
              : loadError
                ? `Could not load — ${loadError}`
                : "No teammates"}
          </Sub>
        }
        renderItem={({ item }) => (
          <View style={styles.row}>
            <Text style={styles.name}>
              {item.full_name} · {item.role}
            </Text>
            <Text style={styles.meta}>
              Cash {formatMoney(item.cash_on_hand, currency)}
              {item.last_income_handover_at
                ? ` (since ${formatWhen(item.last_income_handover_at)})`
                : ""}
              {" · "}
              Spendings {formatMoney(item.spendings, currency)}
              {item.last_expense_payout_at
                ? ` (since ${formatWhen(item.last_expense_payout_at)})`
                : ""}
              {item.pending_count ? ` · ${item.pending_count} pending` : ""}
            </Text>
            {((item.reserved_spendings || 0) > 0 || (item.reserved_cash || 0) > 0) && (
              <Text style={styles.meta}>
                Available spendings{" "}
                {formatMoney(item.available_spendings ?? item.spendings, currency)}
                {(item.reserved_spendings || 0) > 0
                  ? ` (reserved ${formatMoney(item.reserved_spendings || 0, currency)})`
                  : ""}
                {" · "}
                available cash {formatMoney(item.available_cash ?? item.cash_on_hand, currency)}
                {(item.reserved_cash || 0) > 0
                  ? ` (reserved ${formatMoney(item.reserved_cash || 0, currency)})`
                  : ""}
              </Text>
            )}
            <View style={styles.actions}>
              <Btn
                title="Pay spendings"
                variant="ghost"
                disabled={isBusy || billingReadonly || !!loadError || (item.available_spendings ?? item.spendings) <= 0}
                onPress={() => settle(item, "expense_payout")}
              />
              <Btn
                title="Take cash"
                variant="ghost"
                disabled={isBusy || billingReadonly || !!loadError || (item.available_cash ?? item.cash_on_hand) <= 0}
                onPress={() => settle(item, "income_handover")}
              />
            </View>
          </View>
        )}
      />
      <NoteModal
        visible={voidId != null}
        title="Void adjustment"
        label="Reason (required). Void reverses this opening/correction."
        required
        maxLength={2000}
        confirmTitle="Void"
        confirmVariant="danger"
        onCancel={() => setVoidId(null)}
        onSubmit={async (voidNote) => {
          const id = voidId;
          setVoidId(null);
          if (id == null) return;
          if (billingReadonly) {
            Alert.alert("Fos", BILLING_READONLY_MSG);
            return;
          }
          try {
            const b = await billingMe();
            const frozen = isBillingReadOnly(b.billing_status);
            setBillingReadonly(frozen);
            if (frozen) {
              Alert.alert("Fos", BILLING_READONLY_MSG);
              return;
            }
          } catch { /* API 403 if frozen */ }
          const noteKey = voidNote.replace(/\s+/g, " ").trim();
          const key = idemKeyFor(voidAdjIdemRef, voidAdjSlotRef, "avoid", `${id}:${noteKey}`);
          markBusy(true);
          try {
            await voidAdjustment(id, voidNote, { idempotencyKey: key });
            voidAdjIdemRef.current = null;
            voidAdjSlotRef.current = null;
            await reload();
          } catch (e) {
            Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
          } finally {
            markBusy(false);
          }
        }}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { color: colors.text, fontSize: 26, fontWeight: "700", marginVertical: 8 },
  chips: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
  adjRow: { marginBottom: 6 },
  adj: { color: colors.muted, fontSize: 13 },
  row: {
    backgroundColor: colors.card,
    borderRadius: 12,
    padding: 12,
    marginBottom: 8,
  },
  name: { fontWeight: "700", color: colors.text },
  meta: { color: colors.muted, marginTop: 4 },
  actions: { flexDirection: "row", gap: 8, marginTop: 8, flexWrap: "wrap" },
});
