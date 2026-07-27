import React, { useState } from "react";
import { Alert, Text, StyleSheet, View } from "react-native";
import { useFocusEffect } from "../useFocus";
import { myReport, type MyReport } from "../api";
import { Card, Chip, Label, Screen, Sub, TopBar } from "../components/ui";
import { colors } from "../theme";

const PERIODS: { label: string; days?: number }[] = [
  { label: "all" },
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
];

export function MyReportScreen({ onBack }: { onBack: () => void }) {
  const [report, setReport] = useState<MyReport | null>(null);
  const [days, setDays] = useState<number | undefined>(undefined);

  const reload = async () => {
    try {
      setReport(await myReport(days));
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    }
  };

  useFocusEffect(reload);
  React.useEffect(() => {
    void reload();
  }, [days]);

  return (
    <Screen scroll>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Text style={styles.title}>My stats</Text>
      <View style={styles.kinds}>
        {PERIODS.map((p) => (
          <Chip key={p.label} label={p.label} on={days === p.days} onPress={() => setDays(p.days)} />
        ))}
      </View>
      {!report ? (
        <Sub>Loading…</Sub>
      ) : (
        <>
          <Card>
            <Label>Cash on hand</Label>
            <Text style={styles.big}>
              {report.cash_on_hand.toLocaleString()} {report.currency}
            </Text>
            <Label>Spendings owed</Label>
            <Text style={styles.line}>{report.spendings.toLocaleString()}</Text>
            <Sub>{report.pending_count} pending</Sub>
          </Card>
          <Card>
            <Label>Approved totals</Label>
            <Text style={styles.line}>Expense: {report.approved_expense_total.toLocaleString()}</Text>
            <Text style={styles.line}>Fuel: {report.approved_fuel_total.toLocaleString()}</Text>
            <Text style={styles.line}>Income cash: {report.approved_income_cash.toLocaleString()}</Text>
          </Card>
          <Card>
            <Label>By purpose</Label>
            {(report.by_purpose ?? []).length === 0 ? (
              <Sub>No approved spend yet</Sub>
            ) : (
              (report.by_purpose ?? []).map((p) => (
                <Text key={p.purpose} style={styles.line}>
                  {p.purpose}: {p.total.toLocaleString()}
                </Text>
              ))
            )}
          </Card>
          <Card>
            <Label>By category</Label>
            {(report.by_category ?? []).length === 0 ? (
              <Sub>No approved records yet</Sub>
            ) : (
              (report.by_category ?? []).map((c) => (
                <Text key={`${c.kind}-${c.category}`} style={styles.line}>
                  {c.kind}/{c.category}: {c.total.toLocaleString()}
                </Text>
              ))
            )}
          </Card>
        </>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { color: colors.text, fontSize: 26, fontWeight: "700", marginVertical: 8 },
  big: { color: colors.text, fontSize: 24, fontWeight: "700" },
  line: { color: colors.text, marginTop: 6 },
  kinds: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
});
