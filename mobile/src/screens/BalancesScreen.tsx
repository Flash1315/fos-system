import React, { useState } from "react";
import { Alert, FlatList, RefreshControl, Text, StyleSheet, View } from "react-native";
import { useFocusEffect } from "../useFocus";
import { createPayout, myOrg, teamBalances, type TeamBalance } from "../api";
import { Btn, Screen, Sub, TopBar } from "../components/ui";
import { formatMoney } from "../format";
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
  const [currency, setCurrency] = useState("IDR");
  const [refreshing, setRefreshing] = useState(false);
  const [localBusy, setLocalBusy] = useState(false);
  const isBusy = busy ?? localBusy;
  const markBusy = setBusy ?? setLocalBusy;

  const reload = async () => {
    try {
      const [list, org] = await Promise.all([teamBalances(), myOrg()]);
      setRows(list);
      setCurrency(org.currency);
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    }
  };

  useFocusEffect(reload);

  const settle = async (
    item: TeamBalance,
    kind: "expense_payout" | "income_handover",
  ) => {
    const amount = kind === "expense_payout" ? item.spendings : item.cash_on_hand;
    if (amount <= 0) {
      Alert.alert("Fos", kind === "expense_payout" ? "Nothing owed" : "No cash held");
      return;
    }
    markBusy(true);
    try {
      await createPayout({
        user_id: item.user_id,
        kind,
        amount,
        payment_method: "cash",
        note: kind === "expense_payout" ? "quick pay from balances" : "quick take from balances",
      });
      await reload();
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      markBusy(false);
    }
  };

  return (
    <Screen>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Text style={styles.title}>Team balances</Text>
      <Sub>Spendings = my pocket owed. Cash = held cash on hand. Tap to settle one teammate.</Sub>
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
        ListEmptyComponent={<Sub>No teammates</Sub>}
        renderItem={({ item }) => (
          <View style={styles.row}>
            <Text style={styles.name}>
              {item.full_name} · {item.role}
            </Text>
            <Text style={styles.meta}>
              Cash {formatMoney(item.cash_on_hand, currency)} · Spendings{" "}
              {formatMoney(item.spendings, currency)}
              {item.pending_count ? ` · ${item.pending_count} pending` : ""}
            </Text>
            <View style={styles.actions}>
              <Btn
                title="Pay spendings"
                variant="ghost"
                disabled={isBusy || item.spendings <= 0}
                onPress={() => settle(item, "expense_payout")}
              />
              <Btn
                title="Take cash"
                variant="ghost"
                disabled={isBusy || item.cash_on_hand <= 0}
                onPress={() => settle(item, "income_handover")}
              />
            </View>
          </View>
        )}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { color: colors.text, fontSize: 26, fontWeight: "700", marginVertical: 8 },
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
