import React, { useState } from "react";
import { Alert, FlatList, RefreshControl, Text, StyleSheet, View } from "react-native";
import { useFocusEffect } from "../useFocus";
import {
  createAdjustment,
  createPayout,
  listAdjustments,
  myOrg,
  teamBalances,
  voidAdjustment,
  type BalanceAdjustment,
  type TeamBalance,
} from "../api";
import { NoteModal } from "../components/NoteModal";
import { Btn, Chip, Field, Label, Screen, Sub, TopBar } from "../components/ui";
import { formatMoney, formatWhen } from "../format";
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

  const [userId, setUserId] = useState<number | null>(null);
  const [track, setTrack] = useState<"cash_on_hand" | "spendings">("spendings");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");

  const reload = async () => {
    try {
      setLoadError("");
      const voided =
        adjFilter === "voided" ? true : adjFilter === "active" ? false : undefined;
      const [list, org, adj] = await Promise.all([
        teamBalances(),
        myOrg(),
        listAdjustments({
          voided,
          user_id: adjUserFilter ?? undefined,
          track: adjTrackFilter || undefined,
        }),
      ]);
      setRows(list);
      setCurrency(org.currency);
      setAdjustments(adj);
      if (userId == null && list[0]) setUserId(list[0].user_id);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Failed");
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setLoading(false);
    }
  };

  useFocusEffect(reload);
  React.useEffect(() => {
    void reload();
  }, [adjFilter, adjUserFilter, adjTrackFilter]);

  const settle = async (
    item: TeamBalance,
    kind: "expense_payout" | "income_handover",
  ) => {
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
    Alert.alert("Fos", label, [
      { text: "Cancel", style: "cancel" },
      {
        text: "Settle",
        onPress: async () => {
          markBusy(true);
          try {
            await createPayout({
              user_id: item.user_id,
              kind,
              amount: value,
              payment_method: "cash",
              note:
                kind === "expense_payout"
                  ? "quick pay from balances"
                  : "quick take from balances",
            });
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
    const value = Number(amount.replace(",", "."));
    if (!userId || !value || !note.trim()) {
      Alert.alert("Fos", "Pick teammate, signed amount, and note");
      return;
    }
    markBusy(true);
    try {
      await createAdjustment({
        user_id: userId,
        track,
        amount: value,
        note: note.trim(),
      });
      setAmount("");
      setNote("");
      await reload();
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      markBusy(false);
    }
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
            />
            <Label>Note</Label>
            <Field value={note} onChangeText={setNote} placeholder="Opening balance / correction" />
            <Btn title={isBusy ? "…" : "Post adjustment"} onPress={postAdjustment} disabled={isBusy} />
            <Label>Adjustments</Label>
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
                      disabled={isBusy}
                      onPress={() => setVoidId(a.id)}
                    />
                  )}
                </View>
              ))
            )}
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
                disabled={isBusy || (item.available_spendings ?? item.spendings) <= 0}
                onPress={() => settle(item, "expense_payout")}
              />
              <Btn
                title="Take cash"
                variant="ghost"
                disabled={isBusy || (item.available_cash ?? item.cash_on_hand) <= 0}
                onPress={() => settle(item, "income_handover")}
              />
            </View>
          </View>
        )}
      />
      <NoteModal
        visible={voidId != null}
        title="Void adjustment"
        required
        onCancel={() => setVoidId(null)}
        onSubmit={async (voidNote) => {
          const id = voidId;
          setVoidId(null);
          if (id == null) return;
          markBusy(true);
          try {
            await voidAdjustment(id, voidNote);
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
